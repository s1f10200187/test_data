"""Core application entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import ConfigManager, LayerConfig
from .exceptions import ConfigurationError, GlueWorkflowDownloaderError, LocalOverrideError
from .s3 import FileDownloader, S3FileCollector, S3FileInfo, S3Uploader
from .s3.downloader import DownloadResult
from .utils import ProgressTracker, configure_logging
from .utils.report import ReportGenerator
from .workflow import WorkflowExecutor, WorkflowRunResult, WorkflowValidator

LOGGER = logging.getLogger(__name__)


class GlueWorkflowDownloader:
    """Coordinates the workflow execution and S3 download process."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config = ConfigManager(config_path)
        self.config.load()

        configure_logging(self.config.get_logging_config())

        aws_config = self.config.get_aws_config()
        self.session = self._create_session(aws_config)
        self.glue_client = self.session.client("glue")
        self.s3_client = self.session.client("s3")

        self.workflow_validator = WorkflowValidator(self.glue_client, self.s3_client, self.config)
        self.workflow_executor = WorkflowExecutor(self.glue_client, self.config)
        self.file_collector = S3FileCollector(self.s3_client, self.config)
        self.progress_tracker = ProgressTracker()
        self.downloader = FileDownloader(self.s3_client, self.config, self.progress_tracker)
        self.report_generator = ReportGenerator()
        self.uploader = S3Uploader(self.s3_client)

    def run(
        self,
        workflow_name: str,
        *,
        execute: Optional[bool] = None,
        wait_for_completion: Optional[bool] = None,
        dry_run: bool = False,
        skip_validation: bool = False,
        execution_timeout: Optional[int] = None,
        polling_interval: Optional[int] = None,
    ) -> DownloadResult:
        """Execute the configured workflow and download matching files."""
        workflow_config = self.config.get_workflow_config()
        layers = self.config.get_layers()
        should_execute = workflow_config["execute"] if execute is None else bool(execute)
        should_wait = workflow_config["wait_for_completion"] if wait_for_completion is None else bool(wait_for_completion)
        timeout = execution_timeout or int(workflow_config["execution_timeout"])
        interval = polling_interval or int(workflow_config["polling_interval"])

        if dry_run:
            should_execute = False

        LOGGER.info("Starting download process for workflow '%s'", workflow_name)

        local_override_layers = [layer for layer in layers if layer.local_override_path]
        if local_override_layers:
            self._upload_local_overrides(local_override_layers, dry_run)

        if not skip_validation and workflow_config.get("validate_before_run", True):
            self._validate_workflow(workflow_name)
            self._check_initial_layer()

        pre_layers = [layer for layer in layers if layer.download_before_execution]
        post_layers = [layer for layer in layers if not layer.download_before_execution]

        pre_files: Dict[str, List[S3FileInfo]] = {}
        pre_result: Optional[DownloadResult] = None

        if pre_layers:
            LOGGER.info("Collecting pre-execution files for %s layers", len(pre_layers))
            pre_files = self._collect_files(pre_layers)
            if dry_run:
                LOGGER.info("Dry run: skipping download of pre-execution files")
            else:
                LOGGER.info("Downloading pre-execution files prior to workflow run")
                pre_result = self._download_files(pre_files)

        workflow_result: Optional[WorkflowRunResult] = None
        if should_execute:
            workflow_result = self._execute_workflow(
                workflow_name,
                wait_for_completion=should_wait,
                timeout=timeout,
                polling_interval=interval,
            )

        post_files: Dict[str, List[S3FileInfo]] = {}
        if post_layers:
            LOGGER.info("Collecting post-execution files for %s layers", len(post_layers))
            post_files = self._collect_files(post_layers)

        all_files = self._merge_file_maps(pre_files, post_files)

        if dry_run:
            return self._generate_dry_run_result(all_files, workflow_result)

        post_result = self._download_files(post_files)
        result = self._merge_download_results(pre_result, post_result)
        self._generate_report(result, workflow_result, all_files)
        LOGGER.info(
            "Download finished. Success=%s, Failed=%s, Skipped=%s",
            result.successful,
            result.failed,
            result.skipped,
        )
        return result

    def _generate_dry_run_result(
        self,
        files: Dict[str, List[S3FileInfo]],
        workflow_result: Optional[WorkflowRunResult],
    ) -> DownloadResult:
        total_files = sum(len(layer_files) for layer_files in files.values())
        total_size_mb = sum(file_info.get_size_mb() for layer_files in files.values() for file_info in layer_files)
        result = DownloadResult(
            total_files=total_files,
            successful=0,
            failed=0,
            skipped=total_files,
            total_size_mb=total_size_mb,
            duration_seconds=0.0,
            failed_files=[],
        )
        self._generate_report(result, workflow_result, files)
        LOGGER.info("Dry run completed. Files detected: %s", total_files)
        return result

    def _validate_workflow(self, workflow_name: str) -> None:
        LOGGER.debug("Validating workflow '%s'", workflow_name)
        self.workflow_validator.validate_workflow_exists(workflow_name)

    def _check_initial_layer(self) -> None:
        workflow_config = self.config.get_workflow_config()
        timeout = int(workflow_config.get("initial_layer_check_timeout", 300))
        LOGGER.debug("Checking initial layers with timeout %s seconds", timeout)
        self.workflow_validator.check_initial_layer_files(timeout=timeout)

    def _execute_workflow(
        self,
        workflow_name: str,
        *,
        wait_for_completion: bool,
        timeout: int,
        polling_interval: int,
    ) -> Optional[WorkflowRunResult]:
        LOGGER.info("Triggering workflow '%s'", workflow_name)
        run_id = self.workflow_executor.execute_workflow(workflow_name)
        LOGGER.info("Workflow '%s' started with run id %s", workflow_name, run_id)

        if not wait_for_completion:
            return None

        try:
            result = self.workflow_executor.wait_for_completion(
                workflow_name, run_id, timeout=timeout, polling_interval=polling_interval
            )
            LOGGER.info("Workflow '%s' completed successfully", workflow_name)
            return result
        except GlueWorkflowDownloaderError as exc:
            LOGGER.error("Workflow '%s' failed: %s", workflow_name, exc)
            raise

    def _collect_files(self, layers: Optional[List[LayerConfig]] = None) -> Dict[str, List[S3FileInfo]]:
        if layers is None:
            target_layers = self.config.get_layers()
        else:
            target_layers = layers
        LOGGER.info("Collecting files from S3 for %s layers", len(target_layers))
        if layers is None:
            return self.file_collector.collect_all_layers()
        return self.file_collector.collect_layers(target_layers)

    def _download_files(self, files: Dict[str, List[S3FileInfo]]) -> DownloadResult:
        LOGGER.info("Starting downloads for %s layers", len(files))
        return self.downloader.download_files(files)

    def _upload_local_overrides(self, layers: List[LayerConfig], dry_run: bool) -> None:
        if not layers:
            return
        if dry_run:
            LOGGER.info(
                "Dry run: skipping upload for %s local override layers", len(layers)
            )
            return
        LOGGER.info("Uploading local override files for %s layers", len(layers))
        for layer in layers:
            try:
                uploaded = self.uploader.upload_layer(layer)
            except LocalOverrideError:
                LOGGER.exception("Failed to upload local override files for layer '%s'", layer.name)
                raise
            LOGGER.info(
                "Uploaded %s file(s) from %s to s3://%s/%s",
                len(uploaded),
                layer.local_override_path,
                layer.s3_bucket,
                layer.s3_prefix,
            )

    @staticmethod
    def _merge_file_maps(*file_maps: Dict[str, List[S3FileInfo]]) -> Dict[str, List[S3FileInfo]]:
        merged: Dict[str, List[S3FileInfo]] = {}
        for mapping in file_maps:
            for layer_name, file_infos in mapping.items():
                merged.setdefault(layer_name, []).extend(file_infos)
        return merged

    @staticmethod
    def _merge_download_results(
        first: Optional[DownloadResult], second: Optional[DownloadResult]
    ) -> DownloadResult:
        if first is None and second is None:
            return DownloadResult(0, 0, 0, 0, 0.0, 0.0, [])
        if first is None:
            return second if second is not None else DownloadResult(0, 0, 0, 0, 0.0, 0.0, [])
        if second is None:
            return first
        return DownloadResult(
            total_files=first.total_files + second.total_files,
            successful=first.successful + second.successful,
            failed=first.failed + second.failed,
            skipped=first.skipped + second.skipped,
            total_size_mb=first.total_size_mb + second.total_size_mb,
            duration_seconds=first.duration_seconds + second.duration_seconds,
            failed_files=list(first.failed_files) + list(second.failed_files),
        )

    def _generate_report(
        self,
        result: DownloadResult,
        workflow_result: Optional[WorkflowRunResult],
        files: Dict[str, List[S3FileInfo]],
    ) -> None:
        try:
            self.report_generator.generate(
                result,
                workflow_result,
                self.config,
                files,
                str(self.config_path),
            )
        except OSError as exc:
            LOGGER.warning("Failed to generate report: %s", exc)

    @staticmethod
    def _create_session(aws_config: Dict[str, str]) -> boto3.session.Session:
        try:
            return boto3.session.Session(**aws_config)
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover - depends on AWS
            raise ConfigurationError(f"Unable to create AWS session: {exc}") from exc
