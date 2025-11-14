"""File name matching helpers."""

from __future__ import annotations

import re
from typing import Dict, List, Optional


class FileMatcher:
    """Provides cached regular-expression based matching utilities."""

    def __init__(self) -> None:
        self._pattern_cache: Dict[str, re.Pattern[str]] = {}

    def matches(self, filename: str, pattern: str) -> bool:
        """Return True if the filename matches the supplied pattern."""
        compiled = self._get_compiled_pattern(pattern)
        return bool(compiled.match(filename))

    def matches_any(self, filename: str, patterns: List[str]) -> bool:
        """Return True if the filename matches any pattern in the list."""
        return self.get_matched_pattern(filename, patterns) is not None

    def get_matched_pattern(self, filename: str, patterns: List[str]) -> Optional[str]:
        """Return the pattern that matches the filename, if any."""
        for pattern in patterns:
            if self.matches(filename, pattern):
                return pattern
        return None

    def filter_files(self, files: List[str], pattern: str) -> List[str]:
        """Filter file names to those matching the pattern."""
        compiled = self._get_compiled_pattern(pattern)
        return [name for name in files if compiled.match(name)]

    def filter_files_multi_pattern(self, files: List[str], patterns: List[str]) -> Dict[str, List[str]]:
        """Return a mapping of pattern to file names matching that pattern."""
        result: Dict[str, List[str]] = {pattern: [] for pattern in patterns}
        for name in files:
            matched = self.get_matched_pattern(name, patterns)
            if matched is not None:
                result.setdefault(matched, []).append(name)
        return result

    def _get_compiled_pattern(self, pattern: str) -> re.Pattern[str]:
        """Fetch or compile the regex pattern."""
        compiled = self._pattern_cache.get(pattern)
        if compiled is None:
            compiled = re.compile(pattern)
            self._pattern_cache[pattern] = compiled
        return compiled
