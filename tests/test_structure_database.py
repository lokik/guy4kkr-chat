from io import StringIO

import pytest

from ase2sprkkr_gui.physics.structure_database import (
    StructureDatabaseError,
    load_structure_database,
    parse_structure_database,
)


def test_bundled_xband_database_is_complete():
    prototypes = load_structure_database()

    assert len(prototypes) == 49
    assert sum(len(prototype.sites) for prototype in prototypes) == 104
    assert any(prototype.name.startswith("B2") for prototype in prototypes)
    assert any(prototype.name.startswith("A1") for prototype in prototypes)
    assert any(prototype.is_rhombohedral_setting for prototype in prototypes)


def test_parser_preserves_site_coordinates_and_name_parts():
    prototype = next(
        item
        for item in load_structure_database()
        if item.name.startswith("C4 ")
    )

    assert prototype.structure_type == "C4"
    assert prototype.pearson_symbol == "tP6"
    assert prototype.description == "TiO2 (Rutil)"
    assert prototype.space_group == 136
    assert prototype.sites[1].coordinates == ("x", "x", "0")
    assert prototype.sites[1].position(x=0.17, y=0.29, z=0.41) == (
        0.17,
        0.17,
        0.0,
    )


def test_nonstandard_name_is_used_as_description():
    prototype = load_structure_database()[0]

    assert prototype.name == "Molecular Perovskite x"
    assert prototype.description == prototype.name
    assert prototype.structure_type == ""


def test_base_centered_pearson_symbol_is_recognized():
    prototype = next(
        item for item in load_structure_database() if "ZrSi2" in item.name
    )

    assert prototype.structure_type == "C49"
    assert prototype.pearson_symbol == "oC12"
    assert prototype.description == "ZrSi2"


def test_parser_reports_malformed_record():
    malformed = StringIO(
        "\n".join(
            (
                "**********",
                "Broken cP1 Example",
                "221 PM-3M",
                "Oh^1",
                "486",
                "2",
                "a 0 0 0 1 m-3m",
            )
        )
    )

    with pytest.raises(StructureDatabaseError, match="declares 2 sites"):
        parse_structure_database(malformed)
