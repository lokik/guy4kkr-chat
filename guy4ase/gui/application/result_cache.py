"""Bounded GUI-thread cache for parsed historical calculation results."""
from __future__ import annotations

import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


def _estimate_size(value: Any, limit: int) -> int:
    """Estimate retained Python/NumPy memory without invoking result properties.

    This is deliberately conservative: very large object graphs are not cached.
    NumPy views account for their referenced array data, not only their header.
    """
    seen: set[int] = set()
    pending = [value]
    total = 0
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if len(seen) > 25000:
            return limit + 1
        total += sys.getsizeof(current, 0)
        if type(current).__module__.startswith("numpy."):
            total = max(total, total - sys.getsizeof(current, 0) + max(
                sys.getsizeof(current, 0), int(getattr(current, "nbytes", 0))
            ))
        if total > limit:
            return total
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple, set, frozenset)):
            pending.extend(current)
        elif hasattr(current, "__dict__"):
            pending.append(vars(current))
        # Do not access arbitrary properties: many result properties parse files.
    return total


@dataclass(frozen=True)
class _Entry:
    version: tuple[Any, ...]
    value: Any
    size: int
    timestamp: float


class ResultLRU:
    """Cache only completed parsed results, bounded by count, bytes, and age."""

    def __init__(
        self,
        *,
        max_entries: int = 1024,
        max_bytes: int = 512 * 1024 * 1024,
        max_age_seconds: float = 600,
    ) -> None:
        if max_entries < 1 or max_bytes < 1 or max_age_seconds <= 0:
            raise ValueError("Cache limits must be positive")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.max_age_seconds = max_age_seconds
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._bytes = 0

    def invalidate(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= entry.size

    def clear(self) -> None:
        self._entries.clear()
        self._bytes = 0

    def lookup(self, key: str, version: tuple[Any, ...]) -> tuple[bool, Any]:
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        if entry.version != version or time.monotonic() - entry.timestamp > self.max_age_seconds:
            self.invalidate(key)
            return False, None
        self._entries.move_to_end(key)
        return True, entry.value

    def store(self, key: str, version: tuple[Any, ...], result: Any) -> bool:
        size = _estimate_size(result, self.max_bytes)
        self.invalidate(key)
        if size > self.max_bytes:
            return False
        self._entries[key] = _Entry(version, result, size, time.monotonic())
        self._bytes += size
        while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
            _, evicted = self._entries.popitem(last=False)
            self._bytes -= evicted.size
        return True
