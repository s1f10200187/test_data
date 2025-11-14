"""S3 upload utilities for local override layers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from botocore.exceptions import ClientError

from ..config import LayerConfig
from ..exceptions import LocalOverrideError, S3AccessError
from .file_collector import S3FileInfo


LOGGER = logging.getLogger(__name__)


class S3Uploader:
    """Uploads local files to S3 for layers configured with overrides."""

    def __init__(self, s3_client) -> None:
        self.s3_client = s3_client

    def upload_layer(self, layer: LayerConfig) -> List[S3FileInfo]:
        """Upload files from the local override path to the layer's S3 location."""
        if not layer.local_override_path:
            return []

        base_path = Path(layer.local_override_path).expanduser().resolve()
        if not base_path.exists():
            raise LocalOverrideError(
                f"Local override path does not exist for layer '{layer.name}': {base_path}"
            )
        if not base_path.is_dir():
            raise LocalOverrideError(
                f"Local override path must be a directory for layer '{layer.name}': {base_path}"
            )

        uploaded: List[S3FileInfo] = []
        prefix = layer.s3_prefix.rstrip("/")
        list_prefix = layer.s3_prefix
        if list_prefix and not list_prefix.endswith("/"):
            list_prefix = f"{list_prefix}/"

        if layer.clear_destination_before_upload:
            self._clear_destination(layer, list_prefix)

        for file_path in base_path.rglob("*"):
            if not file_path.is_file():
                continue

            filename = file_path.name
            if not layer.matches_filename(filename):
                continue

            relative_key = file_path.relative_to(base_path).as_posix()
            key = f"{prefix}/{relative_key}" if prefix else relative_key

            try:
                self.s3_client.upload_file(str(file_path), layer.s3_bucket, key)
            except ClientError as exc:  # pragma: no cover - depends on AWS
                raise S3AccessError(
                    f"Unable to upload {file_path} to s3://{layer.s3_bucket}/{key}: {exc}"
                ) from exc

            stat = file_path.stat()
            uploaded.append(
                S3FileInfo(
                    bucket=layer.s3_bucket,
                    key=key,
                    size=stat.st_size,
                    last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    layer_name=layer.name,
                    matched_pattern=layer.get_matched_pattern(filename),
                )
            )

        if not uploaded:
            raise LocalOverrideError(
                f"No files in local override path matched layer '{layer.name}' patterns: {base_path}"
            )

        return uploaded

    def _clear_destination(self, layer: LayerConfig, prefix: str) -> None:
        """Remove existing objects beneath the layer's configured prefix before upload."""
        if not prefix:
            raise S3AccessError(
                f"Layer '{layer.name}' clear_destination_before_upload requires a non-empty s3_prefix."
            )

        LOGGER.info(
            "Clearing existing objects under s3://%s/%s before upload",
            layer.s3_bucket,
            prefix,
        )

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=layer.s3_bucket, Prefix=prefix)
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise S3AccessError(
                f"Unable to list objects for s3://{layer.s3_bucket}/{prefix}: {exc}"
            ) from exc

        for page in pages:
            objects = page.get("Contents", [])
            keys: List[Dict[str, str]] = [
                {"Key": obj["Key"]} for obj in objects if obj.get("Key")
            ]
            if not keys:
                continue
            try:
                self.s3_client.delete_objects(
                    Bucket=layer.s3_bucket,
                    Delete={"Objects": keys, "Quiet": True},
                )
            except ClientError as exc:  # pragma: no cover - depends on AWS
                raise S3AccessError(
                    "Unable to delete objects for "
                    f"s3://{layer.s3_bucket}/{prefix}: {exc}"
                ) from exc
