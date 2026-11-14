from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)
from urllib.request import Request, urlopen

import numpy as np
from ase import Atoms
from ase.data import atomic_numbers
from ase.formula import Formula

from .models import (
    DownloadedStructure,
    SearchPage,
    StructureProvenance,
    StructureSearchQuery,
    StructureSummary,
)
from .provider import (
    PropertyFilterDefinition,
    ProviderCapabilities,
    StructureDatabaseProvider,
)


class OnlineDatabaseError(RuntimeError):
    """A user-facing online database or response error."""


class InvalidProviderRecordError(OnlineDatabaseError):
    """A provider could not serialize one or more matching records."""


JsonTransport = Callable[[str], dict[str, Any]]

_EQUALITY_OPERATOR = (("=", "is"),)
_NUMBER_OPERATORS = (
    ("=", "equals"),
    (">=", "at least"),
    ("<=", "at most"),
)
_TEXT_OPERATORS = (
    ("=", "is"),
    ("CONTAINS", "contains"),
)
_LIST_TEXT_OPERATORS = (
    ("HAS", "contains"),
    ("HAS ANY", "contains any"),
)


def _default_json_transport(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.api+json, application/json",
            "User-Agent": "Ase2sprkkr/0.1",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.reason or f"HTTP {exc.code}"
        code = ""
        source = ""
        try:
            payload = json.load(exc)
            error = payload.get("errors", [{}])[0]
            detail = error.get("detail", detail)
            code = str(error.get("code", ""))
            source = str((error.get("source") or {}).get("pointer", ""))
        except Exception:
            pass
        if (
            exc.code >= 500
            and code in {"string_pattern_mismatch", "value_error"}
            and source.startswith("/attributes/species/")
        ):
            field = source[len("/attributes/"):].replace("/", " / ")
            raise InvalidProviderRecordError(
                "The database contains an invalid structure record "
                f"({field})."
            ) from exc
        raise OnlineDatabaseError(f"Database request failed: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise OnlineDatabaseError(f"Cannot reach the online database: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise OnlineDatabaseError("The database returned invalid JSON data.") from exc


def _escape_filter_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _as_optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class OptimadeProvider(StructureDatabaseProvider):
    """Shared implementation of standard OPTIMADE search and conversion."""

    id = "optimade"
    name = "OPTIMADE"
    base_url = ""
    homepage = ""
    capabilities = ProviderCapabilities()
    license_name = ""
    license_url = ""
    experimental: Optional[bool] = None
    default_doi = ""
    default_method = ""
    query_placeholder = "Formula or database ID"
    query_modes = (
        "auto",
        "id",
        "name",
        "reduced",
        "hill",
        "anonymous",
        "descriptive",
    )
    _id_pattern: Optional[str] = None
    _name_fields: tuple[str, ...] = ()
    _space_group_field: Optional[str] = None
    _space_group_number_field: Optional[str] = None
    _method_field: Optional[str] = None
    _year_field: Optional[str] = None
    _status_field: Optional[str] = None
    _duplicate_field: Optional[str] = None
    _optimal_field: Optional[str] = None
    _doi_field: Optional[str] = None
    _temperature_field: Optional[str] = None
    _pressure_field: Optional[str] = None
    _entry_page_field: Optional[str] = None
    _validity_filter: Optional[str] = None
    _summary_fields = (
        "chemical_formula_reduced",
        "chemical_formula_descriptive",
        "nsites",
        "structure_features",
    )
    _structure_fields = (
        "lattice_vectors",
        "cartesian_site_positions",
        "dimension_types",
        "species_at_sites",
        "species",
        "assemblies",
    )

    def __init__(self, transport: Optional[JsonTransport] = None):
        self._transport = transport or _default_json_transport

    def search(
        self,
        query: StructureSearchQuery,
        *,
        page_url: Optional[str] = None,
    ) -> SearchPage:
        url = page_url or self._search_url(query)
        payload = self._transport(url)
        return self._parse_page(payload, request_url=url)

    def fetch(self, summary: StructureSummary) -> DownloadedStructure:
        entry_id = quote(summary.entry_id, safe="")
        parameters = {
            "response_fields": ",".join(
                self._summary_fields + self._structure_fields
            )
        }
        url = (
            urljoin(self.base_url, f"structures/{entry_id}")
            + "?"
            + urlencode(parameters)
        )
        payload = self._transport(url)
        resource = payload.get("data")
        if not isinstance(resource, dict):
            raise OnlineDatabaseError("The database response contains no structure.")
        return self._downloaded_structure(resource, fallback_summary=summary)

    def _search_url(self, query: StructureSearchQuery) -> str:
        parameters = {
            "page_limit": max(
                1, min(int(query.page_limit), self.max_page_limit)
            ),
            "response_fields": ",".join(self._summary_fields),
        }
        filters = self._filters(query)
        if filters:
            parameters["filter"] = " AND ".join(f"({item})" for item in filters)
        return urljoin(self.base_url, "structures") + "?" + urlencode(parameters)

    def _filters(self, query: StructureSearchQuery) -> list[str]:
        filters = []
        text = query.text.strip()
        if text:
            filters.append(self._text_filter(text, query.query_mode))

        elements = tuple(dict.fromkeys(query.elements))
        if elements:
            quoted = ", ".join(f'"{_escape_filter_string(item)}"' for item in elements)
            operator = (
                "HAS ANY" if query.element_match == "any" else "HAS ALL"
            )
            filters.append(f"elements {operator} {quoted}")
            if query.element_match == "only":
                filters.append(f"nelements={len(elements)}")
        excluded_elements = tuple(dict.fromkeys(query.excluded_elements))
        if excluded_elements:
            quoted = ", ".join(
                f'"{_escape_filter_string(item)}"'
                for item in excluded_elements
            )
            filters.append(f"NOT elements HAS ANY {quoted}")

        if query.min_elements is not None:
            filters.append(f"nelements>={int(query.min_elements)}")
        if query.max_elements is not None:
            filters.append(f"nelements<={int(query.max_elements)}")

        if (
            query.space_group is not None
            and self.capabilities.space_group
            and self._space_group_number_field
        ):
            filters.append(
                f"{self._space_group_number_field}={int(query.space_group)}"
            )
        if query.min_sites is not None and self.capabilities.max_sites:
            filters.append(f"nsites>={int(query.min_sites)}")
        if query.max_sites is not None and self.capabilities.max_sites:
            filters.append(f"nsites<={int(query.max_sites)}")
        if (
            query.hide_duplicates
            and self.capabilities.duplicate_filter
            and self._duplicate_field
        ):
            filters.append(f"{self._duplicate_field} IS UNKNOWN")
        if (
            query.hide_invalid
            and self.capabilities.validity_filter
            and self._validity_filter
        ):
            filters.append(self._validity_filter)
        if (
            query.structure_order == "ordered"
            and self.capabilities.disorder_filter
        ):
            filters.append('NOT structure_features HAS "disorder"')
        elif (
            query.structure_order == "disordered"
            and self.capabilities.disorder_filter
        ):
            filters.append('structure_features HAS "disorder"')
        if self.capabilities.disorder_filter:
            filters.extend(
                (
                    'NOT structure_features HAS "implicit_atoms"',
                    'NOT structure_features HAS "site_attachments"',
                )
            )
        if query.dimensionality is not None:
            filters.append(
                f"nperiodic_dimensions={int(query.dimensionality)}"
            )
        if query.modified_after is not None:
            filters.append(
                'last_modified>="'
                f"{query.modified_after.isoformat()}T00:00:00Z"
                '"'
            )
        if query.modified_before is not None:
            filters.append(
                'last_modified<="'
                f"{query.modified_before.isoformat()}T23:59:59Z"
                '"'
            )
        filters.extend(
            self._property_filter(item) for item in query.property_filters
        )
        return filters

    def _text_filter(self, text: str, mode: str) -> str:
        if mode not in self.query_modes:
            raise OnlineDatabaseError(
                f"{self.name} does not support the selected query type."
            )
        escaped = _escape_filter_string(text)
        if mode == "id":
            return f'id="{escaped}"'
        if mode == "name":
            if not self._name_fields:
                raise OnlineDatabaseError(
                    f"{self.name} does not support name searches."
                )
            name_filters = " OR ".join(
                f'{field} CONTAINS "{escaped}"'
                for field in self._name_fields
            )
            return f"({name_filters})"
        formula_fields = {
            "reduced": "chemical_formula_reduced",
            "hill": "chemical_formula_hill",
            "anonymous": "chemical_formula_anonymous",
            "descriptive": "chemical_formula_descriptive",
        }
        if mode in formula_fields:
            value = text
            if mode == "hill":
                value = Formula(re.sub(r"\s+", "", text)).format("hill")
            return (
                f'{formula_fields[mode]}="'
                f'{_escape_filter_string(value)}"'
            )
        if self._id_pattern and re.fullmatch(self._id_pattern, text):
            return f'id="{escaped}"'
        if re.fullmatch(
            r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?)+",
            re.sub(r"\s+", "", text),
        ):
            formula = Formula(re.sub(r"\s+", "", text)).format("hill")
            return (
                'chemical_formula_hill="'
                f'{_escape_filter_string(formula)}"'
            )
        if self._name_fields:
            name_filters = " OR ".join(
                f'{field} CONTAINS "{escaped}"'
                for field in self._name_fields
            )
            return f"({name_filters})"
        return f'id="{escaped}"'

    def _property_filter(self, criterion) -> str:
        definitions = {
            item.key: item for item in self.property_filter_definitions
        }
        definition = definitions.get(criterion.key)
        if definition is None:
            raise OnlineDatabaseError(
                f"{self.name} does not support property filter "
                f"{criterion.key!r}."
            )
        operators = {item[0] for item in definition.operators}
        if criterion.operator not in operators:
            raise OnlineDatabaseError(
                f"Operator {criterion.operator!r} is not supported for "
                f"{definition.label}."
            )
        value = criterion.value
        try:
            if definition.value_type == "integer":
                formatted = str(int(value))
            elif definition.value_type == "float":
                formatted = f"{float(value):g}"
            elif definition.value_type == "boolean":
                formatted = "TRUE" if bool(value) else "FALSE"
            else:
                if definition.choices:
                    allowed = {item[1] for item in definition.choices}
                    if value not in allowed:
                        raise ValueError
                formatted = f'"{_escape_filter_string(str(value))}"'
        except (TypeError, ValueError) as exc:
            raise OnlineDatabaseError(
                f"Invalid value for {definition.label}."
            ) from exc
        return (
            f"{definition.property_name} "
            f"{criterion.operator} {formatted}"
        )

    def _parse_page(self, payload: dict[str, Any], *, request_url: str) -> SearchPage:
        resources = payload.get("data")
        if not isinstance(resources, list):
            raise OnlineDatabaseError("The database returned an invalid result page.")
        results = tuple(self._summary(resource) for resource in resources)
        links = payload.get("links") or {}
        meta = payload.get("meta") or {}
        return SearchPage(
            results=results,
            next_url=self._page_link(links.get("next"), request_url),
            previous_url=self._page_link(links.get("prev"), request_url),
            total=_as_optional_int(
                meta.get("data_returned_available", meta.get("data_returned"))
            ),
        )

    @staticmethod
    def _page_link(value: Any, request_url: str) -> Optional[str]:
        if isinstance(value, dict):
            value = value.get("href")
        if not isinstance(value, str) or not value:
            return None
        return urljoin(request_url, value)

    def _summary(self, resource: dict[str, Any]) -> StructureSummary:
        attributes = resource.get("attributes")
        if not isinstance(attributes, dict):
            raise OnlineDatabaseError("A database result contains no attributes.")
        entry_id = str(resource.get("id", ""))
        if not entry_id:
            raise OnlineDatabaseError("A database result contains no identifier.")
        name = self._first_text(attributes, self._name_fields)
        formula = (
            attributes.get("chemical_formula_reduced")
            or attributes.get("chemical_formula_descriptive")
            or ""
        )
        return StructureSummary(
            provider_id=self.id,
            entry_id=entry_id,
            formula=str(formula),
            name=name,
            space_group=self._field_text(
                attributes, self._space_group_field
            ),
            space_group_number=_as_optional_int(
                attributes.get(self._space_group_number_field)
                if self._space_group_number_field
                else None
            ),
            site_count=_as_optional_int(attributes.get("nsites")),
            method=self._field_text(attributes, self._method_field)
            or self.default_method,
            year=_as_optional_int(
                attributes.get(self._year_field) if self._year_field else None
            ),
            status=self._field_text(attributes, self._status_field),
            duplicate_of=(
                str(attributes[self._duplicate_field])
                if self._duplicate_field
                and attributes.get(self._duplicate_field) is not None
                else None
            ),
            optimal_entry=(
                str(attributes[self._optimal_field])
                if self._optimal_field
                and attributes.get(self._optimal_field) is not None
                else None
            ),
            structure_features=tuple(attributes.get("structure_features") or ()),
            doi=self._field_text(attributes, self._doi_field)
            or self.default_doi,
            raw_attributes=dict(attributes),
        )

    @staticmethod
    def _field_text(
        attributes: dict[str, Any], field: Optional[str]
    ) -> str:
        if not field or attributes.get(field) is None:
            return ""
        return str(attributes[field]).strip()

    @classmethod
    def _first_text(
        cls, attributes: dict[str, Any], fields: tuple[str, ...]
    ) -> str:
        return next(
            (
                cls._field_text(attributes, field)
                for field in fields
                if attributes.get(field)
            ),
            "",
        )

    def _entry_url(
        self, attributes: dict[str, Any], summary: StructureSummary
    ) -> str:
        if self._entry_page_field and attributes.get(self._entry_page_field):
            return str(attributes[self._entry_page_field])
        entry_id = quote(summary.entry_id, safe="")
        return urljoin(self.base_url, f"structures/{entry_id}")

    def _downloaded_structure(
        self,
        resource: dict[str, Any],
        *,
        fallback_summary: StructureSummary,
    ) -> DownloadedStructure:
        attributes = resource.get("attributes")
        if not isinstance(attributes, dict):
            raise OnlineDatabaseError("The selected database entry has no attributes.")
        summary = self._summary(resource)
        if not summary.formula:
            summary = fallback_summary
        atoms, conversion_warnings = self._atoms_from_attributes(attributes)
        warnings = tuple(dict.fromkeys(summary.warnings + conversion_warnings))
        provenance = StructureProvenance(
            provider_id=self.id,
            provider_name=self.name,
            entry_id=summary.entry_id,
            entry_url=self._entry_url(attributes, summary),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            license_name=self.license_name,
            license_url=self.license_url,
            experimental=self.experimental,
            doi=summary.doi,
            method=summary.method,
            temperature_kelvin=_as_optional_float(
                attributes.get(self._temperature_field)
                if self._temperature_field
                else None
            ),
            pressure_kpa=_as_optional_float(
                attributes.get(self._pressure_field)
                if self._pressure_field
                else None
            ),
            warnings=warnings,
            provider_metadata={
                "structure_features": list(summary.structure_features),
                "optimade_assemblies": attributes.get("assemblies"),
                "provider_fields": {
                    field: value
                    for field, value in attributes.items()
                    if field.startswith("_")
                },
            },
        )
        atoms.info["online_database"] = provenance.as_dict()
        return DownloadedStructure(
            atoms=atoms,
            summary=summary,
            provenance=provenance,
            warnings=warnings,
        )

    @staticmethod
    def _atoms_from_attributes(
        attributes: dict[str, Any],
    ) -> tuple[Atoms, tuple[str, ...]]:
        try:
            lattice = np.asarray(
                attributes.get("lattice_vectors"), dtype=float
            )
            positions = np.asarray(
                attributes.get("cartesian_site_positions"), dtype=float
            )
        except (TypeError, ValueError) as exc:
            raise OnlineDatabaseError(
                "The selected structure has invalid coordinates."
            ) from exc
        if lattice.shape != (3, 3) or not np.isfinite(lattice).all():
            raise OnlineDatabaseError("The selected structure has no valid unit cell.")
        if (
            positions.ndim != 2
            or positions.shape[1:] != (3,)
            or not np.isfinite(positions).all()
        ):
            raise OnlineDatabaseError(
                "The selected structure has no valid atomic positions."
            )
        declared_site_count = _as_optional_int(attributes.get("nsites"))
        if (
            declared_site_count is not None
            and declared_site_count != len(positions)
        ):
            raise OnlineDatabaseError(
                "The selected structure has an inconsistent site count."
            )

        features = set(attributes.get("structure_features") or ())
        unsupported_features = features.intersection(
            {"implicit_atoms", "site_attachments"}
        )
        if unsupported_features:
            names = ", ".join(sorted(unsupported_features))
            raise OnlineDatabaseError(
                "The selected structure uses unsupported OPTIMADE features: "
                f"{names}."
            )

        species_at_sites = attributes.get("species_at_sites")
        if not isinstance(species_at_sites, list) or len(species_at_sites) != len(
            positions
        ):
            raise OnlineDatabaseError(
                "The selected structure has inconsistent site information."
            )
        species_definitions = {
            item.get("name"): item
            for item in (attributes.get("species") or ())
            if isinstance(item, dict) and item.get("name")
        }
        assemblies = attributes.get("assemblies")
        site_probabilities = OptimadeProvider._site_probabilities(
            assemblies, len(positions)
        )

        symbols = []
        occupancies: dict[str, dict[str, float]] = {}
        labels = []
        warnings = []
        for index, species_name in enumerate(species_at_sites):
            definition = species_definitions.get(species_name)
            if definition is None:
                raise OnlineDatabaseError(
                    "The selected structure refers to an undefined species."
                )
            if definition.get("attached") or definition.get("nattached"):
                raise OnlineDatabaseError(
                    "The selected structure contains attached atoms without "
                    "explicit positions."
                )
            occupation = OptimadeProvider._occupation(definition)
            probability = site_probabilities[index]
            if probability < 1.0:
                occupation = {
                    symbol: concentration * probability
                    for symbol, concentration in occupation.items()
                }
                occupation["Vc"] = (
                    occupation.get("Vc", 0.0) + 1.0 - probability
                )
                occupation = OptimadeProvider._normalize_occupation(
                    occupation
                )
            occupancies[str(index)] = occupation
            real_species = [
                (symbol, concentration)
                for symbol, concentration in occupation.items()
                if symbol != "Vc"
            ]
            symbols.append(
                max(real_species, key=lambda item: item[1])[0]
                if real_species
                else "X"
            )
            labels.append(str(species_name or f"site-{index + 1}"))

        if assemblies:
            warnings.append(
                "Correlated disorder assemblies are preserved in provenance, "
                "but SPR-KKR represents their site concentrations independently."
            )

        pbc = attributes.get("dimension_types") or [1, 1, 1]
        if (
            not isinstance(pbc, list)
            or len(pbc) != 3
            or any(value not in (0, 1) for value in pbc)
        ):
            raise OnlineDatabaseError(
                "The selected structure has invalid periodic dimensions."
            )
        atoms = Atoms(symbols=symbols, positions=positions, cell=lattice, pbc=pbc)
        atoms.set_array("spacegroup_kinds", np.arange(len(atoms), dtype=int))
        atoms.set_array("labels", np.asarray(labels, dtype=object))
        atoms.info["occupancy"] = occupancies
        if assemblies:
            atoms.info["optimade_assemblies"] = assemblies
        return atoms, tuple(warnings)

    @staticmethod
    def _site_probabilities(
        assemblies: Any, site_count: int
    ) -> list[float]:
        probabilities = [1.0] * site_count
        if not assemblies:
            return probabilities
        if not isinstance(assemblies, list):
            raise OnlineDatabaseError(
                "The selected structure has invalid disorder assemblies."
            )

        assigned_sites = set()
        for assembly in assemblies:
            if not isinstance(assembly, dict):
                raise OnlineDatabaseError(
                    "The selected structure has invalid disorder assemblies."
                )
            groups = assembly.get("sites_in_groups")
            group_probabilities = assembly.get("group_probabilities")
            if (
                not isinstance(groups, list)
                or not isinstance(group_probabilities, list)
                or len(groups) != len(group_probabilities)
            ):
                raise OnlineDatabaseError(
                    "The selected structure has invalid disorder assemblies."
                )
            for group, probability in zip(groups, group_probabilities):
                try:
                    value = float(probability)
                except (TypeError, ValueError) as exc:
                    raise OnlineDatabaseError(
                        "The selected structure has an invalid assembly "
                        "probability."
                    ) from exc
                if not 0.0 <= value <= 1.0 or not isinstance(group, list):
                    raise OnlineDatabaseError(
                        "The selected structure has an invalid disorder "
                        "assembly."
                    )
                for site in group:
                    if (
                        not isinstance(site, int)
                        or isinstance(site, bool)
                        or not 0 <= site < site_count
                        or site in assigned_sites
                    ):
                        raise OnlineDatabaseError(
                            "The selected structure has an invalid disorder "
                            "assembly."
                        )
                    assigned_sites.add(site)
                    probabilities[site] = value
        return probabilities

    @staticmethod
    def _occupation(definition: dict[str, Any]) -> dict[str, float]:
        symbols = definition.get("chemical_symbols") or ()
        concentrations = definition.get("concentration") or ()
        if len(symbols) != len(concentrations) or not symbols:
            raise OnlineDatabaseError(
                "The selected structure contains an invalid species definition."
            )

        occupation: dict[str, float] = {}
        for symbol, concentration in zip(symbols, concentrations):
            try:
                value = float(concentration)
            except (TypeError, ValueError) as exc:
                raise OnlineDatabaseError(
                    "The selected structure contains an invalid concentration."
                ) from exc
            if value < 0:
                raise OnlineDatabaseError(
                    "The selected structure contains a negative concentration."
                )
            if symbol == "vacancy":
                target = "Vc"
            elif symbol == "X":
                raise OnlineDatabaseError(
                    "The selected structure contains an unknown chemical species."
                )
            elif symbol not in atomic_numbers:
                raise OnlineDatabaseError(
                    f"The selected structure contains unknown element {symbol!r}."
                )
            else:
                target = symbol
            occupation[target] = occupation.get(target, 0.0) + value

        return OptimadeProvider._normalize_occupation(occupation)

    @staticmethod
    def _normalize_occupation(
        occupation: dict[str, float],
    ) -> dict[str, float]:
        occupation = {
            symbol: concentration
            for symbol, concentration in occupation.items()
            if concentration > 0.0
        }
        total = sum(occupation.values())
        if total > 1.0 + 1e-6:
            raise OnlineDatabaseError(
                "The selected structure has site concentrations greater than one."
            )
        if total < 1.0 - 1e-6:
            occupation["Vc"] = occupation.get("Vc", 0.0) + (1.0 - total)
        correction = 1.0 - sum(occupation.values())
        correction_target = (
            "Vc"
            if "Vc" in occupation
            else max(occupation, key=occupation.get)
        )
        occupation[correction_target] += correction
        return occupation


class CodOptimadeProvider(OptimadeProvider):
    id = "cod"
    name = "Crystallography Open Database"
    base_url = "https://www.crystallography.net/cod/optimade/v1/"
    homepage = "https://www.crystallography.net/cod"
    max_page_limit = 10
    query_placeholder = "Formula, name, or seven-digit COD ID"
    license_name = "CC0-1.0"
    license_url = "https://creativecommons.org/publicdomain/zero/1.0/"
    experimental = True
    query_modes = (
        "auto",
        "id",
        "name",
        "reduced",
        "hill",
        "descriptive",
    )
    capabilities = ProviderCapabilities(
        space_group=True,
        max_sites=False,
        duplicate_filter=True,
        validity_filter=True,
        disorder_filter=False,
    )
    _id_pattern = r"\d{7}"
    _name_fields = (
        "_cod_commonname",
        "_cod_chemname",
        "_cod_mineral",
    )
    _space_group_field = "_cod_sg"
    _space_group_number_field = "_cod_sgnumber"
    _method_field = "_cod_method"
    _year_field = "_cod_year"
    _status_field = "_cod_status"
    _duplicate_field = "_cod_duplicateof"
    _optimal_field = "_cod_optimal"
    _doi_field = "_cod_doi"
    _temperature_field = "_cod_celltemp"
    _pressure_field = "_cod_cellpressure"
    _validity_filter = (
        '(_cod_status IS UNKNOWN OR '
        '(_cod_status!="errors" AND _cod_status!="retracted"))'
    )
    _summary_fields = OptimadeProvider._summary_fields + (
        "_cod_chemname",
        "_cod_commonname",
        "_cod_mineral",
        "_cod_sg",
        "_cod_sgnumber",
        "_cod_method",
        "_cod_year",
        "_cod_status",
        "_cod_duplicateof",
        "_cod_optimal",
        "_cod_doi",
        "_cod_flags",
        "_cod_celltemp",
        "_cod_cellpressure",
    )
    property_filter_definitions = (
        PropertyFilterDefinition(
            "year",
            "Publication year",
            "_cod_year",
            "integer",
            _NUMBER_OPERATORS,
            "e.g. 2020",
        ),
        PropertyFilterDefinition(
            "method",
            "Experimental method",
            "_cod_method",
            "string",
            _TEXT_OPERATORS,
            "e.g. X-ray diffraction",
        ),
        PropertyFilterDefinition(
            "doi",
            "DOI",
            "_cod_doi",
            "string",
            _EQUALITY_OPERATOR,
            "e.g. 10.1234/example",
        ),
        PropertyFilterDefinition(
            "cell_volume",
            "Cell volume",
            "_cod_vol",
            "float",
            _NUMBER_OPERATORS,
            "volume",
            unit="Å³",
        ),
    )

    def _entry_url(
        self, attributes: dict[str, Any], summary: StructureSummary
    ) -> str:
        return f"{self.homepage}/{summary.entry_id}.html"


class NomadOptimadeProvider(OptimadeProvider):
    id = "nomad"
    name = "NOMAD"
    base_url = "https://nomad-lab.eu/prod/v1/optimade/v1/"
    homepage = "https://nomad-lab.eu"
    max_page_limit = 50
    query_placeholder = "Formula, name, or NOMAD entry ID"
    license_name = "CC-BY-4.0"
    license_url = "https://creativecommons.org/licenses/by/4.0/"
    capabilities = ProviderCapabilities(space_group=True)
    _id_pattern = r"[-_A-Za-z0-9]{28}"
    _name_fields = (
        "_nmd_entry_name",
        "_nmd_results_material_symmetry_structure_name",
    )
    _space_group_field = (
        "_nmd_results_material_symmetry_space_group_symbol"
    )
    _space_group_number_field = (
        "_nmd_results_material_symmetry_space_group_number"
    )
    _method_field = "_nmd_results_method_method_name"
    _entry_page_field = "_nmd_entry_page_url"
    _summary_fields = OptimadeProvider._summary_fields + (
        "_nmd_entry_name",
        "_nmd_results_material_symmetry_structure_name",
        "_nmd_results_material_symmetry_space_group_symbol",
        "_nmd_results_material_symmetry_space_group_number",
        "_nmd_results_method_method_name",
        "_nmd_entry_page_url",
        "_nmd_external_db",
        "_nmd_external_id",
    )
    property_filter_definitions = (
        PropertyFilterDefinition(
            "crystal_system",
            "Crystal system",
            "_nmd_results_material_symmetry_crystal_system",
            "choice",
            _EQUALITY_OPERATOR,
            choices=tuple(
                (item.title(), item)
                for item in (
                    "triclinic",
                    "monoclinic",
                    "orthorhombic",
                    "tetragonal",
                    "trigonal",
                    "hexagonal",
                    "cubic",
                )
            ),
        ),
        PropertyFilterDefinition(
            "program",
            "Simulation program",
            "_nmd_results_method_simulation_program_name",
            "string",
            _TEXT_OPERATORS,
            "e.g. VASP",
        ),
        PropertyFilterDefinition(
            "xc_functional",
            "XC functional",
            "_nmd_results_method_simulation_dft_xc_functional_names",
            "string",
            _LIST_TEXT_OPERATORS,
            "e.g. GGA_X_PBE",
        ),
        PropertyFilterDefinition(
            "cell_volume",
            "Conventional-cell volume",
            (
                "_nmd_results_properties_structures_"
                "structure_conventional_cell_volume"
            ),
            "float",
            _NUMBER_OPERATORS,
            "volume",
            unit="Å³",
        ),
    )

    def search(
        self,
        query: StructureSearchQuery,
        *,
        page_url: Optional[str] = None,
    ) -> SearchPage:
        url = page_url or self._search_url(query)
        parts = urlsplit(url)
        parameters = dict(parse_qsl(parts.query, keep_blank_values=True))
        limit = max(
            1,
            min(
                int(parameters.get("page_limit", query.page_limit)),
                self.max_page_limit,
            ),
        )
        offset = max(0, int(parameters.get("page_offset", 0)))
        results, total, skipped = self._search_range(
            url, offset=offset, limit=limit
        )
        previous_url = (
            self._page_url(url, max(0, offset - limit), limit)
            if offset
            else None
        )
        next_url = (
            self._page_url(url, offset + limit, limit)
            if total is None or offset + limit < total
            else None
        )
        warnings = ()
        if skipped:
            verb = "was" if skipped == 1 else "were"
            warnings = (
                f"{skipped} invalid NOMAD "
                f"{'entry' if skipped == 1 else 'entries'} {verb} "
                "omitted from this page.",
            )
        return SearchPage(
            results=tuple(results),
            next_url=next_url,
            previous_url=previous_url,
            total=total,
            warnings=warnings,
        )

    def _search_range(
        self, url: str, *, offset: int, limit: int
    ) -> tuple[list[StructureSummary], Optional[int], int]:
        request_url = self._page_url(url, offset, limit)
        try:
            payload = self._transport(request_url)
        except InvalidProviderRecordError:
            if limit == 1:
                return [], None, 1
            left_limit = limit // 2
            left = self._search_range(
                url, offset=offset, limit=left_limit
            )
            right = self._search_range(
                url,
                offset=offset + left_limit,
                limit=limit - left_limit,
            )
            return (
                left[0] + right[0],
                left[1] if left[1] is not None else right[1],
                left[2] + right[2],
            )
        page = self._parse_page(payload, request_url=request_url)
        return list(page.results), page.total, 0

    @staticmethod
    def _page_url(url: str, offset: int, limit: int) -> str:
        parts = urlsplit(url)
        parameters = dict(parse_qsl(parts.query, keep_blank_values=True))
        parameters["page_offset"] = str(offset)
        parameters["page_limit"] = str(limit)
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(parameters),
                parts.fragment,
            )
        )


class MaterialsCloudMc3dOptimadeProvider(OptimadeProvider):
    id = "materials-cloud-mc3d-pbe"
    name = "Materials Cloud MC3D (PBE)"
    base_url = (
        "https://optimade.materialscloud.org/main/mc3d-pbe-v1/v1/"
    )
    homepage = "https://mc3d.materialscloud.org"
    max_page_limit = 50
    query_placeholder = "Formula, MC3D ID, or OPTIMADE UUID"
    license_name = "CC-BY-4.0"
    license_url = "https://creativecommons.org/licenses/by/4.0/"
    experimental = False
    default_doi = "10.24435/materialscloud:jn-ac"
    default_method = "DFT (PBE)"
    capabilities = ProviderCapabilities()
    _id_pattern = (
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    _name_fields = ("_mcloud_mc3d_id",)
    _summary_fields = OptimadeProvider._summary_fields + (
        "_mcloud_mc3d_id",
        "_mcloud_source_db",
        "_mcloud_source_db_id",
    )
    property_filter_definitions = (
        PropertyFilterDefinition(
            "source_database",
            "Source database",
            "_mcloud_source_db",
            "string",
            _EQUALITY_OPERATOR,
            "e.g. COD",
        ),
        PropertyFilterDefinition(
            "total_energy",
            "Total energy",
            "_mcloud_total_energy",
            "float",
            _NUMBER_OPERATORS,
            "energy",
            unit="eV",
        ),
        PropertyFilterDefinition(
            "cell_volume",
            "Cell volume",
            "_mcloud_cell_volume",
            "float",
            _NUMBER_OPERATORS,
            "volume",
            unit="Å³",
        ),
        PropertyFilterDefinition(
            "total_magnetization",
            "Total magnetization",
            "_mcloud_total_magnetization",
            "float",
            _NUMBER_OPERATORS,
            "magnetization",
        ),
    )
