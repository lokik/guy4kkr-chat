"""Guided structure inspector: composition, geometry and host context."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import pytest
from ase import Atoms
from ase.build import bulk
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QFrame, QApplication, QBoxLayout

from ase2sprkkr import SPRKKRAtoms
from ase2sprkkr_gui.ase.embedding import EmbeddingDraft
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.widgets.structures.overview import (
    StructureOverviewWidget,
    structure_facts,
)
from ase2sprkkr.input_parameters.input_parameters import InputParameters


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_periodicity_and_cell_data_are_physical_properties():
    bulk_atoms = Atoms("Fe2", positions=[[0, 0, 0], [1, 1, 1]],
                       cell=(2, 3, 4), pbc=True)
    facts = structure_facts(bulk_atoms, status="ITR")
    assert "Type: Bulk (3D)" in facts
    assert "Composition: Fe2" in facts
    assert "Sites: 2" in facts
    assert "Periodicity: x, y, z (3D)" in facts
    assert "a=2.000, b=3.000, c=4.000" in facts
    assert "α=90.0, β=90.0, γ=90.0" in facts
    assert "SCF status: ITR" in facts

    finite = Atoms("H2", positions=[[0, 0, 0], [1, 0, 0]], pbc=False)
    finite_facts = structure_facts(finite)
    assert "Periodicity: None (finite cluster)" in finite_facts
    assert "Cell (Å)" not in finite_facts

    from ase2sprkkr.sprkkr.build import semiinfinite_system

    slab = semiinfinite_system(bulk("Cu", "sc", a=2.0), (0, 0))
    slab_facts = structure_facts(slab)
    assert "Type: 2D structure" in slab_facts
    assert "Periodicity: x, y (2D)" in slab_facts
    assert "Cell (Å)" in slab_facts


def test_overview_shows_separate_host_and_cluster_information(application):
    host = SPRKKRAtoms.promote_ase_atoms(bulk("Fe", "bcc", a=2.87)).potential
    host.SCF_INFO.SCFSTATUS = "ITR"
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    cluster = draft.to_atoms()

    widget = StructureOverviewWidget()
    widget.set_structure(cluster, kind="0d", scf_status="START")

    assert "Embedded cluster" in widget.details.text()
    assert "Periodicity: None" in widget.details.text()
    assert "Host structure" == widget.host_heading.text()
    assert "Bulk (3D)" in widget.host_details.text()
    assert "Composition:" in widget.host_details.text()
    assert "Cell (Å)" in widget.host_geometry.text()
    assert "SCF status: ITR" in widget.host_geometry.text()

    # The scope selector is a mutually exclusive radio group in the
    # right-hand control rail, above projection (3D) and Fit.
    assert widget.host_radio.text() == "Host"
    assert widget.cluster_radio.text() == "Cluster"
    assert widget.cluster_radio.isChecked()
    assert not widget.host_radio.isChecked()
    assert not widget._view_selector.isHidden()
    assert widget.preview.layout().itemAt(0).widget() is widget.preview.canvas
    assert widget.preview.layout().itemAt(1).layout() is not None
    assert widget.preview.projection.currentText() == "3D"
    assert widget.preview.fit_button.text() == "Fit"
    controls = widget.preview.layout().itemAt(1).layout()
    fit_index = next(i for i in range(controls.count())
                     if controls.itemAt(i).widget() is widget.preview.fit_button)
    assert controls.itemAt(fit_index + 1).widget() is widget.external_viewer_button
    assert widget.frameShape() == QFrame.Shape.NoFrame
    assert widget.layout().contentsMargins().left() == 0
    assert widget.external_viewer_button.text() == "Viewer"
    assert widget.external_viewer_button.toolTip() == "External viewer"
    assert widget.external_viewer_button.height() == 68
    assert widget.external_viewer_button.iconSize() == QSize(26, 26)
    assert widget.external_viewer_button.toolButtonStyle() == (
        Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    )

    widget.host_radio.setChecked(True)
    assert not widget.cluster_radio.isChecked()
    assert len(widget.preview._positions) == len(host.atoms)

    widget.cluster_radio.setChecked(True)
    assert not widget.host_radio.isChecked()
    assert len(widget.preview._positions) == len(cluster)
    widget.close()



def test_replacing_host_view_with_bulk_draws_preview_once(application, monkeypatch):
    host = SPRKKRAtoms.promote_ase_atoms(bulk("Fe", "bcc", a=2.87)).potential
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    widget = StructureOverviewWidget()
    widget.set_structure(cluster, kind="0d")
    widget.host_radio.setChecked(True)

    calls = []
    original = widget._render_preview

    def draw(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(widget, "_render_preview", draw)
    widget.set_structure(Atoms("Fe", cell=(3, 3, 3), pbc=True), kind="3d")
    assert widget.cluster_radio.isChecked()
    assert len(calls) == 1
    widget.close()


def test_host_facts_use_columns_when_wide_and_stack_when_narrow(application):
    host = SPRKKRAtoms.promote_ase_atoms(bulk("Fe", "bcc", a=2.87)).potential
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    widget = StructureOverviewWidget()
    widget.set_structure(cluster, kind="0d")
    widget.resize(500, 620)
    widget.show()
    application.processEvents()
    assert widget._host_layout.direction() == QBoxLayout.Direction.LeftToRight

    widget.resize(340, 620)
    application.processEvents()
    assert widget._host_layout.direction() == QBoxLayout.Direction.TopToBottom
    widget.close()


def test_simple_structure_hides_host_cluster_selector(application):
    widget = StructureOverviewWidget()
    widget.set_structure(Atoms("Fe", cell=(3, 3, 3), pbc=True))
    assert widget._view_selector.isHidden()
    assert widget.host_heading.isHidden()
    assert widget._host_info.isHidden()
    assert widget.cluster_radio.isChecked()
    assert widget.preview.projection.currentText() == "3D"
    assert len(widget.preview._positions) == 1
    widget.close()


def test_guided_scf_dialog_displays_structure_type(application):
    source = Atoms("Fe", cell=(3, 3, 3), pbc=True)
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"),
                                        atoms=source)
    assert dialog.structure_type_label.text() == "Structure type: Bulk (3D)"
    dialog.close()

    without_structure = GuidedInputParametersDialog(
        "scf", InputParameters.create("scf"),
    )
    assert without_structure.structure_type_label is None
    without_structure.close()
