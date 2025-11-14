"""Workflow execution utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from ..exceptions import (
    WorkflowExecutionError,
    WorkflowFailedError,
    WorkflowTimeoutError,
)


@dataclass
class WorkflowRunResult:
    """Container for workflow run information."""

    run_id: str
    workflow_name: str
    status: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    completed_jobs: int
    failed_jobs: int
    total_jobs: int
    job_details: List[Dict[str, Any]]
    error_message: Optional[str] = None

    def is_successful(self) -> bool:
        return self.status == "COMPLETED" and self.failed_jobs == 0

    def get_success_rate(self) -> float:
        if self.total_jobs == 0:
            return 0.0
        return (self.completed_jobs / self.total_jobs) * 100


class WorkflowExecutor:
    """Controls the execution and monitoring of Glue workflows."""

    TERMINAL_STATUSES = {"COMPLETED", "FAILED", "STOPPED", "ERROR"}

    def __init__(self, glue_client, config):
        self.glue_client = glue_client
        self.config = config

    def execute_workflow(self, workflow_name: str) -> str:
        """Trigger a workflow run and return the run identifier."""
        try:
            response = self.glue_client.start_workflow_run(Name=workflow_name)
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise WorkflowExecutionError(f"Unable to start workflow '{workflow_name}': {exc}") from exc

        run_id = response.get("RunId")
        if not run_id:
            raise WorkflowExecutionError("Workflow run did not return a RunId.")
        return run_id

    def wait_for_completion(
        self,
        workflow_name: str,
        run_id: str,
        timeout: int = 3600,
        polling_interval: int = 30,
    ) -> WorkflowRunResult:
        """Wait for a workflow run to finish, returning the run result."""
        status = self._poll_workflow_status(workflow_name, run_id, timeout, polling_interval)
        run_status = self.get_workflow_run_status(workflow_name, run_id)
        job_details = self.get_job_run_details(workflow_name, run_id)

        result = WorkflowRunResult(
            run_id=run_id,
            workflow_name=workflow_name,
            status=status,
            start_time=run_status["start_time"],
            end_time=run_status["end_time"],
            duration_seconds=self._calculate_duration(run_status["start_time"], run_status["end_time"]),
            completed_jobs=run_status["completed_jobs"],
            failed_jobs=run_status["failed_jobs"],
            total_jobs=run_status["total_jobs"],
            job_details=job_details,
            error_message=run_status.get("error_message"),
        )

        if not result.is_successful():
            raise WorkflowFailedError(
                f"Workflow '{workflow_name}' failed with status {result.status} "
                f"and {result.failed_jobs} failed jobs."
            )

        return result

    def get_workflow_run_status(self, workflow_name: str, run_id: str) -> Dict[str, Any]:
        """Return status metadata for the specified run."""
        try:
            response = self.glue_client.get_workflow_run(
                Name=workflow_name, RunId=run_id, IncludeGraph=False
            )
        except ClientError as exc:  # pragma: no cover - depends on AWS
            raise WorkflowExecutionError(f"Unable to fetch workflow run status: {exc}") from exc

        run = response.get("Run", {})
        statistics = run.get("Statistics", {})
        start_time = self._ensure_datetime(run.get("StartedOn"))
        end_time = self._ensure_datetime(run.get("CompletedOn"))
        total_jobs = statistics.get("TotalActions")
        completed = statistics.get("SucceededActions")
        failed = statistics.get("FailedActions")

        return {
            "status": run.get("Status", "UNKNOWN"),
            "start_time": start_time,
            "end_time": end_time,
            "total_jobs": total_jobs or 0,
            "completed_jobs": completed or 0,
            "failed_jobs": failed or 0,
            "running_jobs": statistics.get("RunningActions", 0),
            "error_message": run.get("ErrorMessage"),
        }

    def get_job_run_details(self, workflow_name: str, run_id: str) -> List[Dict[str, Any]]:
        """Return per-job run details if available."""
        try:
            response = self.glue_client.get_workflow_run(
                Name=workflow_name, RunId=run_id, IncludeGraph=True
            )
        except ClientError:
            return []  # pragma: no cover - degraded mode

        run = response.get("Run", {})
        graph = run.get("Graph", {})
        nodes = graph.get("Nodes", [])
        details: List[Dict[str, Any]] = []

        for node in nodes:
            node_name = node.get("Name") or node.get("Node", {}).get("Name")
            run_details = node.get("RunDetails", {})
            entry: Dict[str, Any] = {
                "name": node_name,
                "type": node.get("NodeType"),
                "run_state": run_details.get("State") or run_details.get("Status"),
                "attempt": run_details.get("Attempt") or run_details.get("AttemptNumber"),
                "error_message": run_details.get("Error")
                or run_details.get("ErrorMessage")
                or run_details.get("AttemptFailureMessage"),
            }
            start_time = self._ensure_datetime(run_details.get("StartedOn"))
            end_time = self._ensure_datetime(run_details.get("CompletedOn"))
            if start_time:
                entry["started_on"] = start_time
            if end_time:
                entry["completed_on"] = end_time
            if start_time and end_time:
                entry["duration_seconds"] = (end_time - start_time).total_seconds()
            cleaned = {key: value for key, value in entry.items() if value is not None}
            if cleaned:
                details.append(cleaned)

        return details

    def _poll_workflow_status(
        self,
        workflow_name: str,
        run_id: str,
        timeout: int,
        polling_interval: int,
    ) -> str:
        """Poll workflow status until a terminal state is reached or timeout."""
        deadline = time.time() + max(timeout, 0)
        while time.time() <= deadline:
            status_info = self.get_workflow_run_status(workflow_name, run_id)
            status = status_info["status"]
            if status in self.TERMINAL_STATUSES:
                return status
            time.sleep(max(polling_interval, 1))

        raise WorkflowTimeoutError(
            f"Workflow '{workflow_name}' run '{run_id}' did not complete within {timeout} seconds."
        )

    @staticmethod
    def _ensure_datetime(value: Optional[Any]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return None

    @staticmethod
    def _calculate_duration(
        start_time: Optional[datetime], end_time: Optional[datetime]
    ) -> Optional[float]:
        if not start_time or not end_time:
            return None
        return max((end_time - start_time).total_seconds(), 0.0)
