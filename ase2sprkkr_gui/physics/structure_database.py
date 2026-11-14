from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from importlib import resources
from pathlib import Path
import re
from typing import TextIO, Union


_RECORD_SEPARATOR = re.compile(r"^\*{10,}\s*$", re.MULTILINE)
_VARIABLE_TERM = re.compile(r"^(?P<sign>-?)(?P<name>[xyz])(?P<offset>[+-].+)?$")
_NAME_PARTS = re.compile(
    r"^(?P<type>\S+)\s+(?P<pearson>[a-z][A-Z][0-9]+)\s*(?P<description>.*)$"
)


class StructureDatabaseError(ValueError):
    """Raised when an XBand structure database record is malformed."""


@dataclass(frozen=True)
class StructureSite:
    wyckoff_letter: str
    coordinates: tuple[str, str, str]
    multiplicity: int
    point_group: str

    @property
    def coordinate_text(self) -> str:
        return ", ".join(self.coordinates)

    def position(self, *, x: float, y: float, z: float) -> tuple[float, float, float]:
        variables = {"x": x, "y": y, "z": z}
        return tuple(_evaluate_coordinate(value, variables) for value in self.coordinates)


@dataclass(frozen=True)
class StructurePrototype:
    name: str
    space_group: int
    international_symbol: str
    schoenflies_symbol: str
    perlov_space_group: int
    sites: tuple[StructureSite, ...]

    @property
    def structure_type(self) -> str:
        match = _NAME_PARTS.match(self.name)
        return match.group("type") if match else ""

    @property
    def pearson_symbol(self) -> str:
        match = _NAME_PARTS.match(self.name)
        return match.group("pearson") if match else ""

    @property
    def description(self) -> str:
        match = _NAME_PARTS.match(self.name)
        return match.group("description") if match else self.name

    @property
    def is_rhombohedral_setting(self) -> bool:
        return self.international_symbol.casefold().endswith(":r")

    @property
    def site_summary(self) -> str:
        return ", ".join(
            f"{site.wyckoff_letter} ({site.multiplicity})" for site in self.sites
        )

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.name,
                str(self.space_group),
                self.international_symbol,
                self.schoenflies_symbol,
                self.site_summary,
            )
        ).casefold()


def _evaluate_coordinate(expression: str, variables: dict[str, float]) -> float:
    try:
        return float(Fraction(expression))
    except ValueError:
        pass

    match = _VARIABLE_TERM.match(expression)
    if not match:
        raise StructureDatabaseError(f"Unsupported coordinate expression: {expression!r}")

    value = variables[match.group("name")]
    if match.group("sign"):
        value = -value
    offset = match.group("offset")
    if offset:
        value += float(Fraction(offset))
    return value


def _nonempty_lines(block: str) -> list[str]:
    return [line.strip() for line in block.splitlines() if line.strip()]


def _parse_record(block: str, record_number: int) -> StructurePrototype:
    lines = _nonempty_lines(block)
    try:
        name = lines[0]
        space_group_fields = lines[1].split(maxsplit=1)
        space_group = int(space_group_fields[0])
        international_symbol = (
            space_group_fields[1] if len(space_group_fields) > 1 else ""
        )
        schoenflies_symbol = lines[2]
        perlov_space_group = int(lines[3].split()[0])
        site_count = int(lines[4].split()[0])
    except (IndexError, ValueError) as exc:
        raise StructureDatabaseError(
            f"Invalid header in structure database record {record_number}"
        ) from exc

    if not 1 <= space_group <= 230:
        raise StructureDatabaseError(
            f"Invalid space group {space_group} in record {record_number}"
        )

    site_lines = lines[5 : 5 + site_count]
    if len(site_lines) != site_count:
        raise StructureDatabaseError(
            f"Record {record_number} declares {site_count} sites, "
            f"but contains {len(site_lines)}"
        )

    sites = []
    for site_number, line in enumerate(site_lines, start=1):
        fields = line.split()
        if len(fields) < 5:
            raise StructureDatabaseError(
                f"Invalid site {site_number} in record {record_number}: {line!r}"
            )
        try:
            multiplicity = int(fields[4])
        except ValueError as exc:
            raise StructureDatabaseError(
                f"Invalid multiplicity in record {record_number}: {line!r}"
            ) from exc
        coordinates = tuple(fields[1:4])
        for expression in coordinates:
            _evaluate_coordinate(expression, {"x": 0.17, "y": 0.29, "z": 0.41})
        sites.append(
            StructureSite(
                wyckoff_letter=fields[0],
                coordinates=coordinates,
                multiplicity=multiplicity,
                point_group=" ".join(fields[5:]),
            )
        )

    return StructurePrototype(
        name=name,
        space_group=space_group,
        international_symbol=international_symbol,
        schoenflies_symbol=schoenflies_symbol,
        perlov_space_group=perlov_space_group,
        sites=tuple(sites),
    )


def parse_structure_database(source: Union[str, Path, TextIO]) -> tuple[StructurePrototype, ...]:
    """Parse XBand's ``ITXC_structure.dat`` format."""
    if hasattr(source, "read"):
        text = source.read()
    else:
        text = Path(source).read_text(encoding="utf-8")

    blocks = _RECORD_SEPARATOR.split(text)
    records = [
        _parse_record(block, record_number)
        for record_number, block in enumerate(blocks[1:], start=1)
        if block.strip()
    ]
    if not records:
        raise StructureDatabaseError("The structure database contains no records")
    return tuple(records)


@lru_cache(maxsize=1)
def load_structure_database() -> tuple[StructurePrototype, ...]:
    """Load the structure database bundled with Ase2sprkkr."""
    database = resources.files("ase2sprkkr_gui").joinpath(
        "assets", "structures", "ITXC_structure.dat"
    )
    with database.open("r", encoding="utf-8") as stream:
        return parse_structure_database(stream)
