"""Transactional Structure Editor and its conditional pages."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import numpy as np
from ase import Atoms
from PyQt6.QtWidgets import QApplication

from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs.structures import structure_editor as editor_module
from ase2sprkkr_gui.gui.flows import structures as structure_flows


def _atoms():
    atoms = Atoms(
        "Fe2", scaled_positions=((0, 0, 0), (0.5, 0.5, 0.5)),
        cell=np.eye(3), pbc=True,
    )
    atoms.set_array("spacegroup_kinds", np.array([0, 0]))
    atoms.set_array("labels", np.array(["a.1", "a.2"], dtype=object))
    atoms.info["occupancy"] = {"0": {"Fe": 1.0}}
    return atoms


def _cluster():
    host = Atoms("Fe2", positions=[[0, 0, 0], [1, 1, 1]],
                 cell=[2, 2, 4], pbc=True)
    atoms = SPRKKRAtoms.from_embedding(
        host, [(0, (0, 0, 0), "Co"), (1, (1, 0, 0), "Ni")]
    )
    atoms.sites[0].embedding.displacement = (0.04, -0.01, 0.02)
    return atoms


def _dialog(atoms=None, **kwargs):
    _app = QApplication.instance() or QApplication([])
    return editor_module.StructureEditorDialog(
        _atoms() if atoms is None else atoms, **kwargs
    )


def test_overview_first_and_advanced_removed_with_shared_preview():
    dialog = _dialog()
    assert dialog.windowTitle() == "Structure Editor"
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "Overview", "Sites", "Lattice", "Transform"
    ]
    assert dialog.tabs.currentIndex() == 0
    assert dialog.overview.site_table.rowCount() == 2
    assert not dialog.tabs.tabIcon(0).isNull()
    assert dialog.tabs.iconSize().width() >= 20
    assert dialog.editor_splitter.widget(1).isAncestorOf(dialog.canvas)
    assert not hasattr(dialog, "splitter")
    dialog.close()


def test_embedded_tab_reuses_guided_embedding_icon():
    from PyQt6.QtGui import QIcon
    from ase2sprkkr_gui.gui.misc.resources import icon_path

    dialog = _dialog(_cluster())
    index = dialog._embedded_index()
    assert index >= 0
    expected = QIcon(str(icon_path("bulk_crystal.png")))
    assert not expected.isNull()
    size = dialog.tabs.iconSize()
    assert dialog.tabs.tabIcon(index).pixmap(size).toImage() == (
        expected.pixmap(size).toImage()
    )
    dialog.close()


def test_editor_page_hints_live_in_shared_footer():
    dialog = _dialog(_cluster())
    action_row = dialog.layout().itemAt(dialog.layout().count() - 1).layout()
    assert action_row.indexOf(dialog.footer_hint) >= 0
    dialog.tabs.setCurrentWidget(dialog._sites_page)
    assert "host sites and occupations" in dialog.footer_hint.text()
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    assert "HOST POTENTIAL lattice" in dialog.footer_hint.text()
    assert dialog._lattice_page.layout().itemAt(0).widget() is dialog.lattice_group
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    assert "Select a repeated host cell" in dialog.footer_hint.text()
    dialog.tabs.setCurrentWidget(dialog.overview)
    assert dialog.footer_hint.text() == ""
    dialog.close()


def test_build_derived_in_transform_not_advanced():
    dialog = _dialog()
    dialog.tabs.setCurrentIndex(3)
    assert not dialog.derived_group.isHidden()
    assert dialog.build_surface_button.isEnabled() is False  # no recent files
    assert dialog.build_2d_button.isEnabled() is False
    assert dialog.embedding_button.isEnabled() is False  # capability not passed
    dialog.close()


def test_noop_and_cancel_do_not_modify_source():
    source = _atoms()
    dialog = _dialog(source)
    dialog._on_ok()
    assert dialog._result is None
    dialog.close()
    dialog = _dialog(source)
    dialog._draft.split_site(dialog._draft.sites[0])
    # This test isolates cancellation from the interactive close confirmation.
    editor_module.QDialog.reject(dialog)
    assert source.info["occupancy"] == {"0": {"Fe": 1.0}}
    np.testing.assert_array_equal(source.get_array("spacegroup_kinds"), [0, 0])
    dialog.close()


def test_site_and_lattice_edits_commit_together():
    source = _atoms()
    dialog = _dialog(source)
    dialog._letter_widgets[0].break_btn.click()
    dialog.tabs.setCurrentIndex(2)
    dialog.lattice_spinboxes[0][0].setValue(2.0)
    dialog._on_ok()
    result = dialog._result
    assert result is not None and result is not source
    np.testing.assert_allclose(result.cell[0, 0], 2.0)
    np.testing.assert_array_equal(result.get_array("spacegroup_kinds"), [0, 1])
    np.testing.assert_allclose(source.cell[0, 0], 1.0)
    dialog.close()


def test_transform_uses_staged_edit_and_no_early_publication(monkeypatch):
    source = _atoms()
    seen = []
    def scale(candidate, *, parent=None):
        seen.append(candidate)
        np.testing.assert_allclose(candidate.cell[0, 0], 2.0)
        out = candidate.copy()
        out.set_cell([3, 1, 1], scale_atoms=True)
        return out
    monkeypatch.setattr(editor_module, "scale_atoms", scale)
    dialog = _dialog(source)
    dialog.lattice_spinboxes[0][0].setValue(2.0)
    dialog.scale_button.click()
    assert len(seen) == 1
    np.testing.assert_allclose(dialog._draft.cell[0, 0], 3.0)
    np.testing.assert_allclose(source.cell[0, 0], 1.0)
    dialog._on_ok()
    np.testing.assert_allclose(dialog._result.cell[0, 0], 3.0)
    dialog.close()


def test_cancel_transform_keeps_staged_lattice_edit(monkeypatch):
    monkeypatch.setattr(editor_module, "scale_atoms", lambda atoms, parent=None: None)
    dialog = _dialog()
    dialog.lattice_spinboxes[0][0].setValue(2.0)
    dialog.scale_button.click()
    np.testing.assert_allclose(dialog._draft.cell[0, 0], 2.0)
    editor_module.QDialog.reject(dialog)


def test_embedded_page_edits_host_and_hides_shared_preview():
    atoms = _cluster()
    dialog = _dialog(atoms, allow_build_embedding=True)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "Overview", "Embedded", "Sites", "Lattice", "Transform"
    ]
    assert dialog.tabs.currentIndex() == 0
    assert dialog.scroll.isEnabled()
    assert dialog.lattice_spinboxes[0][0].isEnabled()
    assert dialog.scale_button.isEnabled()
    assert dialog.repeat_button.isEnabled()
    assert not dialog.rotate_button.isEnabled()
    assert all(not row.break_btn.isEnabled() for row in dialog._letter_widgets)
    assert dialog._embedded_editor is not None
    dialog.tabs.setCurrentIndex(1)
    assert dialog.preview_stack.isHidden()
    dialog.tabs.setCurrentIndex(0)
    assert not dialog.preview_stack.isHidden()
    assert dialog.preview_stack.currentWidget() is dialog._overview_previews
    assert dialog._shared_preview.isHidden()
    dialog.close()


def test_discard_cluster_is_a_transform_and_retains_host(monkeypatch):
    cluster = _cluster()
    host = cluster.embedding_host
    dialog = _dialog(cluster)
    assert dialog.discard_cluster_button.property("workflowActionTitle") == "Discard cluster"
    assert dialog.cluster_actions.title() == "Embedded cluster"
    assert not dialog.cluster_actions.isHidden()
    assert not hasattr(dialog, "apply_cluster_button")
    assert not dialog._embedded_page.isAncestorOf(dialog.discard_cluster_button)
    dialog.tabs.setCurrentWidget(dialog._transform_page)
    monkeypatch.setattr(
        editor_module.QMessageBox, "question",
        lambda *_args, **_kwargs: editor_module.QMessageBox.StandardButton.Yes,
    )
    dialog.discard_cluster_button.click()
    assert dialog._working_atoms is host
    assert dialog.tabs.currentWidget() is dialog.overview
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "Overview", "Sites", "Lattice", "Transform"
    ]
    assert dialog.cluster_actions.isHidden()
    assert dialog._result is None
    assert "sprkkr_embedding" in cluster.arrays
    editor_module.QDialog.reject(dialog)


def test_discard_cluster_retains_native_host_potential(monkeypatch):
    from ase2sprkkr.potentials.potential_base import Potential

    cluster = _cluster()
    host = Potential.from_atoms(cluster.embedding_host)
    host.SCF_INFO.SCFSTATUS = "CONVERGED"
    cluster.embedding_host = host
    dialog = _dialog(cluster)
    monkeypatch.setattr(
        editor_module.QMessageBox, "question",
        lambda *_args, **_kwargs: editor_module.QMessageBox.StandardButton.Yes,
    )
    dialog.discard_cluster_button.click()
    assert host.SCF_INFO.SCFSTATUS() == "CONVERGED"
    assert cluster.embedding_host is host
    dialog._on_ok()
    assert dialog._result is host.atoms
    assert dialog._result.potential is host
    assert host.SCF_INFO.SCFSTATUS() == "CONVERGED"
    dialog.close()


def test_navigation_preserves_embedded_draft_and_undo(monkeypatch):
    cluster = _cluster()
    dialog = _dialog(cluster)
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    embedded = dialog._embedded_editor
    undo_stack = embedded.undo_stack
    site = next(iter(embedded.draft.entries))
    assert undo_stack.apply(
        lambda: embedded.draft.set_occupation([site], {"Fe": 1.0}),
        "Change cluster occupation",
    )
    assert embedded.has_unapplied_changes()
    saved_index = undo_stack.index()
    monkeypatch.setattr(
        dialog, "_confirm_close_changes",
        lambda: (_ for _ in ()).throw(AssertionError("navigation must not prompt")),
    )
    for destination in (dialog.overview, dialog._sites_page,
                        dialog._lattice_page, dialog._embedded_page):
        dialog.tabs.setCurrentWidget(destination)
        assert dialog._embedded_editor is embedded
        assert embedded.undo_stack is undo_stack
        assert undo_stack.index() == saved_index
    assert dialog._working_atoms is cluster
    assert dialog._result is None
    assert "Fe" in dialog._candidate().sites[0].occupation.to_dict(True)
    undo_stack.undo()
    assert embedded.draft.is_unchanged()
    assert not dialog._has_unapplied_changes()
    editor_module.QDialog.reject(dialog)


def test_navigation_with_incomplete_cluster_field_stays_editable(monkeypatch):
    dialog = _dialog(_cluster())
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    embedded = dialog._embedded_editor
    monkeypatch.setattr(embedded, "_unfinished_numbers", lambda: [object()])
    monkeypatch.setattr(
        dialog, "_confirm_close_changes",
        lambda: (_ for _ in ()).throw(AssertionError("navigation must not prompt")),
    )
    dialog.tabs.setCurrentWidget(dialog.overview)
    assert dialog.tabs.currentWidget() is dialog.overview
    assert dialog._embedded_editor is embedded
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    assert dialog._embedded_editor is embedded
    editor_module.QDialog.reject(dialog)


def test_final_apply_blocks_incomplete_embedded_values(monkeypatch):
    dialog = _dialog(_cluster())
    embedded = dialog._embedded_editor
    monkeypatch.setattr(embedded, "_unfinished_numbers", lambda: [object()])
    warnings = []
    monkeypatch.setattr(
        editor_module.QMessageBox, "warning",
        lambda _parent, title, message, *_args, **_kwargs:
            warnings.append((title, message)),
    )
    dialog._on_ok()
    assert dialog._result is None
    assert any("Incomplete Cluster Edit" == title for title, _ in warnings)
    assert dialog._embedded_editor is embedded
    editor_module.QDialog.reject(dialog)


def test_embedded_host_preview_tracks_lattice_and_preserves_undo():
    cluster = _cluster()
    dialog = _dialog(cluster)
    widget = dialog._embedded_editor
    initial_host = widget.draft.host
    saved_undo = widget.undo_stack
    saved_center = widget.draft.center
    site = next(iter(widget.draft.entries))
    assert saved_undo.apply(
        lambda: widget.draft.set_occupation([site], {"Fe": 1.0}),
        "Edit occupation",
    )
    index = saved_undo.index()
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(4.0)
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    assert dialog._embedded_editor is widget
    assert widget.undo_stack is saved_undo
    assert saved_undo.index() == index
    assert widget.draft.center == saved_center
    assert widget.draft.host is initial_host
    assert widget.draft.geometry_host is not initial_host
    np.testing.assert_allclose(widget.draft.geometry_host.cell[0, 0], 4)
    np.testing.assert_allclose(cluster.embedding_host.cell[0, 0], 2)
    assert widget.draft.entries[site].occupation == {"Fe": 1.0}
    saved_undo.undo()
    assert widget.draft.is_unchanged()
    saved_undo.redo()
    assert widget.draft.entries[site].occupation == {"Fe": 1.0}
    editor_module.QDialog.reject(dialog)


def test_embedded_live_displacements_match_final_host_rebase():
    cluster = _cluster()
    dialog = _dialog(cluster)
    widget = dialog._embedded_editor
    site = next(iter(widget.draft.entries))
    original = widget.draft.entries[site].displacement.copy()
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(4.0)
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    expected = original @ np.diag([2.0, 1.0, 1.0])
    np.testing.assert_allclose(widget.draft.display_displacement(original), expected)
    widget._render_local()
    index = widget._local_sites.index(site)
    np.testing.assert_allclose(
        widget.local_preview._positions[index],
        site.position(widget.draft.geometry_host) + expected,
    )
    new_displayed = expected + [0.02, 0.0, 0.0]
    widget.draft.set_displacement([site], new_displayed)
    np.testing.assert_allclose(
        widget.draft.display_displacement(widget.draft.entries[site].displacement),
        new_displayed,
    )
    dialog._on_ok()
    np.testing.assert_allclose(
        dialog._result.sites[0].embedding.displacement, new_displayed,
    )
    np.testing.assert_allclose(cluster.sites[0].embedding.displacement, original)
    dialog.close()


def test_embedded_geometry_returns_to_original_when_host_edit_is_reverted():
    dialog = _dialog(_cluster())
    widget = dialog._embedded_editor
    old_host = widget.draft.host
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(4.0)
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    assert widget.draft.geometry_host is not old_host
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(2.0)
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    assert widget.draft.geometry_host is old_host
    assert not dialog._has_unapplied_changes()
    editor_module.QDialog.reject(dialog)


def test_embedded_preview_uses_uncommitted_host_occupations():
    cluster = _cluster()
    dialog = _dialog(cluster)
    widget = dialog._embedded_editor
    host = widget.draft.host
    first = dialog._require_draft().sites[0]
    first.occupancies[0].symbol = "Ni"
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    assert widget.draft.geometry_host is not host
    site = next(s for s in widget._site_rows if s.original_site == 0)
    assert "Ni" in widget.sites.item(widget._site_rows.index(site), 1).text()
    assert host[0].symbol == "Fe"
    editor_module.QDialog.reject(dialog)


def test_host_and_embedded_changes_are_composed_at_final_apply():
    cluster = _cluster()
    original_positions = cluster.positions.copy()
    original_host_cell = cluster.embedding_host.cell.copy()
    dialog = _dialog(cluster)
    site = next(iter(dialog._embedded_editor.draft.entries))
    dialog._embedded_editor.draft.set_occupation([site], {"Fe": 1.0})
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(4.0)
    assert dialog._embedded_editor.has_unapplied_changes()
    preview = dialog._candidate()
    assert "Fe" in preview.sites[0].occupation.to_dict(True)
    np.testing.assert_allclose(preview.embedding_host.cell[0, 0], 4.0)
    assert dialog._working_atoms is cluster
    assert dialog._result is None
    np.testing.assert_allclose(cluster.positions, original_positions)
    np.testing.assert_array_equal(cluster.embedding_host.cell, original_host_cell)
    dialog._on_ok()
    assert dialog._result is not None
    assert "Fe" in dialog._result.sites[0].occupation.to_dict(True)
    np.testing.assert_allclose(dialog._result.embedding_host.cell[0, 0], 4.0)
    dialog.close()


def test_discard_cluster_keeps_pending_host_geometry(monkeypatch):
    cluster = _cluster()
    old_host = cluster.embedding_host
    dialog = _dialog(cluster)
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(4.0)
    monkeypatch.setattr(
        editor_module.QMessageBox, "question",
        lambda *_args, **_kwargs: editor_module.QMessageBox.StandardButton.Yes,
    )
    dialog.discard_cluster_button.click()
    assert dialog.tabs.currentWidget() is dialog.overview
    assert dialog._embedded_editor is None
    np.testing.assert_allclose(dialog._working_atoms.cell[0, 0], 4.0)
    np.testing.assert_allclose(old_host.cell[0, 0], 2.0)
    dialog._on_ok()
    assert dialog._result is not None
    np.testing.assert_allclose(dialog._result.cell[0, 0], 4.0)
    dialog.close()


def test_host_edit_after_cluster_discard_is_checked_on_final_apply(monkeypatch):
    from ase2sprkkr.potentials.potential_base import Potential

    cluster = _cluster()
    host = Potential.from_atoms(cluster.embedding_host)
    host.SCF_INFO.SCFSTATUS = "CONVERGED"
    cluster.embedding_host = host
    dialog = _dialog(cluster)
    monkeypatch.setattr(
        editor_module.QMessageBox, "question",
        lambda *_args, **_kwargs: editor_module.QMessageBox.StandardButton.Yes,
    )
    dialog.discard_cluster_button.click()
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    dialog.lattice_spinboxes[0][0].setValue(3.5)
    warnings = []
    def confirm(_parent, title, message, *_args, **_kwargs):
        warnings.append((title, message))
        return editor_module.QMessageBox.StandardButton.Yes
    monkeypatch.setattr(editor_module.QMessageBox, "warning", confirm)
    dialog._on_ok()
    assert any(title == "Host Transformation Invalidates SCF"
               for title, _ in warnings)
    np.testing.assert_allclose(dialog._result.cell[0, 0], 3.5)
    assert host.SCF_INFO.SCFSTATUS() == "CONVERGED"
    dialog.close()


def test_close_prompts_only_once_for_entire_editor(monkeypatch):
    cluster = _cluster()
    dialog = _dialog(cluster)
    embedded = dialog._embedded_editor
    site = next(iter(embedded.draft.entries))
    embedded.draft.set_occupation([site], {"Fe": 1.0})
    outcomes = []
    def choose():
        outcomes.append("called")
        return "continue"
    monkeypatch.setattr(dialog, "_confirm_close_changes", choose)
    dialog.show()
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    dialog.tabs.setCurrentWidget(dialog.overview)
    dialog.tabs.setCurrentWidget(dialog._lattice_page)
    assert outcomes == []
    dialog.reject()
    assert outcomes == ["called"]
    assert dialog.isVisible()
    assert dialog._result is None
    monkeypatch.setattr(dialog, "_confirm_close_changes", lambda: "apply")
    dialog.reject()
    assert dialog.result() == editor_module.QDialog.DialogCode.Accepted
    assert dialog._result is not None
    assert "Fe" in dialog._result.sites[0].occupation.to_dict(True)
    assert "Co" in cluster.sites[0].occupation.to_dict(True)
    dialog.close()

    dialog = _dialog(_cluster())
    site = next(iter(dialog._embedded_editor.draft.entries))
    dialog._embedded_editor.draft.set_occupation([site], {"Fe": 1.0})
    monkeypatch.setattr(dialog, "_confirm_close_changes", lambda: "discard")
    dialog.reject()
    assert dialog.result() == editor_module.QDialog.DialogCode.Rejected
    assert dialog._result is None


def test_window_close_can_continue_editing_or_discard(monkeypatch):
    dialog = _dialog(_cluster())
    dialog.tabs.setCurrentWidget(dialog._embedded_page)
    site = next(iter(dialog._embedded_editor.draft.entries))
    dialog._embedded_editor.draft.set_occupation([site], {"Fe": 1.0})
    monkeypatch.setattr(dialog, "_confirm_close_changes", lambda: "continue")
    dialog.show()
    dialog.close()
    assert dialog.isVisible()
    assert dialog._embedded_editor.has_unapplied_changes()
    monkeypatch.setattr(dialog, "_confirm_close_changes", lambda: "discard")
    dialog.close()
    assert not dialog.isVisible()


def test_editing_host_lattice_rebases_cluster_displacement_without_touching_original():
    atoms = _cluster()
    original = atoms.positions.copy()
    dialog = _dialog(atoms)
    dialog.tabs.setCurrentIndex(3)
    dialog.lattice_spinboxes[0][0].setValue(4.0)
    candidate = dialog._candidate()
    assert candidate is not atoms
    assert candidate.embedding_host is not atoms.embedding_host
    np.testing.assert_allclose(candidate.sites[0].embedding.displacement,
                               [0.08, -0.01, 0.02])
    np.testing.assert_allclose(atoms.positions, original)
    dialog._on_ok()
    assert dialog._result is not None
    dialog.close()


def test_newly_built_embedded_structure_adds_and_selects_page():
    dialog = _dialog()
    cluster = _cluster()
    assert dialog._accept_operation_result(cluster, dialog._working_atoms)
    assert dialog.tabs.currentIndex() == 1
    assert dialog.tabs.tabText(1) == "Embedded"
    assert dialog._embedded_editor is not None
    editor_module.QDialog.reject(dialog)


def test_0d_transform_rejects_unknown_site_mapping():
    dialog = _dialog(_cluster())
    assert not dialog.rotate_button.isEnabled()
    assert "mapping" in dialog.rotate_button.toolTip()
    dialog.close()


def test_guided_edit_commits_accepted_result_once(monkeypatch):
    _app = QApplication.instance() or QApplication([])
    controller = WorkspaceController()
    source = _atoms()
    controller.replace_structure(source)
    accepted = source.copy()

    def select(atoms, parent=None, **kwargs):
        assert atoms is source
        assert kwargs["allow_build_2d"] == controller.can_build_2d()
        return accepted

    monkeypatch.setattr(editor_module, "select_structure_editor", select)
    assert structure_flows.edit_structure(controller, None)
    assert controller.atoms is accepted
    assert controller.atoms is not source


def test_guided_cancel_keeps_workspace_revision(monkeypatch):
    _app = QApplication.instance() or QApplication([])
    controller = WorkspaceController()
    source = _atoms()
    controller.replace_structure(source)
    generation = controller.structure_generation
    monkeypatch.setattr(editor_module, "select_structure_editor", lambda *_a, **_k: None)
    assert not structure_flows.edit_structure(controller, None)
    assert controller.atoms is source
    assert controller.structure_generation == generation



def test_overview_reports_hall_number_for_3d_and_left_right_bulk_for_2d():
    from ase.build import bulk
    from ase2sprkkr.sprkkr.build import semiinfinite_system
    dialog = _dialog()
    assert "Space group:" in dialog.overview.symmetry.text()
    assert "Hall symbol:" in dialog.overview.symmetry.text()
    assert "No." in dialog.overview.symmetry.text()
    dialog.close()

    slab = semiinfinite_system(bulk("Cu", "sc", a=2.0), (0, 0))
    dialog = _dialog(slab)
    assert not dialog.overview.bulk_boxes["left"][0].isHidden()
    assert not dialog.overview.bulk_boxes["right"][0].isHidden()
    left_text = dialog.overview.bulk_boxes["left"][1].text()
    right_text = dialog.overview.bulk_boxes["right"][1].text()
    assert "Space group:" in left_text
    assert "Space group:" in right_text
    assert "Hall symbol:" in left_text
    assert "Hall symbol:" in right_text
    dialog.close()



def test_lattice_inputs_have_uniform_compact_width_and_parameter_frame():
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFrame, QHeaderView

    dialog = _dialog()
    assert dialog.cell_parameter_frame.frameShape() == QFrame.Shape.StyledPanel
    assert dialog.cell_parameter_frame.parentWidget() is dialog.cell_parameter_group.content
    assert dialog.cell_parameter_group.content_layout.indexOf(
        dialog.cell_parameter_frame
    ) >= 0
    assert dialog.lattice_group.title() == "Lattice vectors (Å)"
    assert dialog.cell_parameter_group.title() == "Cell lengths and angles"
    assert dialog.lattice_group.maximumWidth() == dialog.cell_parameter_group.maximumWidth()
    widths = {spin.width() for spin in dialog.cell_parameter_spins.values()}
    assert len(widths) == 1
    (width,) = tuple(widths)
    assert 110 <= width <= 145
    table = dialog.lattice_vectors_table
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert header.minimumSectionSize() == 115
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    expected_height = (
        table.horizontalHeader().sizeHint().height()
        + table.verticalHeader().length()
        + 2 * table.frameWidth()
    )
    if table.horizontalScrollBar().maximum() > 0:
        expected_height += table.horizontalScrollBar().sizeHint().height()
    assert table.height() == expected_height
    grid = dialog.cell_parameter_grid
    assert grid.columnStretch(4) == 1
    for index in range(6):
        row, column = index % 3, 0 if index < 3 else 2
        assert grid.itemAtPosition(row, column + 1).alignment() == Qt.AlignmentFlag.AlignLeft
    dialog.show()
    QApplication.processEvents()
    assert dialog.lattice_group.width() == dialog.cell_parameter_group.width()
    expected_height = (
        table.horizontalHeader().sizeHint().height()
        + table.verticalHeader().length()
        + 2 * table.frameWidth()
    )
    if table.horizontalScrollBar().maximum() > 0:
        expected_height += table.horizontalScrollBar().sizeHint().height()
    assert table.height() == expected_height
    dialog.close()


def test_overview_uses_indented_aligned_two_column_facts():
    from PyQt6.QtWidgets import QBoxLayout
    from ase2sprkkr_gui.gui.widgets.structures.editor_overview import (
        _fact_columns, _fact_table,
    )

    dialog = _dialog(_cluster())
    overview = dialog.overview
    sections = (
        overview.info_box, overview.host_box, overview.table_box,
        *(box for box, _ in overview.bulk_boxes.values()),
    )
    assert all(section.content_layout.contentsMargins().left() == 14 for section in sections)
    dialog.show()
    QApplication.processEvents()
    expected_direction = (
        QBoxLayout.Direction.LeftToRight
        if overview.scroll.viewport().width() >= 720
        else QBoxLayout.Direction.TopToBottom
    )
    assert overview.info_columns.direction() == expected_direction
    assert overview.info_columns.spacing() == 40
    assert "Type:" in overview.main.text()
    assert "Cell (Å):" in overview.symmetry.text()
    assert "Cluster symmetry:" in overview.symmetry.text()
    assert "<table" in overview.host_facts.text()
    assert "Space group:" in overview.host_facts.text()
    summary, details = _fact_columns(
        "Type: 3D\nSites: 2\nCell (Å): a=2\nAngles (°): α=90",
        "Space group: Pm-3m",
    )
    assert summary == ["Type: 3D", "Sites: 2"]
    assert details == ["Cell (Å): a=2", "Angles (°): α=90", "Space group: Pm-3m"]
    assert _fact_table(summary, details).count("<tr>") == 3
    assert '<td width="36"></td>' in _fact_table(summary, details)
    assert _fact_table(["Elements: Fe < Co"]).count("&lt;") == 1
    dialog.close()


def test_info_headings_and_unframed_sites():
    from PyQt6.QtWidgets import QFrame

    dialog = _dialog()
    assert dialog.overview.info_box.title() == "Structure information"
    assert dialog.overview.table_box.title() == "Atomic sites"
    from PyQt6.QtWidgets import QGroupBox
    from ase2sprkkr_gui.gui.widgets.structures.editor_section import EditorSection

    sections = (
        dialog.overview.info_box,
        dialog.overview.host_box,
        dialog.overview.table_box,
        *(box for box, _label in dialog.overview.bulk_boxes.values()),
        dialog.lattice_group,
        dialog.cell_parameter_group,
        dialog.geometry_group,
        dialog.derived_group,
    )
    assert all(isinstance(section, EditorSection) for section in sections)
    assert all(not isinstance(section, QGroupBox) for section in sections)
    assert all(section.heading.font().bold() for section in sections)
    assert all(
        section.heading.font().pointSizeF() > dialog.font().pointSizeF()
        for section in sections
    )
    assert dialog.scroll.frameShape() == QFrame.Shape.NoFrame
    assert dialog.overview.site_table.horizontalHeader().count() == 9
    assert dialog.overview.site_table.horizontalHeaderItem(2).text() == "Color"
    assert not hasattr(dialog, "cell_summary")
    dialog.close()


def test_guided_style_transform_actions():
    dialog = _dialog()
    assert dialog.scale_button.property("workflowActionTitle") == "Scale lattice"
    assert dialog.repeat_button.property("workflowActionTitle") == "Repeat structure"
    assert dialog.rotate_button.property("workflowActionTitle") == (
        "Rotate structure (Miller indices)"
    )
    assert dialog.build_surface_button.property("workflowActionTitle") == "Create 2D surface"
    assert dialog.embedding_button.property("workflowActionTitle") == "Build embedded cluster"
    dialog.close()


def test_edit_lengths_angles_preserves_fractional_coordinates():
    from ase2sprkkr_gui.physics.cell_parameters import lengths_and_angles

    atoms = _atoms()
    original = atoms.get_scaled_positions(wrap=False).copy()
    dialog = _dialog(atoms)
    dialog.tabs.setCurrentIndex(2)
    dialog.cell_parameter_spins["a"].setValue(2.5)
    dialog.cell_parameter_spins["gamma"].setValue(106)
    result = dialog._candidate()
    np.testing.assert_allclose(
        result.get_scaled_positions(wrap=False), original, atol=1e-8,
    )
    np.testing.assert_allclose(
        lengths_and_angles(result.cell)[0], 2.5, atol=1e-5,
    )
    np.testing.assert_allclose(
        lengths_and_angles(result.cell)[5], 106, atol=1e-5,
    )
    assert not np.allclose(result.positions, atoms.positions)
    np.testing.assert_allclose(np.asarray(atoms.cell), np.eye(3))
    editor_module.QDialog.reject(dialog)


def test_lattice_host_potential_label_and_cell_parameters_rebase_cluster():
    from ase2sprkkr.sprkkr.embedding import host_atoms
    from ase2sprkkr_gui.physics.cell_parameters import lengths_and_angles

    cluster = _cluster()
    old_host = host_atoms(cluster.embedding_host)
    fractions = old_host.get_scaled_positions(wrap=False).copy()
    dialog = _dialog(cluster)
    dialog.tabs.setCurrentIndex(3)
    assert "HOST POTENTIAL" in dialog.lattice_note.text()
    assert "Host potential" in dialog.lattice_group.title()
    dialog.cell_parameter_spins["a"].setValue(3.25)
    candidate = dialog._candidate()
    new_host = host_atoms(candidate.embedding_host)
    np.testing.assert_allclose(
        new_host.get_scaled_positions(wrap=False), fractions, atol=1e-8,
    )
    np.testing.assert_allclose(
        lengths_and_angles(new_host.cell)[0], 3.25, atol=1e-5,
    )
    assert not np.allclose(new_host.positions, old_host.positions)
    assert not np.array_equal(candidate.positions, cluster.positions)
    np.testing.assert_allclose(
        np.asarray(old_host.cell), np.diag([2, 2, 4]),
    )
    editor_module.QDialog.reject(dialog)


def test_host_table_highlights_all_matching_cluster_atoms():
    host = Atoms(
        "Fe2", positions=[[0, 0, 0], [1, 1, 1]],
        cell=[2, 2, 4], pbc=True,
    )
    cluster = SPRKKRAtoms.from_embedding(
        host, [
            (0, (0, 0, 0), "Co"),
            (0, (1, 0, 0), "Co"),
            (1, (0, 0, 0), "Ni"),
        ],
    )
    dialog = _dialog(cluster)
    previews = dialog._overview_previews
    assert previews.splitter.count() == 2
    assert dialog.overview.site_table.rowCount() == 3

    # Cluster mode only highlights the selected atom.
    assert tuple(np.flatnonzero(previews.cluster_preview._widths > 1)) == (0,)
    dialog.overview.host_radio.setChecked(True)
    assert dialog.overview.site_table.rowCount() == 2
    assert tuple(np.flatnonzero(previews.cluster_preview._widths > 1)) == (0, 1)
    assert not np.any(previews.host_preview._widths > 1)

    dialog.overview.site_table.setCurrentCell(1, 0)
    assert tuple(np.flatnonzero(previews.cluster_preview._widths > 1)) == (2,)
    dialog.overview.cluster_radio.setChecked(True)
    dialog.overview.site_table.setCurrentCell(1, 0)
    assert tuple(np.flatnonzero(previews.cluster_preview._widths > 1)) == (1,)
    assert not np.any(previews.host_preview._widths > 1)
    dialog.close()


def test_info_color_by_species_switch_updates_table_and_preview():
    from ase.data.colors import jmol_colors
    from matplotlib.colors import to_hex

    atoms = _atoms()
    atoms.set_array("spacegroup_kinds", np.array([0, 1]))
    atoms.info["occupancy"] = {"0": {"Fe": 1.0}, "1": {"Fe": 1.0}}
    dialog = _dialog(atoms)
    overview = dialog.overview
    previews = dialog._overview_previews
    table = overview.site_table

    def swatch(row):
        return table.item(row, 2).background().color().name()

    assert overview.color_mode == "site_type"
    assert dialog.preview_stack.currentWidget() is previews
    assert previews.cluster_label.text() == "Structure"
    assert previews.host_page.isHidden()
    assert swatch(0) != swatch(1)
    assert list(previews.cluster_preview._colors) == [swatch(0), swatch(1)]

    table.setCurrentCell(1, 0)
    overview.color_by.setCurrentIndex(1)
    assert overview.color_mode == "species"
    assert table.currentRow() == 1
    expected = to_hex(jmol_colors[26])
    assert swatch(0) == swatch(1) == expected
    assert list(previews.cluster_preview._colors) == [expected, expected]

    dialog.tabs.setCurrentWidget(dialog._sites_page)
    dialog.tabs.setCurrentWidget(overview)
    assert overview.color_mode == "species"
    assert list(previews.cluster_preview._colors) == [expected, expected]
    dialog.close()


def test_cluster_host_color_legend_matches_both_previews():
    dialog = _dialog(_cluster())
    overview = dialog.overview
    previews = dialog._overview_previews
    table = overview.site_table

    def swatches():
        return [table.item(i, 2).background().color().name()
                for i in range(table.rowCount())]

    assert previews.cluster_label.text() == "Embedded cluster"
    assert not previews.host_page.isHidden()
    assert swatches() == list(previews.cluster_preview._colors)
    overview.host_radio.setChecked(True)
    assert swatches() == list(previews.host_preview._colors)
    overview.color_by.setCurrentIndex(1)
    assert swatches() == list(previews.host_preview._colors)
    overview.cluster_radio.setChecked(True)
    assert swatches() == list(previews.cluster_preview._colors)
    dialog.close()


def test_site_scope_radios_are_stacked_beside_table():
    from PyQt6.QtWidgets import QVBoxLayout

    dialog = _dialog(_cluster())
    overview = dialog.overview
    assert isinstance(overview.site_scope.layout(), QVBoxLayout)
    assert overview.site_scope.layout().itemAt(0).widget() is overview.cluster_radio
    assert overview.site_scope.layout().itemAt(1).widget() is overview.host_radio
    assert overview.table_row.itemAt(0).widget() is overview.site_table
    assert overview.table_row.itemAt(1).widget() is overview.site_scope
    assert overview.table_box.title() == "Atomic sites"
    dialog.close()


def test_cannot_make_lattice_vector_zero():
    dialog = _dialog()
    before = dialog._require_draft().cell.copy()
    # Initially the a vector is (1, 0, 0). The first component may not
    # be changed to zero, because that would make the entire vector zero.
    dialog.lattice_spinboxes[0][0].setValue(0.0)
    np.testing.assert_array_equal(dialog._require_draft().cell, before)
    assert dialog.lattice_spinboxes[0][0].value() == 1.0
    assert "zero length" in dialog.cell_parameter_error.text()
    dialog.close()


def test_loaded_zero_vector_can_be_repaired_without_crashing():
    atoms = _atoms()
    atoms.set_cell([[1, 0, 0], [0, 1, 0], [0, 0, 0]])
    atoms.set_pbc((True, True, False))
    dialog = _dialog(atoms)
    assert not dialog.cell_parameter_group.isEnabled()
    dialog.lattice_spinboxes[2][2].setValue(2.0)
    assert dialog.cell_parameter_group.isEnabled()
    assert not np.isclose(np.linalg.norm(dialog._require_draft().cell[2]), 0)
    editor_module.QDialog.reject(dialog)


def test_transform_action_cards_use_bundled_crystal_icons():
    """All four Transform actions render their bundled icons, including on clusters."""
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QLabel
    from ase2sprkkr_gui.gui.misc.resources import icon_path

    for atoms, icons in (
        (None, (
            ("scale_button", "scale_lattice.svg"),
            ("repeat_button", "repeat_structure.svg"),
            ("rotate_button", "rotate_structure.svg"),
        )),
        (_cluster(), (("discard_cluster_button", "discard_cluster.svg"),)),
    ):
        dialog = _dialog(atoms)
        try:
            for name, filename in icons:
                path = icon_path(filename)
                assert path.is_file(), filename
                expected = QIcon(str(path)).pixmap(26, 26)
                assert not expected.isNull(), filename
                icon_images = [
                    label.pixmap().toImage()
                    for label in getattr(dialog, name).findChildren(QLabel)
                    if label.pixmap() is not None and not label.pixmap().isNull()
                ]
                assert expected.toImage() in icon_images, name
        finally:
            dialog.close()
