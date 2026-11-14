import os
from datetime import date

import pytest

from ase2sprkkr_gui.online_databases import (
    CodOptimadeProvider,
    MaterialsCloudMc3dOptimadeProvider,
    NomadOptimadeProvider,
    PropertyFilter,
    StructureSearchQuery,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("ASE2SPRKKR_GUI_RUN_LIVE_OPTIMADE") != "1",
    reason="set ASE2SPRKKR_GUI_RUN_LIVE_OPTIMADE=1 to query public OPTIMADE APIs",
)


@pytest.mark.parametrize(
    ("provider", "query"),
    (
        (
            CodOptimadeProvider(),
            StructureSearchQuery(
                text="Fe2O3",
                elements=("Fe", "O"),
                element_match="only",
                excluded_elements=("U",),
                min_elements=2,
                max_elements=2,
                dimensionality=3,
                modified_after=date(1900, 1, 1),
                page_limit=1,
            ),
        ),
        (
            NomadOptimadeProvider(),
            StructureSearchQuery(
                elements=("Cd", "Mo"),
                element_match="all",
                excluded_elements=("U",),
                min_elements=2,
                max_elements=5,
                dimensionality=3,
                modified_after=date(1900, 1, 1),
                page_limit=10,
            ),
        ),
        (
            MaterialsCloudMc3dOptimadeProvider(),
            StructureSearchQuery(
                elements=("Fe", "O"),
                element_match="only",
                excluded_elements=("U",),
                min_elements=2,
                max_elements=2,
                min_sites=1,
                max_sites=20,
                dimensionality=3,
                structure_order="ordered",
                page_limit=1,
            ),
        ),
    ),
)
def test_live_search_and_fetch(provider, query):
    page = provider.search(query)

    assert page.results
    downloaded = provider.fetch(page.results[0])
    assert len(downloaded.atoms) > 0
    assert downloaded.provenance.provider_id == provider.id
    assert downloaded.provenance.entry_id == page.results[0].entry_id


@pytest.mark.parametrize(
    ("provider", "query"),
    (
        (
            CodOptimadeProvider(),
            StructureSearchQuery(
                elements=("Fe", "O"),
                element_match="all",
                property_filters=(
                    PropertyFilter("year", ">=", 2000),
                ),
                page_limit=1,
            ),
        ),
        (
            NomadOptimadeProvider(),
            StructureSearchQuery(
                elements=("Fe", "O"),
                element_match="all",
                property_filters=(
                    PropertyFilter("crystal_system", "=", "cubic"),
                ),
                page_limit=1,
            ),
        ),
        (
            MaterialsCloudMc3dOptimadeProvider(),
            StructureSearchQuery(
                elements=("Fe",),
                element_match="all",
                property_filters=(
                    PropertyFilter("cell_volume", ">=", 0.0),
                ),
                page_limit=1,
            ),
        ),
    ),
)
def test_live_provider_specific_filter(provider, query):
    page = provider.search(query)

    assert page.results


def test_live_materials_cloud_accepts_last_modified_filter():
    page = MaterialsCloudMc3dOptimadeProvider().search(
        StructureSearchQuery(
            modified_after=date(1900, 1, 1),
            page_limit=1,
        )
    )

    assert page is not None


@pytest.mark.parametrize(
    ("provider", "criterion"),
    (
        (CodOptimadeProvider(), PropertyFilter("year", ">=", 1900)),
        (
            CodOptimadeProvider(),
            PropertyFilter("method", "CONTAINS", "diffraction"),
        ),
        (
            CodOptimadeProvider(),
            PropertyFilter("doi", "=", "10.1000/not-a-real-doi"),
        ),
        (CodOptimadeProvider(), PropertyFilter("cell_volume", ">=", 0)),
        (
            NomadOptimadeProvider(),
            PropertyFilter("crystal_system", "=", "cubic"),
        ),
        (
            NomadOptimadeProvider(),
            PropertyFilter("program", "CONTAINS", "VASP"),
        ),
        (
            NomadOptimadeProvider(),
            PropertyFilter("xc_functional", "HAS", "GGA_X_PBE"),
        ),
        (NomadOptimadeProvider(), PropertyFilter("cell_volume", ">=", 0)),
        (
            MaterialsCloudMc3dOptimadeProvider(),
            PropertyFilter("source_database", "=", "cod"),
        ),
        (
            MaterialsCloudMc3dOptimadeProvider(),
            PropertyFilter("total_energy", "<=", 0),
        ),
        (
            MaterialsCloudMc3dOptimadeProvider(),
            PropertyFilter("cell_volume", ">=", 0),
        ),
        (
            MaterialsCloudMc3dOptimadeProvider(),
            PropertyFilter("total_magnetization", ">=", 0),
        ),
    ),
)
def test_live_every_exposed_provider_filter_is_accepted(
    provider, criterion
):
    page = provider.search(
        StructureSearchQuery(
            property_filters=(criterion,),
            page_limit=1,
        )
    )

    assert page is not None
