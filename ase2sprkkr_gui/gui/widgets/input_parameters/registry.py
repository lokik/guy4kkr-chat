"""Single registry and grammar-default dispatch for parameter value editors."""
from __future__ import annotations

from typing import Any

from ase2sprkkr.common.grammar_types import (
    Boolean,
    Energy,
    Flag,
    Integer,
    Keyword,
    Real,
    String,
)

from .bsf import BsfKPathEditor, BsfMeshEditor, BsfVectorsEditor
from .common import (
    BoundEnergyParameterEditor,
    EnergyParameterEditor,
    RelativisticScalingParameterEditor,
)
from .kpath import VectorEditor
from .scalar import (
    BooleanEditor,
    ChoiceEditor,
    IntegerEditor,
    KeywordEditor,
    LiteralEditor,
    RealEditor,
    TextEditor,
)
from .value_editor import ParameterValueEditor


EDITORS: dict[str, type[ParameterValueEditor]] = {
    "integer": IntegerEditor,
    "real": RealEditor,
    "boolean": BooleanEditor,
    "keyword": KeywordEditor,
    "choice": ChoiceEditor,
    "text": TextEditor,
    "literal": LiteralEditor,
    "energy": EnergyParameterEditor,
    "vector": VectorEditor,
    "energy_bound": BoundEnergyParameterEditor,
    "scaling": RelativisticScalingParameterEditor,
    "bsf_mesh": BsfMeshEditor,
    "bsf_kpath": BsfKPathEditor,
    "bsf_vectors": BsfVectorsEditor,
}


DEFAULT_EDITORS = {
    Energy: "energy",
    Integer: "integer",
    Real: "real",
    Boolean: "boolean",
    Flag: "boolean",
    Keyword: "keyword",
    String: "text",
}


def editor_for_type(grammar_type: Any) -> str:
    """Return the nearest registered grammar default using its class MRO."""
    for grammar_class in type(grammar_type).__mro__:
        editor = DEFAULT_EDITORS.get(grammar_class)
        if editor is not None:
            return editor
    return "text"


def create_editor(binding, placement, *, atoms=None, parent=None) -> ParameterValueEditor:
    """Resolve one editor name and instantiate it through the common contract."""
    name = (
        editor_for_type(binding.value_type)
        if placement.editor == "auto"
        else placement.editor
    )
    try:
        editor_class = EDITORS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown input editor {name!r}") from exc
    editor = editor_class.from_binding(
        binding,
        placement,
        atoms=atoms,
        parent=parent,
    )
    if not isinstance(editor, ParameterValueEditor):
        raise TypeError(f"Editor {name!r} must implement ParameterValueEditor")
    return editor
