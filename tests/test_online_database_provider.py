from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from ase2sprkkr_gui.online_databases.models import (
    PropertyFilter,
    StructureSearchQuery,
)
from ase2sprkkr_gui.online_databases.optimade import (
    CodOptimadeProvider,
    InvalidProviderRecordError,
    MaterialsCloudMc3dOptimadeProvider,
    NomadOptimadeProvider,
    OnlineDatabaseError,
)


def _summary_resource(entry_id="1000001"):
    return {
        "id": entry_id,
        "type": "structures",
        "attributes": {
            "chemical_formula_reduced": "Fe2O3",
            "nsites": 5,
            "structure_features": [],
            "_cod_commonname": "hematite",
            "_cod_sg": "R-3c",
            "_cod_sgnumber": 167,
            "_cod_method": "single crystal X-ray diffraction",
            "_cod_year": 2020,
            "_cod_status": None,
            "_cod_duplicateof": None,
            "_cod_optimal": 1000001,
            "_cod_doi": "10.1234/example",
        },
    }


def test_cod_search_builds_filters_and_parses_pagination():
    requested = []

    def transport(url):
        requested.append(url)
        return {
            "data": [_summary_resource()],
            "meta": {"data_returned_available": 123},
            "links": {
                "next": "/cod/optimade/v1/structures?page_offset=50",
                "prev": None,
            },
        }

    provider = CodOptimadeProvider(transport=transport)
    page = provider.search(
        StructureSearchQuery(
            text="Fe2O3",
            elements=("Fe", "O"),
            element_match="only",
            space_group=167,
            min_sites=2,
            max_sites=20,
            structure_order="ordered",
        )
    )

    query = parse_qs(urlparse(requested[0]).query)
    assert query["page_limit"] == ["10"]
    filter_text = query["filter"][0]
    assert 'chemical_formula_hill="Fe2O3"' in filter_text
    assert 'elements HAS ALL "Fe", "O"' in filter_text
    assert "nelements=2" in filter_text
    assert "_cod_sgnumber=167" in filter_text
    assert "nsites<=20" not in filter_text
    assert "nsites>=2" not in filter_text
    assert "_cod_duplicateof IS UNKNOWN" in filter_text
    assert 'NOT structure_features HAS "disorder"' not in filter_text
    assert page.total == 123
    assert page.next_url == (
        "https://www.crystallography.net/cod/optimade/v1/"
        "structures?page_offset=50"
    )
    assert page.results[0].name == "hematite"
    assert page.results[0].space_group_number == 167


def test_formula_is_normalized_to_the_hill_format_supported_by_cod():
    provider = CodOptimadeProvider(transport=lambda _url: {"data": []})

    filters = provider._filters(StructureSearchQuery(text="NaCl"))

    assert 'chemical_formula_hill="ClNa"' in filters


def test_cod_fetch_preserves_partial_occupancies_and_provenance():
    full_resource = _summary_resource()
    full_resource["attributes"].update(
        {
            "nsites": 3,
            "lattice_vectors": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 6.0]],
            "cartesian_site_positions": [
                [0.0, 0.0, 0.0],
                [2.0, 2.0, 2.0],
                [1.0, 1.0, 1.0],
            ],
            "dimension_types": [1, 1, 1],
            "species_at_sites": ["Fe", "mixed", "vac"],
            "species": [
                {
                    "name": "Fe",
                    "chemical_symbols": ["Fe"],
                    "concentration": [1.0],
                },
                {
                    "name": "mixed",
                    "chemical_symbols": ["Fe", "Ni"],
                    "concentration": [0.6, 0.3],
                },
                {
                    "name": "vac",
                    "chemical_symbols": ["vacancy"],
                    "concentration": [1.0],
                },
            ],
            "structure_features": ["assemblies", "disorder"],
            "assemblies": [
                {
                    "sites_in_groups": [[1], [2]],
                    "group_probabilities": [0.7, 0.3],
                }
            ],
            "_cod_celltemp": 295,
            "_cod_cellpressure": 101.325,
        }
    )

    provider = CodOptimadeProvider(
        transport=lambda _url: {"data": full_resource}
    )
    summary = provider._summary(_summary_resource())
    downloaded = provider.fetch(summary)

    assert downloaded.atoms.get_chemical_symbols() == ["Fe", "Fe", "X"]
    assert downloaded.atoms.info["occupancy"]["0"] == {"Fe": 1.0}
    assert downloaded.atoms.info["occupancy"]["1"] == {
        "Fe": pytest.approx(0.42),
        "Ni": pytest.approx(0.21),
        "Vc": pytest.approx(0.37),
    }
    assert downloaded.atoms.info["occupancy"]["2"] == {"Vc": 1.0}
    assert downloaded.provenance.entry_id == "1000001"
    assert downloaded.provenance.license_name == "CC0-1.0"
    assert downloaded.provenance.temperature_kelvin == 295.0
    assert downloaded.atoms.info["online_database"]["doi"] == "10.1234/example"
    assert downloaded.atoms.info["online_database"]["provider_metadata"][
        "optimade_assemblies"
    ] == full_resource["attributes"]["assemblies"]
    assert any("Correlated disorder" in item for item in downloaded.warnings)


def test_unknown_optimade_species_is_rejected():
    with pytest.raises(OnlineDatabaseError, match="unknown chemical species"):
        CodOptimadeProvider._occupation(
            {"chemical_symbols": ["X"], "concentration": [1.0]}
        )


def test_nomad_uses_standard_filters_and_extension_metadata():
    requested = []

    def transport(url):
        requested.append(url)
        return {
            "data": [
                {
                    "id": "-nRNXRS141f-QCPqMPOyJJzaEWTL",
                    "type": "structures",
                    "attributes": {
                        "chemical_formula_reduced": "Ac",
                        "nsites": 1,
                        "structure_features": [],
                        "_nmd_entry_name": "Actinium test",
                        "_nmd_results_material_symmetry_space_group_symbol": "Fm-3m",
                        "_nmd_results_material_symmetry_space_group_number": 225,
                        "_nmd_results_method_method_name": "DFT",
                    },
                }
            ],
            "meta": {"data_returned": 1},
            "links": {},
        }

    provider = NomadOptimadeProvider(transport=transport)
    page = provider.search(
        StructureSearchQuery(
            text="-nRNXRS141f-QCPqMPOyJJzaEWTL",
            elements=("Ac",),
            space_group=225,
            max_sites=10,
            dimensionality=3,
            structure_order="ordered",
        )
    )

    query = parse_qs(urlparse(requested[0]).query)
    filter_text = query["filter"][0]
    assert query["page_limit"] == ["50"]
    assert 'id="-nRNXRS141f-QCPqMPOyJJzaEWTL"' in filter_text
    assert 'elements HAS ALL "Ac"' in filter_text
    assert "_nmd_results_material_symmetry_space_group_number=225" in filter_text
    assert "nsites<=10" in filter_text
    assert 'NOT structure_features HAS "disorder"' in filter_text
    assert 'NOT structure_features HAS "implicit_atoms"' in filter_text
    assert "nperiodic_dimensions=3" in filter_text
    assert "_cod_" not in filter_text
    assert page.results[0].name == "Actinium test"
    assert page.results[0].space_group == "Fm-3m"
    assert page.results[0].space_group_number == 225
    assert page.results[0].method == "DFT"


def test_nomad_omits_only_records_rejected_by_provider_validation():
    requested_ranges = []

    def transport(url):
        query = parse_qs(urlparse(url).query)
        offset = int(query["page_offset"][0])
        limit = int(query["page_limit"][0])
        requested_ranges.append((offset, limit))
        if set(range(offset, offset + limit)).intersection({1, 3}):
            raise InvalidProviderRecordError("Invalid NOMAD record.")
        return {
            "data": [
                {
                    "id": f"entry-{index}",
                    "type": "structures",
                    "attributes": {
                        "chemical_formula_reduced": "CdMo",
                        "nsites": 2,
                        "structure_features": [],
                    },
                }
                for index in range(offset, offset + limit)
            ],
            "meta": {"data_returned_available": 6},
            "links": {},
        }

    page = NomadOptimadeProvider(transport=transport).search(
        StructureSearchQuery(
            elements=("Cd", "Mo"),
            element_match="all",
            page_limit=4,
        )
    )

    assert [item.entry_id for item in page.results] == [
        "entry-0",
        "entry-2",
    ]
    assert page.total == 6
    assert page.previous_url is None
    assert "page_offset=4" in page.next_url
    assert page.warnings == (
        "2 invalid NOMAD entries were omitted from this page.",
    )
    assert (0, 4) in requested_ranges
    assert (1, 1) in requested_ranges
    assert (3, 1) in requested_ranges


def test_materials_cloud_supports_mc3d_and_optimade_ids():
    provider = MaterialsCloudMc3dOptimadeProvider(
        transport=lambda _url: {"data": []}
    )

    mc3d_filters = provider._filters(
        StructureSearchQuery(text="mc3d-38464", dimensionality=3)
    )
    uuid_filters = provider._filters(
        StructureSearchQuery(
            text="3f646254-95ef-45a8-a2b4-236a6fb174a6"
        )
    )

    assert '(_mcloud_mc3d_id CONTAINS "mc3d-38464")' in mc3d_filters
    assert (
        'id="3f646254-95ef-45a8-a2b4-236a6fb174a6"'
        in uuid_filters
    )
    assert "nperiodic_dimensions=3" in mc3d_filters


def test_common_optimade_filters_cover_ranges_and_search_modes():
    provider = NomadOptimadeProvider(
        transport=lambda _url: {"data": [], "links": {}}
    )

    filters = provider._filters(
        StructureSearchQuery(
            text="A2B",
            query_mode="anonymous",
            elements=("Fe", "O"),
            element_match="any",
            excluded_elements=("Pb", "U"),
            min_elements=2,
            max_elements=4,
            min_sites=3,
            max_sites=24,
            dimensionality=2,
            structure_order="disordered",
            modified_after=date(2020, 1, 2),
            modified_before=date(2024, 3, 4),
        )
    )

    assert 'chemical_formula_anonymous="A2B"' in filters
    assert 'elements HAS ANY "Fe", "O"' in filters
    assert 'NOT elements HAS ANY "Pb", "U"' in filters
    assert "nelements>=2" in filters
    assert "nelements<=4" in filters
    assert "nsites>=3" in filters
    assert "nsites<=24" in filters
    assert "nperiodic_dimensions=2" in filters
    assert 'structure_features HAS "disorder"' in filters
    assert 'last_modified>="2020-01-02T00:00:00Z"' in filters
    assert 'last_modified<="2024-03-04T23:59:59Z"' in filters


@pytest.mark.parametrize(
    ("provider", "criterion", "expected"),
    (
        (
            CodOptimadeProvider,
            PropertyFilter("year", ">=", 2020),
            "_cod_year >= 2020",
        ),
        (
            NomadOptimadeProvider,
            PropertyFilter("program", "CONTAINS", "VASP"),
            (
                "_nmd_results_method_simulation_program_name "
                'CONTAINS "VASP"'
            ),
        ),
        (
            MaterialsCloudMc3dOptimadeProvider,
            PropertyFilter("cell_volume", "<=", 100.5),
            "_mcloud_cell_volume <= 100.5",
        ),
    ),
)
def test_provider_specific_filters_are_validated(
    provider, criterion, expected
):
    instance = provider(transport=lambda _url: {"data": []})

    filters = instance._filters(
        StructureSearchQuery(property_filters=(criterion,))
    )

    assert expected in filters


def test_search_query_rejects_conflicting_element_constraints():
    with pytest.raises(ValueError, match="Required and excluded"):
        StructureSearchQuery(
            elements=("Fe",),
            excluded_elements=("Fe",),
        )


@pytest.mark.parametrize(
    (
        "provider",
        "extra_attributes",
        "expected_name",
        "expected_method",
        "expected_experimental",
    ),
    (
        (
            NomadOptimadeProvider,
            {
                "_nmd_entry_name": "NOMAD iron",
                "_nmd_entry_page_url": "https://nomad.example/entry/test-1",
            },
            "NOMAD iron",
            "",
            None,
        ),
        (
            MaterialsCloudMc3dOptimadeProvider,
            {
                "_mcloud_mc3d_id": "mc3d-1",
                "_mcloud_source_db": "cod",
                "_mcloud_source_db_id": "1000001",
            },
            "mc3d-1",
            "DFT (PBE)",
            False,
        ),
    ),
)
def test_standard_provider_fetch_uses_shared_conversion_and_provenance(
    provider,
    extra_attributes,
    expected_name,
    expected_method,
    expected_experimental,
):
    resource = {
        "id": "test-1",
        "type": "structures",
        "attributes": {
            "chemical_formula_reduced": "Fe",
            "nsites": 1,
            "structure_features": [],
            "lattice_vectors": [
                [2.8, 0.0, 0.0],
                [0.0, 2.8, 0.0],
                [0.0, 0.0, 2.8],
            ],
            "cartesian_site_positions": [[0.0, 0.0, 0.0]],
            "dimension_types": [1, 1, 1],
            "species_at_sites": ["Fe"],
            "species": [
                {
                    "name": "Fe",
                    "chemical_symbols": ["Fe"],
                    "concentration": [1.0],
                }
            ],
            "assemblies": None,
            **extra_attributes,
        },
    }
    instance = provider(transport=lambda _url: {"data": resource})
    summary = instance._summary(resource)

    downloaded = instance.fetch(summary)

    assert downloaded.atoms.get_chemical_formula() == "Fe"
    assert downloaded.summary.name == expected_name
    assert downloaded.provenance.license_name == "CC-BY-4.0"
    assert downloaded.provenance.experimental is expected_experimental
    assert downloaded.provenance.method == expected_method
    assert downloaded.atoms.info["online_database"]["provider_id"] == instance.id
