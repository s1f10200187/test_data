"""Custom exception definitions for the Glue Workflow Downloader."""


class GlueWorkflowDownloaderError(Exception):
    """Base exception for the package."""


class ConfigurationError(GlueWorkflowDownloaderError):
    """Raised when configuration loading or validation fails."""


class ValidationError(GlueWorkflowDownloaderError):
    """Raised when input validation fails."""


class WorkflowNotFoundError(GlueWorkflowDownloaderError):
    """Raised when the specified Glue Workflow cannot be found."""


class InitialLayerFileNotFoundError(GlueWorkflowDownloaderError):
    """Raised when no files can be found for a required initial layer."""


class InsufficientFilesError(GlueWorkflowDownloaderError):
    """Raised when the number of files does not meet the minimum requirement."""


class TooManyFilesError(GlueWorkflowDownloaderError):
    """Raised when the number of files exceeds the configured maximum."""


class WorkflowExecutionError(GlueWorkflowDownloaderError):
    """Raised when a workflow cannot be started."""


class WorkflowTimeoutError(GlueWorkflowDownloaderError):
    """Raised when a workflow run does not finish within the timeout."""


class WorkflowFailedError(GlueWorkflowDownloaderError):
    """Raised when a workflow run finishes with a failed status."""


class DownloadError(GlueWorkflowDownloaderError):
    """Raised when downloading files fails."""


class S3AccessError(GlueWorkflowDownloaderError):
    """Raised when accessing S3 resources fails."""


class LocalOverrideError(GlueWorkflowDownloaderError):
    """Raised when processing local overrides fails."""
