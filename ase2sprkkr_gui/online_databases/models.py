from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass(frozen=True)
class PropertyFilter:
    """One validated provider-specific OPTIMADE property condition."""

    key: str
    operator: str
    value: Any


@dataclass(frozen=True)
class StructureSearchQuery:
    text: str = ""
    query_mode: str = "auto"
    elements: tuple[str, ...] = ()
    element_match: str = "only"
    excluded_elements: tuple[str, ...] = ()
    min_elements: Optional[int] = None
    max_elements: Optional[int] = None
    space_group: Optional[int] = None
    min_sites: Optional[int] = None
    max_sites: Optional[int] = None
    dimensionality: Optional[int] = None
    structure_order: str = "any"
    modified_after: Optional[date] = None
    modified_before: Optional[date] = None
    hide_duplicates: bool = True
    hide_invalid: bool = True
    property_filters: tuple[PropertyFilter, ...] = ()
    page_limit: int = 50

    def __post_init__(self) -> None:
        if self.query_mode not in {
            "auto",
            "id",
            "name",
            "reduced",
            "hill",
            "anonymous",
            "descriptive",
        }:
            raise ValueError(f"Unknown query mode {self.query_mode!r}.")
        if self.element_match not in {"all", "any", "only"}:
            raise ValueError(
                f"Unknown element matching mode {self.element_match!r}."
            )
        if self.structure_order not in {"any", "ordered", "disordered"}:
            raise ValueError(
                f"Unknown structure ordering mode {self.structure_order!r}."
            )
        self._validate_range(
            "number of elements", self.min_elements, self.max_elements
        )
        self._validate_range("number of sites", self.min_sites, self.max_sites)
        if self.dimensionality is not None and not 0 <= self.dimensionality <= 3:
            raise ValueError("Dimensionality must be between 0 and 3.")
        for label, value in (
            ("earliest", self.modified_after),
            ("latest", self.modified_before),
        ):
            if value is not None and not isinstance(value, date):
                raise ValueError(
                    f"The {label} modification date must be a date."
                )
        if (
            self.modified_after is not None
            and self.modified_before is not None
            and self.modified_after > self.modified_before
        ):
            raise ValueError(
                "The earliest modification date must not be after the latest."
            )
        if set(self.elements).intersection(self.excluded_elements):
            raise ValueError(
                "Required and excluded elements must not overlap."
            )
        if self.element_match == "only" and self.elements:
            count = len(set(self.elements))
            if self.min_elements is not None and self.min_elements > count:
                raise ValueError(
                    "The minimum element count conflicts with “Only these "
                    "elements”."
                )
            if self.max_elements is not None and self.max_elements < count:
                raise ValueError(
                    "The maximum element count conflicts with “Only these "
                    "elements”."
                )

    @staticmethod
    def _validate_range(
        label: str, minimum: Optional[int], maximum: Optional[int]
    ) -> None:
        if minimum is not None and minimum < 0:
            raise ValueError(f"The minimum {label} must not be negative.")
        if maximum is not None and maximum < 0:
            raise ValueError(f"The maximum {label} must not be negative.")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(
                f"The minimum {label} must not exceed the maximum."
            )


@dataclass(frozen=True)
class StructureSummary:
    provider_id: str
    entry_id: str
    formula: str
    name: str = ""
    space_group: str = ""
    space_group_number: Optional[int] = None
    site_count: Optional[int] = None
    method: str = ""
    year: Optional[int] = None
    status: str = ""
    duplicate_of: Optional[str] = None
    optimal_entry: Optional[str] = None
    structure_features: tuple[str, ...] = ()
    doi: str = ""
    raw_attributes: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def is_disordered(self) -> bool:
        return "disorder" in self.structure_features

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings = []
        if self.is_disordered:
            warnings.append("Disordered structure")
        if self.duplicate_of:
            warnings.append(f"Duplicate of {self.duplicate_of}")
        if self.optimal_entry and self.optimal_entry != self.entry_id:
            warnings.append(f"Recommended COD entry: {self.optimal_entry}")
        if self.status:
            warnings.append(f"COD status: {self.status}")
        return tuple(warnings)


@dataclass(frozen=True)
class SearchPage:
    results: tuple[StructureSummary, ...]
    next_url: Optional[str] = None
    previous_url: Optional[str] = None
    total: Optional[int] = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructureProvenance:
    provider_id: str
    provider_name: str
    entry_id: str
    entry_url: str
    retrieved_at: str
    license_name: str
    license_url: str
    experimental: Optional[bool]
    doi: str = ""
    method: str = ""
    temperature_kelvin: Optional[float] = None
    pressure_kpa: Optional[float] = None
    warnings: tuple[str, ...] = ()
    provider_metadata: dict[str, Any] = field(
        default_factory=dict, compare=False
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "entry_id": self.entry_id,
            "entry_url": self.entry_url,
            "retrieved_at": self.retrieved_at,
            "license": self.license_name,
            "license_url": self.license_url,
            "experimental": self.experimental,
            "doi": self.doi,
            "method": self.method,
            "temperature_kelvin": self.temperature_kelvin,
            "pressure_kpa": self.pressure_kpa,
            "warnings": list(self.warnings),
            "provider_metadata": dict(self.provider_metadata),
        }


@dataclass(frozen=True)
class DownloadedStructure:
    atoms: Any
    summary: StructureSummary
    provenance: StructureProvenance
    warnings: tuple[str, ...] = ()
