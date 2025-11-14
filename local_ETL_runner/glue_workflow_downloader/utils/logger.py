"""Logging helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict


def configure_logging(config: Dict[str, Any]) -> None:
    """Configure application logging based on the supplied configuration."""
    level_name = str(config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_enabled = bool(config.get("console", True))
    file_path = config.get("file")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(log_format)

    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if file_path:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logging.captureWarnings(True)
