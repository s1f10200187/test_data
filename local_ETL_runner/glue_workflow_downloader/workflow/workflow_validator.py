"""Workflow validation helpers."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from botocore.exceptions import ClientError

from ..config import ConfigManager, LayerConfig
from ..exceptions import (
    InitialLayerFileNotFoundError,
    InsufficientFilesError,
    TooManyFilesError,
    ValidationError,
    WorkflowNotFoundError,
)


class WorkflowValidator:
    """Validates Glue workflow prerequisites."""

    _POLL_INTERVAL_SECONDS = 5

    def __init__(self, glue_client, s3_client, config: ConfigManager):
        self.glue_client = glue_client
        self.s3_client = s3_client
        self.config = config

    def validate_workflow_exists(self, workflow_name: str) -> bool:
        """Return True if the workflow exists; raise otherwise."""
        try:
            response = self.glue_client.get_workflow(Name=workflow_name, IncludeGraph=False)
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise WorkflowNotFoundError(f"Workflow '{workflow_name}' not found: {exc}") from exc

        workflow = response.get("Workflow") if response else None
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow '{workflow_name}' not found.")
        return True

    def check_initial_layer_files(self, timeout: int = 300) -> bool:
        """Ensure required layers expose the expected files."""
        required_layers = [layer for layer in self.config.get_layers() if layer.required]
        if not required_layers:
            return True

        deadline = time.time() + max(timeout, 0)
        last_counts: Dict[str, Tuple[int, List[str]]] = {}

        while time.time() <= deadline:
            all_ok = True
            last_counts.clear()
            for layer in required_layers:
                files = self._list_matching_files(layer)
                count = len(files)
                last_counts[layer.name] = (count, files)
                if count == 0 or not layer.validate_file_count(count):
                    all_ok = False
            if all_ok:
                return True
            time.sleep(self._POLL_INTERVAL_SECONDS)

        # Determine root cause from last collected counts
        for layer in required_layers:
            count, files = last_counts.get(layer.name, (0, []))
            if count == 0:
                raise InitialLayerFileNotFoundError(
                    f"No files found for required layer '{layer.name}' within {timeout} seconds."
                )
            if count < layer.min_files:
                raise InsufficientFilesError(
                    f"Layer '{layer.name}' provided {count} files, expected at least {layer.min_files}."
                )
            if layer.max_files is not None and count > layer.max_files:
                raise TooManyFilesError(
                    f"Layer '{layer.name}' provided {count} files, maximum allowed is {layer.max_files}."
                )

        raise ValidationError("Initial layer validation failed for unknown reasons.")

    def get_workflow_status(self, workflow_name: str) -> Dict[str, Any]:
        """Return the latest run status information for the workflow."""
        try:
            runs = self.glue_client.get_workflow_runs(Name=workflow_name, MaxResults=1)
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise WorkflowNotFoundError(f"Unable to query workflow runs: {exc}") from exc

        run_info = runs.get("Runs", [{}])[0]
        status = run_info.get("Status", "UNKNOWN")
        started_on = run_info.get("StartedOn")
        completed_on = run_info.get("CompletedOn")
        return {
            "status": status,
            "run_id": run_info.get("Id"),
            "started_on": self._coerce_datetime(started_on),
            "completed_on": self._coerce_datetime(completed_on),
        }

    def _list_matching_files(self, layer: LayerConfig) -> List[str]:
        """Return keys in S3 that satisfy the layer's file patterns."""
        paginator = self.s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=layer.s3_bucket, Prefix=layer.s3_prefix)
        matched: List[str] = []
        for page in page_iterator:
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                filename = key.rsplit("/", 1)[-1]
                if layer.matches_filename(filename):
                    matched.append(key)
        return matched

    @staticmethod
    def _coerce_datetime(value: Optional[Any]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        raise ValidationError(f"Unexpected datetime value: {value!r}")
