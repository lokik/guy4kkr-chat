"""Input-parameter paths and shared value helpers."""
from __future__ import annotations

from typing import Any

from ase2sprkkr import InputParameters
from ase2sprkkr.common.misc import values_equal as values_equal

InputParameterPath = tuple[str, ...]


def resolve_option(parameters: InputParameters, path: InputParameterPath) -> Any:
    """Resolve an option without relying on ase2sprkkr's ambiguous name search."""
    value: Any = parameters
    for name in path:
        # Conditional BSF members still need editors while inactive. Attribute
        # access rejects them; explicit item access intentionally permits it.
        value = value[name]
    return value
