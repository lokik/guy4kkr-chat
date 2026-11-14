from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from .models import (
    DownloadedStructure,
    SearchPage,
    StructureSearchQuery,
    StructureSummary,
)


@dataclass(frozen=True)
class ProviderCapabilities:
    formula_or_name: bool = True
    elements: bool = True
    space_group: bool = False
    max_sites: bool = True
    duplicate_filter: bool = False
    validity_filter: bool = False
    disorder_filter: bool = True


@dataclass(frozen=True)
class PropertyFilterDefinition:
    """Description and validation rules for one provider-specific filter."""

    key: str
    label: str
    property_name: str
    value_type: str
    operators: tuple[tuple[str, str], ...]
    placeholder: str = ""
    choices: tuple[tuple[str, Any], ...] = ()
    unit: str = ""


class StructureDatabaseProvider(ABC):
    id: str
    name: str
    capabilities: ProviderCapabilities
    max_page_limit: int = 100
    query_placeholder: str = "Formula or database ID"
    query_modes: tuple[str, ...] = ("auto", "id")
    property_filter_definitions: tuple[PropertyFilterDefinition, ...] = ()

    @abstractmethod
    def search(
        self,
        query: StructureSearchQuery,
        *,
        page_url: Optional[str] = None,
    ) -> SearchPage:
        """Search structures or follow a provider-issued pagination URL."""

    @abstractmethod
    def fetch(self, summary: StructureSummary) -> DownloadedStructure:
        """Download and convert one full structure."""
