"""Command line entry point for the Glue Workflow Downloader."""

from __future__ import annotations

import logging
from typing import Optional

import click

from .exceptions import GlueWorkflowDownloaderError
from .main import GlueWorkflowDownloader
from .utils import configure_logging

LOGGER = logging.getLogger(__name__)


@click.command()
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True), help="Path to the YAML configuration file.")
@click.option("--workflow", "workflow_name", required=True, help="Glue workflow name to execute.")
@click.option("--output", "output_dir", type=click.Path(), help="Override the download output directory.")
@click.option("--no-execute", "execute", flag_value=False, default=None, help="Do not trigger the workflow run.")
@click.option("--execution-timeout", type=int, help="Workflow execution timeout in seconds.")
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False), help="Override logging level.")
@click.option("--max-workers", type=int, help="Number of parallel download workers.")
@click.option("--overwrite", is_flag=True, default=None, help="Overwrite existing files.")
@click.option("--dry-run", is_flag=True, help="Preview the run without downloading or executing the workflow.")
@click.option("--skip-validation", is_flag=True, help="Skip workflow validation steps.")
@click.option("--wait", "wait_for_completion", flag_value=True, default=None, help="Wait for workflow completion (default from config).")
@click.option("--polling-interval", type=int, help="Polling interval for workflow status checks.")
@click.version_option(version="1.0.0")
def main(
    config_path: str,
    workflow_name: str,
    output_dir: Optional[str],
    execute: Optional[bool],
    execution_timeout: Optional[int],
    log_level: Optional[str],
    max_workers: Optional[int],
    overwrite: Optional[bool],
    dry_run: bool,
    skip_validation: bool,
    wait_for_completion: Optional[bool],
    polling_interval: Optional[int],
) -> None:
    """Application entry point invoked from the command line."""
    downloader = GlueWorkflowDownloader(config_path)

    config_dict = downloader.config.config

    if output_dir is not None:
        config_dict.setdefault("download", {})["local_base_dir"] = output_dir
    if max_workers is not None:
        config_dict.setdefault("download", {})["max_workers"] = max_workers
    if overwrite is not None:
        config_dict.setdefault("download", {})["overwrite"] = overwrite
    if log_level is not None:
        config_dict.setdefault("logging", {})["level"] = log_level.upper()
        configure_logging(downloader.config.get_logging_config())

    try:
        downloader.run(
            workflow_name,
            execute=execute,
            wait_for_completion=wait_for_completion,
            dry_run=dry_run,
            skip_validation=skip_validation,
            execution_timeout=execution_timeout,
            polling_interval=polling_interval,
        )
    except GlueWorkflowDownloaderError as exc:
        LOGGER.error("Execution failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
