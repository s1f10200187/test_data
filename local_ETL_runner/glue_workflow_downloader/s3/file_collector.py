"""S3 object discovery utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from ..config import ConfigManager, LayerConfig
from ..exceptions import InsufficientFilesError, S3AccessError, TooManyFilesError


@dataclass
class S3FileInfo:
    """Represents metadata about an S3 object."""

    bucket: str
    key: str
    size: int
    last_modified: datetime
    layer_name: str
    matched_pattern: Optional[str] = None

    def get_s3_uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"

    def get_filename(self) -> str:
        return os.path.basename(self.key)

    def get_size_mb(self) -> float:
        return self.size / (1024 * 1024)


class S3FileCollector:
    """Collects S3 file metadata for configured layers."""

    def __init__(self, s3_client, config: ConfigManager):
        self.s3_client = s3_client
        self.config = config

    def collect_files_for_layer(self, layer: LayerConfig) -> List[S3FileInfo]:
        """Return S3 file metadata for files matching the layer configuration."""
        objects = self._list_s3_objects(layer.s3_bucket, layer.s3_prefix)
        matched: List[S3FileInfo] = []

        for obj in objects:
            key = obj.get("Key")
            if not key:
                continue
            filename = os.path.basename(key)
            if not layer.matches_filename(filename):
                continue
            matched_pattern = layer.get_matched_pattern(filename)
            last_modified = obj.get("LastModified")
            if isinstance(last_modified, datetime):
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)
            else:
                last_modified = datetime.now(timezone.utc)
            matched.append(
                S3FileInfo(
                    bucket=layer.s3_bucket,
                    key=key,
                    size=obj.get("Size", 0),
                    last_modified=last_modified,
                    layer_name=layer.name,
                    matched_pattern=matched_pattern,
                )
            )

        file_count = len(matched)
        if not layer.validate_file_count(file_count):
            if file_count < layer.min_files:
                raise InsufficientFilesError(
                    f"Layer '{layer.name}' expected at least {layer.min_files} files, found {file_count}."
                )
            if layer.max_files is not None and file_count > layer.max_files:
                raise TooManyFilesError(
                    f"Layer '{layer.name}' expected at most {layer.max_files} files, found {file_count}."
                )

        return matched

    def collect_all_layers(self) -> Dict[str, List[S3FileInfo]]:
        """Return a mapping of layer name to the files discovered for that layer."""
        return self.collect_layers(self.config.get_layers())

    def collect_layers(self, layers: List[LayerConfig]) -> Dict[str, List[S3FileInfo]]:
        """Collect files only for the specified layers."""
        result: Dict[str, List[S3FileInfo]] = {}
        for layer in layers:
            result[layer.name] = self.collect_files_for_layer(layer)
        return result

    def _list_s3_objects(self, bucket: str, prefix: str) -> List[Dict[str, Any]]:
        """List S3 objects beneath the given bucket/prefix."""
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise S3AccessError(f"Unable to list objects for s3://{bucket}/{prefix}: {exc}") from exc

        objects: List[Dict[str, Any]] = []
        for page in pages:
            objects.extend(page.get("Contents", []))
        return objects
