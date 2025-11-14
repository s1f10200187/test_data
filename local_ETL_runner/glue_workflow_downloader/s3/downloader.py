"""S3 file download utilities."""

from __future__ import annotations

import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from ..config import ConfigManager, LayerConfig
from ..exceptions import DownloadError, S3AccessError
from ..utils.progress import ProgressTracker
from .file_collector import S3FileInfo


@dataclass
class DownloadResult:
    """Summarises a download attempt."""

    total_files: int
    successful: int
    failed: int
    skipped: int
    total_size_mb: float
    duration_seconds: float
    failed_files: List[Tuple[S3FileInfo, str]]

    def get_success_rate(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.successful / self.total_files) * 100


class FileDownloader:
    """Handles downloading S3 objects to local storage."""

    def __init__(self, s3_client, config: ConfigManager, progress_tracker: ProgressTracker):
        self.s3_client = s3_client
        self.config = config
        self.progress_tracker = progress_tracker

    def download_files(self, files: Dict[str, List[S3FileInfo]]) -> DownloadResult:
        """Download all files grouped by layer."""
        tasks: List[Tuple[S3FileInfo, str, LayerConfig]] = []
        for file_infos in files.values():
            for file_info in file_infos:
                local_path = self._get_local_path(file_info)
                layer = self.config.get_layer_by_name(file_info.layer_name)
                if layer is None:
                    raise DownloadError(
                        f"Unknown layer '{file_info.layer_name}' encountered during download."
                    )
                tasks.append((file_info, local_path, layer))

        total_files = len(tasks)
        total_size_mb = sum(file_info.get_size_mb() for file_info, _, _ in tasks)
        if total_files == 0:
            return DownloadResult(0, 0, 0, 0, 0.0, 0.0, [])

        download_cfg = self.config.get_download_config()
        retry_count = int(download_cfg.get("retry_count", 3))
        retry_delay = float(download_cfg.get("retry_delay", 5))
        max_workers = max(int(download_cfg.get("max_workers", 5)), 1)

        successes = 0
        failures = 0
        skipped = 0
        failed_files: List[Tuple[S3FileInfo, str]] = []

        start_time = time.time()
        self.progress_tracker.start(total_files)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    self._download_with_retry,
                    file_info,
                    local_path,
                    layer,
                    retry_count,
                    retry_delay,
                ): (file_info, local_path)
                for file_info, local_path, layer in tasks
            }
            for future in as_completed(future_map):
                file_info, _ = future_map[future]
                try:
                    status = future.result()
                except DownloadError as exc:
                    failures += 1
                    failed_files.append((file_info, str(exc)))
                    self.progress_tracker.fail()
                    continue

                if status == "skipped":
                    skipped += 1
                    self.progress_tracker.skip()
                elif status == "success":
                    successes += 1
                    self.progress_tracker.advance()
                else:
                    failures += 1
                    failed_files.append((file_info, status))
                    self.progress_tracker.fail()

        duration_seconds = time.time() - start_time
        self.progress_tracker.finish()

        return DownloadResult(
            total_files=total_files,
            successful=successes,
            failed=failures,
            skipped=skipped,
            total_size_mb=total_size_mb,
            duration_seconds=duration_seconds,
            failed_files=failed_files,
        )

    def _download_with_retry(
        self,
        file_info: S3FileInfo,
        local_path: str,
        layer: LayerConfig,
        retry_count: int,
        retry_delay: float,
    ) -> str:
        if not self._should_download(file_info, local_path):
            return "skipped"

        attempts = 0
        while attempts <= retry_count:
            try:
                self._download_single_file(file_info, local_path, layer)
                return "success"
            except (ClientError, OSError) as exc:
                attempts += 1
                if attempts > retry_count:
                    raise DownloadError(f"Failed to download {file_info.get_s3_uri()}: {exc}") from exc
                time.sleep(retry_delay)
        return "failed"

    def _download_single_file(
        self,
        file_info: S3FileInfo,
        local_path: str,
        layer: Optional[LayerConfig],
    ) -> None:
        """Download a single S3 object to the specified path."""
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.s3_client.download_file(file_info.bucket, file_info.key, str(destination))
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise S3AccessError(f"Unable to download {file_info.get_s3_uri()}: {exc}") from exc
        self._maybe_extract_zip(destination, layer)

    def _maybe_extract_zip(self, destination: Path, layer: Optional[LayerConfig]) -> None:
        """Extract zip archives if the layer configuration requires it."""
        if layer is None or not layer.extract_zip_on_download:
            return
        if destination.suffix.lower() != ".zip":
            return

        extract_dir = destination.parent / destination.stem
        if extract_dir.exists():
            if extract_dir.is_dir():
                shutil.rmtree(extract_dir)
            else:
                extract_dir.unlink()

        try:
            with zipfile.ZipFile(destination, "r") as archive:
                archive.extractall(extract_dir)
        except (zipfile.BadZipFile, OSError) as exc:
            raise OSError(f"Failed to extract {destination}: {exc}") from exc

    def _get_local_path(self, file_info: S3FileInfo) -> str:
        download_cfg = self.config.get_download_config()
        base_dir = Path(download_cfg.get("local_base_dir", "./downloads")).resolve()
        preserve_structure = bool(download_cfg.get("preserve_structure", True))
        if preserve_structure:
            local_path = base_dir / "layers" / file_info.layer_name / file_info.get_filename()
        else:
            local_path = base_dir / file_info.get_filename()
        return str(local_path)

    def _should_download(self, file_info: S3FileInfo, local_path: str) -> bool:
        download_cfg = self.config.get_download_config()
        overwrite = bool(download_cfg.get("overwrite", False))
        destination = Path(local_path)
        if destination.exists() and not overwrite:
            return False
        return True
