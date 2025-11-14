"""Placeholder for higher-level workflow utilities."""

from __future__ import annotations

from typing import Optional

from .workflow_executor import WorkflowExecutor, WorkflowRunResult


class WorkflowManager:
    """Convenience wrapper around the workflow executor."""

    def __init__(self, executor: WorkflowExecutor) -> None:
        self.executor = executor

    def start_and_wait(
        self,
        workflow_name: str,
        *,
        timeout: int,
        polling_interval: int,
    ) -> WorkflowRunResult:
        run_id = self.executor.execute_workflow(workflow_name)
        return self.executor.wait_for_completion(
            workflow_name, run_id, timeout=timeout, polling_interval=polling_interval
        )
