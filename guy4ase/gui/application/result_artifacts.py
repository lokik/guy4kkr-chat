"""Resolve historical result-file artifacts against the current filesystem."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ase2sprkkr.execution import FileState
from guy4ase.gui.application.result_store import ResultRecord, ResultStore


@dataclass(frozen=True)
class ResolvedResultValue:
    """Filesystem-resolved value used to build result presentation data."""

    value: Any
    warning: str | None = None
    disable_actions: bool = False
    replaced: bool = False
    unavailable: bool = False


def resolve_result_value(
    store: ResultStore | None,
    record: ResultRecord | None,
    key: str,
    value: Any,
) -> ResolvedResultValue:
    """Resolve one captured output value without involving a Qt view."""
    result_file = record.result_files.get(key) if record is not None else None
    if result_file is None:
        return ResolvedResultValue(value)

    state = result_file.state()
    if state is FileState.OVERWRITTEN:
        current_value = (
            store.current_value_for_result_file(result_file)
            if store is not None
            else None
        )
        return ResolvedResultValue(
            current_value if current_value is not None else value,
            warning=(
                "The historical result file was overwritten. Showing the current "
                f"contents of {result_file.path.name}; these are not the original "
                "data from the selected calculation."
            ),
            replaced=True,
        )
    if state is FileState.MISSING:
        return ResolvedResultValue(
            value,
            warning=(
                "The historical result file no longer exists, so its original "
                "contents are unavailable."
            ),
            disable_actions=True,
            unavailable=True,
        )
    if state is FileState.UNAVAILABLE:
        return ResolvedResultValue(
            value,
            warning=(
                "The historical result file cannot currently be inspected, so "
                "its contents are unavailable."
            ),
            disable_actions=True,
            unavailable=True,
        )
    return ResolvedResultValue(value)
