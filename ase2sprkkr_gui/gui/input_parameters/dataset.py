"""Model-level helpers for ``CONTROL.DATASET`` values and file naming."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import uuid4


DATASET_PATH = ("CONTROL", "DATASET")
_FILENAME_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")


def filename_component(value: str) -> str:
    """Convert a DATASET value to a safe single filename component."""
    return _FILENAME_COMPONENT.sub("_", value.strip()).strip("._")


def _structure_name(atoms: Any) -> str:
    if atoms is None:
        return "case"
    try:
        name = atoms.get_chemical_formula()
    except (AttributeError, TypeError, ValueError):
        return "case"
    return filename_component(name) or "case"


def generated_dataset(
    mode: str,
    atoms: Any = None,
    *,
    now: datetime | None = None,
    uuid_hex: str | None = None,
) -> str | None:
    """Return the configured default DATASET, or ``None`` to leave it unset."""
    if mode == "empty":
        return None
    base = _structure_name(atoms)
    if mode == "datetime":
        stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"{base}_{stamp}"
    if mode == "uuid":
        token = (uuid_hex or uuid4().hex)[:12]
        return f"{base}_{token}"
    raise ValueError(f"Unknown DATASET default mode {mode!r}.")


def apply_default_dataset(
    parameters: Any,
    mode: str,
    atoms: Any = None,
) -> None:
    """Populate an unset DATASET using the injected application preference."""
    option = parameters.CONTROL.DATASET
    if option.is_set():
        return
    value = generated_dataset(mode, atoms)
    if value is not None:
        option.set(value)


def dataset_value(parameters: Any) -> str | None:
    """Return an explicitly set DATASET without materializing its default."""
    try:
        option = parameters.CONTROL.DATASET
        if not option.is_set():
            return None
        value = option()
    except (AttributeError, TypeError):
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None
