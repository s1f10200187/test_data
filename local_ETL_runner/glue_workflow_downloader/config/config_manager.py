"""Configuration management utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import re

import yaml

from ..exceptions import ConfigurationError, ValidationError


@dataclass
class LayerConfig:
    """Represents a single data lake layer configuration."""

    name: str
    display_name: str
    s3_bucket: str
    s3_prefix: str
    file_patterns: List[str]
    required: bool = False
    min_files: int = 0
    max_files: Optional[int] = None
    download_before_execution: bool = False
    local_override_path: Optional[str] = None
    clear_destination_before_upload: bool = False
    allowed_formats: List[str] = field(default_factory=list)
    extract_zip_on_download: bool = False

    def get_s3_path(self) -> str:
        """Return the fully qualified S3 path for the layer."""
        return f"s3://{self.s3_bucket}/{self.s3_prefix}".rstrip("/") + "/"

    def matches_filename(self, filename: str) -> bool:
        """Return True if the filename matches any configured pattern."""
        if self.get_matched_pattern(filename) is None:
            return False
        return self.matches_format(filename)

    def get_matched_pattern(self, filename: str) -> Optional[str]:
        """Return the pattern that matches the filename, if any."""
        for pattern in self.file_patterns:
            if re.match(pattern, filename):
                return pattern
        return None

    def matches_format(self, filename: str) -> bool:
        """Return True if the filename extension is allowed for this layer."""
        if not self.allowed_formats:
            return True
        suffix = Path(filename).suffix.lower().lstrip(".")
        return suffix in self.allowed_formats

    def validate_file_count(self, file_count: int) -> bool:
        """Return True if the file_count falls within the configured bounds."""
        if file_count < self.min_files:
            return False
        if self.max_files is not None and file_count > self.max_files:
            return False
        return True


class ConfigManager:
    """Handles loading and validation of the YAML configuration file."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._layers: Optional[List[LayerConfig]] = None
        self._layer_map: Optional[Dict[str, LayerConfig]] = None

    def load(self) -> Dict[str, Any]:
        """Load and validate the configuration file."""
        if not self.config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {self.config_path}")

        try:
            with self.config_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - passthrough
            raise ConfigurationError(f"Failed to parse configuration: {exc}") from exc

        self.config = data
        self.validate()
        self._layers = None  # reset cache after reloading
        self._layer_map = None
        return self.config

    def validate(self) -> bool:
        """Validate the loaded configuration contents."""
        if not isinstance(self.config, dict):
            raise ValidationError("Configuration must be a mapping.")

        aws_cfg = self.config.get("aws", {})
        if not isinstance(aws_cfg, dict) or not aws_cfg.get("region"):
            raise ValidationError("AWS region must be specified under aws.region.")

        workflow_cfg = self.config.get("workflow", {})
        if not isinstance(workflow_cfg, dict) or not workflow_cfg.get("name"):
            raise ValidationError("Workflow name must be specified under workflow.name.")

        layers_cfg = self.config.get("layers")
        if not isinstance(layers_cfg, list) or not layers_cfg:
            raise ValidationError("At least one layer must be defined under layers.")

        for index, layer in enumerate(layers_cfg):
            if not isinstance(layer, dict):
                raise ValidationError(f"Layer entry at index {index} must be a mapping.")

            required_keys = ["name", "s3_bucket", "s3_prefix", "file_patterns"]
            for key in required_keys:
                if not layer.get(key):
                    raise ValidationError(
                        f"Layer '{layer.get('name', f'index {index}')}' is missing required key '{key}'."
                    )

            file_patterns = layer["file_patterns"]
            if not isinstance(file_patterns, list) or not file_patterns:
                raise ValidationError(
                    f"Layer '{layer['name']}' must define a non-empty list of file_patterns."
                )

            for pattern in file_patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValidationError(
                        f"Invalid regex pattern '{pattern}' in layer '{layer['name']}': {exc}"
                    )

            min_files = layer.get("min_files", 0)
            max_files = layer.get("max_files")
            if not isinstance(min_files, int) or min_files < 0:
                raise ValidationError(
                    f"Layer '{layer['name']}' min_files must be a non-negative integer."
                )
            if max_files is not None:
                if not isinstance(max_files, int) or max_files < min_files:
                    raise ValidationError(
                        f"Layer '{layer['name']}' max_files must be >= min_files or null."
                    )

            pre_flag = layer.get("download_before_execution", False)
            if not isinstance(pre_flag, bool):
                raise ValidationError(
                    f"Layer '{layer['name']}' download_before_execution must be boolean if specified."
                )

            local_override_path = layer.get("local_override_path")
            if local_override_path is not None and not isinstance(local_override_path, str):
                raise ValidationError(
                    f"Layer '{layer['name']}' local_override_path must be a string if specified."
                )

            clear_flag = layer.get("clear_destination_before_upload", False)
            if not isinstance(clear_flag, bool):
                raise ValidationError(
                    f"Layer '{layer['name']}' clear_destination_before_upload must be boolean if specified."
                )
            if clear_flag and not local_override_path:
                raise ValidationError(
                    f"Layer '{layer['name']}' clear_destination_before_upload requires local_override_path to be set."
                )

            file_formats = layer.get("file_formats")
            if file_formats is not None:
                if not isinstance(file_formats, list) or not file_formats:
                    raise ValidationError(
                        f"Layer '{layer['name']}' file_formats must be a non-empty list of strings if specified."
                    )
                for fmt in file_formats:
                    if not isinstance(fmt, str) or not fmt.strip():
                        raise ValidationError(
                            f"Layer '{layer['name']}' file_formats entries must be non-empty strings."
                        )

            extract_zip = layer.get("extract_zip_on_download", False)
            if not isinstance(extract_zip, bool):
                raise ValidationError(
                    f"Layer '{layer['name']}' extract_zip_on_download must be boolean if specified."
                )

        return True

    def get_layers(self) -> List[LayerConfig]:
        """Return the list of configured layers as LayerConfig instances."""
        if self._layers is None:
            layers_cfg = self.config.get("layers", [])
            layer_objects: List[LayerConfig] = []
            for layer in layers_cfg:
                raw_formats = layer.get("file_formats") or []
                allowed_formats = [fmt.strip().lower().lstrip(".") for fmt in raw_formats if fmt]
                layer_objects.append(
                    LayerConfig(
                        name=layer["name"],
                        display_name=layer.get("display_name", layer["name"]),
                        s3_bucket=layer["s3_bucket"],
                        s3_prefix=layer["s3_prefix"],
                        file_patterns=layer["file_patterns"],
                        required=bool(layer.get("required", False)),
                        min_files=int(layer.get("min_files", 0)),
                        max_files=layer.get("max_files"),
                        download_before_execution=bool(
                            layer.get("download_before_execution", False)
                        ),
                        local_override_path=layer.get("local_override_path"),
                        clear_destination_before_upload=bool(
                            layer.get("clear_destination_before_upload", False)
                        ),
                        allowed_formats=allowed_formats,
                        extract_zip_on_download=bool(
                            layer.get("extract_zip_on_download", False)
                        ),
                    )
                )
            self._layers = layer_objects
            self._layer_map = {layer.name: layer for layer in layer_objects}
        return list(self._layers)

    def get_layer_by_name(self, name: str) -> Optional[LayerConfig]:
        """Return a single layer configuration by name, if present."""
        if self._layers is None:
            self.get_layers()
        if self._layer_map is None:
            return None
        return self._layer_map.get(name)

    def get_aws_config(self) -> Dict[str, str]:
        """Return the AWS configuration section."""
        aws_cfg = self.config.get("aws", {})
        region = aws_cfg.get("region")
        profile = aws_cfg.get("profile")
        result: Dict[str, str] = {"region_name": region}
        if profile:
            result["profile_name"] = profile
        return result

    def get_workflow_config(self) -> Dict[str, Any]:
        """Return workflow-related configuration values with defaults."""
        defaults = {
            "execute": True,
            "validate_before_run": True,
            "initial_layer_check_timeout": 300,
            "execution_timeout": 3600,
            "polling_interval": 30,
            "wait_for_completion": True,
        }
        workflow_cfg = self.config.get("workflow", {})
        merged = {**defaults, **workflow_cfg}
        return merged

    def get_download_config(self) -> Dict[str, Any]:
        """Return download-related configuration values with defaults."""
        defaults = {
            "local_base_dir": "./downloads",
            "preserve_structure": True,
            "overwrite": False,
            "max_workers": 5,
            "retry_count": 3,
            "retry_delay": 5,
        }
        download_cfg = self.config.get("download", {})
        merged = {**defaults, **download_cfg}
        return merged

    def get_logging_config(self) -> Dict[str, Any]:
        """Return logging configuration values with defaults."""
        defaults = {
            "level": "INFO",
            "file": None,
            "console": True,
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        }
        logging_cfg = self.config.get("logging", {})
        merged = {**defaults, **logging_cfg}
        return merged
