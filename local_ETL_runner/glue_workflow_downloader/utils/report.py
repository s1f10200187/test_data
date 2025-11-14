"""Report generation utilities."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import ConfigManager, LayerConfig
from ..s3.file_collector import S3FileInfo
from ..s3.downloader import DownloadResult
from ..workflow.workflow_executor import WorkflowRunResult

LOGGER = logging.getLogger(__name__)


class ReportGenerator:
    """Produces human-readable and JSON reports summarising a run."""

    def generate(
        self,
        download_result: DownloadResult,
        workflow_result: Optional[WorkflowRunResult],
        config: ConfigManager,
        files: Dict[str, List[S3FileInfo]],
        config_path: Optional[str] = None,
    ) -> Dict[str, Path]:
        output_dir = Path(config.get_download_config().get("local_base_dir", "./downloads")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_name = f"report_{timestamp}"
        text_path = output_dir / f"{base_name}.txt"
        json_path = output_dir / f"{base_name}.json"

        layers = {layer.name: layer for layer in config.get_layers()}

        text_content = self._build_text_report(
            download_result, workflow_result, layers, files, config_path
        )
        json_content = self._build_json_report(
            download_result, workflow_result, layers, files, config_path, str(output_dir)
        )

        text_path.write_text(text_content, encoding="utf-8")
        json_path.write_text(json.dumps(json_content, default=self._json_serializer, indent=2), encoding="utf-8")

        LOGGER.info("Generated reports: %s, %s", text_path, json_path)
        return {"text": text_path, "json": json_path}

    def _build_text_report(
        self,
        download_result: DownloadResult,
        workflow_result: Optional[WorkflowRunResult],
        layers: Dict[str, LayerConfig],
        files: Dict[str, List[S3FileInfo]],
        config_path: Optional[str],
    ) -> str:
        lines: List[str] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append("=" * 80)
        lines.append("Glue Workflow ETL Download Report")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Generated At: {now_str}")
        if workflow_result is not None:
            lines.append(f"Workflow Name: {workflow_result.workflow_name}")
            lines.append(f"Workflow Status: {workflow_result.status}")
            if workflow_result.start_time:
                lines.append(f"Workflow Started: {workflow_result.start_time}")
            if workflow_result.end_time:
                lines.append(f"Workflow Finished: {workflow_result.end_time}")
            lines.append(f"Completed Jobs: {workflow_result.completed_jobs}")
            lines.append(f"Failed Jobs: {workflow_result.failed_jobs}")
        if config_path:
            lines.append(f"Configuration File: {config_path}")
        lines.append("")
        lines.append("Download Summary")
        lines.append("-" * 80)
        lines.append(f"Total Files: {download_result.total_files}")
        lines.append(f"Successful: {download_result.successful}")
        lines.append(f"Failed: {download_result.failed}")
        lines.append(f"Skipped: {download_result.skipped}")
        lines.append(f"Total Size (MB): {download_result.total_size_mb:.2f}")
        lines.append(f"Duration (s): {download_result.duration_seconds:.2f}")
        lines.append(f"Success Rate (%): {download_result.get_success_rate():.2f}")
        lines.append("")

        lines.append("Per Layer Details")
        lines.append("-" * 80)
        for layer_name, layer_config in layers.items():
            layer_files = files.get(layer_name, [])
            total_size = sum(file_info.get_size_mb() for file_info in layer_files)
            lines.append(f"[{layer_config.display_name}]")
            lines.append(f"Bucket: {layer_config.s3_bucket}")
            lines.append(f"Prefix: {layer_config.s3_prefix}")
            lines.append(f"File Count: {len(layer_files)}")
            lines.append(f"Total Size (MB): {total_size:.2f}")
            lines.append("Files:")
            for idx, file_info in enumerate(layer_files, start=1):
                lines.append(
                    f"  {idx}. {file_info.get_filename()} ({file_info.get_size_mb():.2f} MB) "
                    f"-> {file_info.get_s3_uri()}"
                )
            lines.append("")

        if download_result.failed_files:
            lines.append("Failed Downloads")
            lines.append("-" * 80)
            for file_info, message in download_result.failed_files:
                lines.append(f"- {file_info.get_s3_uri()} :: {message}")
            lines.append("")

        return "\n".join(lines)

    def _build_json_report(
        self,
        download_result: DownloadResult,
        workflow_result: Optional[WorkflowRunResult],
        layers: Dict[str, LayerConfig],
        files: Dict[str, List[S3FileInfo]],
        config_path: Optional[str],
        output_directory: str,
    ) -> Dict[str, object]:
        report: Dict[str, object] = {
            "generated_at": datetime.now(timezone.utc),
            "config_file": config_path,
            "output_directory": output_directory,
            "summary": {
                "total_files": download_result.total_files,
                "successful": download_result.successful,
                "failed": download_result.failed,
                "skipped": download_result.skipped,
                "total_size_mb": download_result.total_size_mb,
                "duration_seconds": download_result.duration_seconds,
                "success_rate": download_result.get_success_rate(),
            },
            "layers": [],
            "failed_files": [
                {"s3_uri": info.get_s3_uri(), "message": message}
                for info, message in download_result.failed_files
            ],
        }

        if workflow_result is not None:
            report["workflow"] = {
                "name": workflow_result.workflow_name,
                "run_id": workflow_result.run_id,
                "status": workflow_result.status,
                "start_time": workflow_result.start_time,
                "end_time": workflow_result.end_time,
                "duration_seconds": workflow_result.duration_seconds,
                "completed_jobs": workflow_result.completed_jobs,
                "failed_jobs": workflow_result.failed_jobs,
                "total_jobs": workflow_result.total_jobs,
                "success_rate": workflow_result.get_success_rate(),
                "error_message": workflow_result.error_message,
                "job_details": workflow_result.job_details,
            }

        for layer_name, layer_config in layers.items():
            layer_files = files.get(layer_name, [])
            report["layers"].append(
                {
                    "name": layer_name,
                    "display_name": layer_config.display_name,
                    "s3_bucket": layer_config.s3_bucket,
                    "s3_prefix": layer_config.s3_prefix,
                    "file_count": len(layer_files),
                    "total_size_mb": sum(file_info.get_size_mb() for file_info in layer_files),
                    "files": [
                        {
                            "filename": file_info.get_filename(),
                            "s3_uri": file_info.get_s3_uri(),
                            "size_mb": file_info.get_size_mb(),
                            "last_modified": file_info.last_modified,
                            "matched_pattern": file_info.matched_pattern,
                        }
                        for file_info in layer_files
                    ],
                }
            )

        return report

    @staticmethod
    def _json_serializer(value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc).isoformat()
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        raise TypeError(f"Object of type {type(value)!r} is not JSON serialisable")
