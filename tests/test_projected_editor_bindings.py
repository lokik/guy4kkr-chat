"""Generic value editors consume projected bindings without option proxies."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.input_parameters.field_binding import (
    ProjectedFieldBinding,
    create_field_binding,
)
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement, field
from ase2sprkkr_gui.gui.widgets.input_parameters.registry import create_editor
from ase2sprkkr_gui.gui.widgets.input_parameters.scalar import (
    IntegerEditor,
    KeywordEditor,
    RealEditor,
    TextEditor,
)


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_generic_scalar_editors_accept_optionless_projected_bindings(application):
    session = InputParametersSession(InputParameters.create("scf"))
    definitions = (
        (("SCF", "NITER"), "Iterations", "integer", IntegerEditor),
        (("TAU", "CLURAD"), "Cluster radius", "real", RealEditor),
        (("TAU", "BZINT"), "Integration", "keyword", KeywordEditor),
        (("CONTROL", "DATASET"), "Dataset name", "text", TextEditor),
    )
    editors = {}
    for path, label, editor_name, editor_type in definitions:
        root = create_field_binding(session, field(*path, label), "expert")
        binding = ProjectedFieldBinding(
            root,
            FieldPlacement(path, label, editor=editor_name),
            project_value=lambda value: value,
            replace_value=lambda _old, value: value,
            value_type=root.value_type,
            allows_unset=False,
        )
        assert binding.option is None
        editors[editor_name] = create_editor(binding, binding.placement)
        assert isinstance(editors[editor_name], editor_type)

    editors["integer"].setValue(17)
    assert session.value(("SCF", "NITER")) == 17
    editors["real"].setValue(1.25)
    assert session.value(("TAU", "CLURAD")) == pytest.approx(1.25)
    keyword = editors["keyword"]
    alternative = next(
        index for index in range(keyword.count())
        if keyword.itemData(index) != session.value(("TAU", "BZINT"))
    )
    keyword.setCurrentIndex(alternative)
    assert session.value(("TAU", "BZINT")) == keyword.itemData(alternative)
    editors["text"].setText("projected-case")
    assert editors["text"].commit()
    assert session.value(("CONTROL", "DATASET")) == "projected-case"
