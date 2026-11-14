"""Tooltips shared by the guided SPR-KKR parameter editors."""
from __future__ import annotations

import re
import textwrap
from typing import Any


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _wrap_help(text: str, width: int = 88) -> str:
    """Wrap prose while preserving blank lines and indented help tables."""
    lines = []
    for line in text.strip().splitlines():
        if not line or line[:1].isspace() or len(line) <= width:
            lines.append(line.rstrip())
            continue
        lines.extend(textwrap.wrap(line, width=width))
    return "\n".join(lines).strip()


def _meaningful_help(option: Any, label: str) -> str:
    """Return the text printed by ``Option.help()``, if it adds useful detail."""
    definition = option._definition
    explicit_info = (definition.info(False) or "").strip()
    detailed_description = getattr(definition, "_description", None)
    type_description = (
        definition.additional_data_description() or ""
    ).strip()

    if (
        not detailed_description
        and not type_description
        and (
            not explicit_info
            or _normalized(explicit_info) == _normalized(label)
        )
    ):
        return ""

    try:
        return _wrap_help(option.doc)
    except Exception:
        return _wrap_help(explicit_info)


def parameter_tooltip(
    option: Any,
    section: str,
    name: str,
    label: str,
) -> str:
    """Build a tooltip containing the input-file name and useful documentation."""
    tooltip = f"SPR-KKR parameter: {section}.{name}"
    help_text = _meaningful_help(option, label.rstrip(":"))
    if help_text:
        tooltip += f"\n\n{help_text}"
    return tooltip
