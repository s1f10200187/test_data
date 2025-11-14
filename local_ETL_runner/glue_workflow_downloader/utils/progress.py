"""Progress tracking utilities."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from tqdm import tqdm as _Tqdm


class ProgressTracker:
    """Provides lightweight progress tracking with optional tqdm integration."""

    def __init__(self, description: str = "Downloading") -> None:
        self.description = description
        self.total = 0
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        self._bar: Optional["_Tqdm"] = None
        self._tqdm_factory = self._lazy_load_tqdm()

    @staticmethod
    def _lazy_load_tqdm():
        try:
            from tqdm import tqdm  # type: ignore

            return tqdm
        except ImportError:  # pragma: no cover - optional dependency
            return None

    def start(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        if self._tqdm_factory is not None:
            self._bar = self._tqdm_factory(total=total, desc=self.description, unit="file")

    def advance(self) -> None:
        self.completed += 1
        self._advance_bar()

    def skip(self) -> None:
        self.skipped += 1
        self._advance_bar()

    def fail(self) -> None:
        self.failed += 1
        self._advance_bar()

    def finish(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None

    def _advance_bar(self) -> None:
        if self._bar is not None:
            self._bar.update(1)
