"""Qt-independent declarations of fields, groups and wizard pages."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Literal

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath, resolve_option


@dataclass(frozen=True)
class PresentationContext:
    """Read-only inputs available to Qt-independent presentation rules."""

    parameters: Any
    atoms: Any = None

    def value(self, section: str, option: str, *, default: Any = None) -> Any:
        """Return an option value, or ``default`` when a task lacks the option."""
        try:
            return resolve_option(self.parameters, (section, option))(all_values=True)
        except (AttributeError, KeyError):
            return default


Predicate = Callable[[PresentationContext], bool]
TextRule = Callable[[PresentationContext], str]


class FieldRole(Enum):
    """Distinguish a field's main location from a Quick setup view of that field."""
    PRIMARY = "primary"
    MIRROR = "mirror"


@dataclass(frozen=True)
class Choice:
    label: str
    value: Any


@dataclass(frozen=True)
class FieldPlacement:
    """Describe a view of an option, not an additional stored parameter value.

    ``index`` selects one array element; ``related_paths`` belong to the same
    value editor. ``editor`` names its presentation or requests ``"auto"``
    inference from the grammar type. It is unrelated to the field's page or
    group. Defaults come exclusively
    from InputParameters and are shown as placeholders, not duplicated here.
    """
    path: InputParameterPath
    label: str
    editor: str = "auto"
    role: FieldRole = FieldRole.PRIMARY
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    decimals: int = 6
    choices: tuple[Choice, ...] = ()
    special_value_text: str | None = None
    nullable: bool = False
    index: int | None = None
    descriptions: bool = False
    related_paths: tuple[InputParameterPath, ...] = ()
    visible_when: Predicate | None = None
    enabled_when: Predicate | None = None
    label_when: TextRule | None = None
    tooltip_when: TextRule | None = None
    disabled_reason_when: TextRule | None = None
    required_when: Predicate | None = None
    required_message: str | TextRule | None = None

    @property
    def paths(self):
        return (self.path,) + self.related_paths


@dataclass(frozen=True)
class GroupSpec:
    """A group and its optional parameter-driven presentation rules."""
    title: str
    fields: tuple[FieldPlacement, ...]
    collapsed: bool = False
    note: str | None = None
    id: str | None = None
    layout: Literal["form", "paired"] = "form"
    visible_when: Predicate | None = None
    title_when: TextRule | None = None
    note_when: TextRule | None = None


@dataclass(frozen=True)
class PageSpec:
    id: str
    title: str
    groups: tuple[GroupSpec, ...]
    color: str
    quick: bool = False


@dataclass(frozen=True)
class TaskDialogSpec:
    """Declarative layout and presentation metadata for one Guided dialog."""

    title: str
    pages: tuple[PageSpec, ...]
    intro: str | None = None

    def primary_pages(self) -> dict[InputParameterPath, str]:
        """Map paths to their owning page, validating primary/mirror placements.

        Different array indices may share a page. Quick setup mirrors must have
        a primary placement; related paths also belong to their composite field.
        """
        result: dict[InputParameterPath, str] = {}
        mirrors: set[InputParameterPath] = set()
        placements: set[tuple[InputParameterPath, int | None]] = set()
        for page in self.pages:
            for group in page.groups:
                for field in group.fields:
                    if field.role is FieldRole.MIRROR:
                        if not page.quick:
                            raise ValueError(
                                f"Mirror {'.'.join(field.path)} is only allowed on Quick setup."
                            )
                        mirrors.add(field.path)
                    elif ((field.path, field.index) in placements
                          or (field.path in result and result[field.path] != page.id)):
                        raise ValueError(f"Duplicate primary field {'.'.join(field.path)}")
                    else:
                        for path in field.paths:
                            if path in result and path != field.path:
                                raise ValueError(f"Duplicate primary field {'.'.join(path)}")
                            result[path] = page.id
                            placements.add((path, field.index))
        missing = mirrors - result.keys()
        if missing:
            names = ", ".join(".".join(path) for path in sorted(missing))
            raise ValueError(f"Mirrored fields have no primary placement: {names}")
        return result

    def all_paths(self) -> tuple[InputParameterPath, ...]:
        return tuple(dict.fromkeys(
            path
            for page in self.pages
            for group in page.groups
            for field in group.fields
            for path in field.paths
        ))


def field(section: str, option: str, label: str, editor: str = "auto", **kwargs: Any) -> FieldPlacement:
    """Declare one view of an input-parameter option."""
    return FieldPlacement((section, option), label, editor, **kwargs)


def main_energy_mesh_field(option: str, label: str, editor: str = "auto", **kwargs: Any) -> FieldPlacement:
    """Declare the main (index-zero) component of ``ENERGY.GRID`` or ``NE``."""
    if option not in {"GRID", "NE"}:
        raise ValueError(f"{option} is not an energy-mesh option")
    return field("ENERGY", option, label, editor, index=0, **kwargs)


def mirror(value: FieldPlacement) -> FieldPlacement:
    return replace(value, role=FieldRole.MIRROR)


def energy_bound(name: str, label: str) -> FieldPlacement:
    return field(
        "ENERGY",
        name,
        label,
        editor="energy_bound",
        related_paths=(("ENERGY", name + "EV"),),
    )
