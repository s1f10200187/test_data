"""Additional validation helpers for configuration structures."""

from __future__ import annotations

from typing import Any, Dict

from .config_manager import ConfigManager


def ensure_layer_exists(config: ConfigManager, layer_name: str) -> bool:
    """Return True if a layer with the provided name exists."""
    for layer in config.get_layers():
        if layer.name == layer_name:
            return True
    return False
