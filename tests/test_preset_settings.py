"""Preset Settings UX: exact IPD/task scopes, create/copy/delete, and save modes."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox
from ase2sprkkr import InputParameters
from ase2sprkkr.input_parameters.presets import PresetStore
from ase2sprkkr_gui.gui.widgets.settings.presets import (
    PresetsSettingsPage, preset_scopes, scope_label,
)


def _app():
    return QApplication.instance() or QApplication([])


def _dos(store, name="input_parameters:dos.mesh", energy=311):
    parameters = InputParameters.for_task("DOS")
    parameters.ENERGY.NE.set(energy)
    parameters.save_preset(name, store=store)
    return parameters


def test_scope_labels_and_only_existing_namespaces_are_shown(tmp_path):
    _app()
    store = PresetStore(tmp_path)
    _dos(store)
    _dos(store, "task:dos.special", 355)
    assert preset_scopes(store.list()) == (
        "input_parameters:dos", "task:dos",
    )
    assert scope_label("input_parameters:dos") == "IPD  ·  DOS"
    assert scope_label("task:dos") == "Task  ·  DOS"

    page = PresetsSettingsPage(store=store)
    assert [page.scopes.item(row).text() for row in range(page.scopes.count())] == [
        "IPD  ·  DOS", "Task  ·  DOS",
    ]
    assert [page.presets.item(row).text() for row in range(page.presets.count())] == ["mesh"]
    assert page.add_button.isEnabled()
    assert page.copy_button.isEnabled()
    page.scopes.setCurrentRow(1)
    assert [page.presets.item(row).text() for row in range(page.presets.count())] == ["special"]
    page.scopes.setCurrentRow(-1)
    assert not page.details.isEnabled()
    assert not page.add_button.isEnabled()
    assert not page.copy_button.isEnabled()
    assert not page.remove_button.isEnabled()
    page.close()


def test_add_copy_and_choose_a_new_scope(tmp_path, monkeypatch):
    _app()
    store = PresetStore(tmp_path)
    _dos(store)
    page = PresetsSettingsPage(store=store)
    opened = []
    monkeypatch.setattr(
        page, "_open_editor",
        lambda scope, *, base_preset=None: opened.append((scope, base_preset)),
    )
    page.add_button.click()
    page.copy_button.click()
    assert opened == [
        ("input_parameters:dos", None),
        ("input_parameters:dos", "input_parameters:dos.mesh"),
    ]
    choices = dict(page._scope_choices())
    assert "IPD  ·  ARPES" in choices
    assert "Task  ·  DOS" in choices
    monkeypatch.setattr(
        QInputDialog, "getItem",
        lambda *_args, **_kwargs: ("IPD  ·  ARPES", True),
    )
    page.new_scope_button.click()
    assert opened[-1] == ("input_parameters:arpes", None)
    page.close()


def test_save_rejects_colliding_name_and_keeps_both_presets(tmp_path, monkeypatch):
    _app()
    store = PresetStore(tmp_path)
    source = _dos(store)
    page = PresetsSettingsPage(store=store)
    prompts = iter([("mesh", True), ("mesh_copy", True)])
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *_args, **_kwargs: next(prompts),
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *_args, **_kwargs: warnings.append(True),
    )
    assert page._save_named_preset("input_parameters:dos", source)
    assert set(store.list()) == {
        "input_parameters:dos.mesh",
        "input_parameters:dos.mesh_copy",
    }
    assert warnings
    assert page._current_preset() == "input_parameters:dos.mesh_copy"
    assert page._copy_suggestion("input_parameters:dos.mesh") == "mesh_copy2"
    page.close()


def test_cancel_preset_name_keeps_editor_open(tmp_path, monkeypatch):
    _app()
    page = PresetsSettingsPage(store=PresetStore(tmp_path))
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *_args, **_kwargs: ("", False),
    )
    assert not page._save_named_preset(
        "input_parameters:dos", InputParameters.for_task("DOS"),
    )
    assert page._store.list() == ()
    page.close()


def test_remove_confirmed_preset_and_drop_last_scope(tmp_path, monkeypatch):
    _app()
    store = PresetStore(tmp_path)
    _dos(store)
    page = PresetsSettingsPage(store=store)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page.remove_button.click()
    assert store.list() == ()
    assert page.scopes.count() == 0
    assert not page.details.isEnabled()
    page.close()


def test_guided_preset_save_does_not_require_calculation(tmp_path):
    _app()
    from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog

    saved = []
    dialog = GuidedInputParametersDialog(
        "dos", InputParameters.for_task("DOS"),
        preset_save=lambda params: saved.append(params) or True,
    )
    assert dialog.calculate_button.text() == "Save"
    assert dialog.calculate_button.objectName() == "guidedSavePreset"
    assert dialog.calculate_button.isEnabled()
    assert not dialog.presets_menu.actions()[-1].isVisible()
    dialog.calculate_button.click()
    assert len(saved) == 1
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_expert_preset_save_and_incomplete_nested_editing():
    _app()
    from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog

    saved = []
    dialog = InputParametersDialog(
        InputParameters.for_task("DOS"),
        preset_save=lambda params: saved.append(params) or True,
    )
    assert dialog.ok_btn.text() == "Save"
    assert not dialog.save_preset_btn.isVisible()
    dialog.ok_btn.click()
    assert len(saved) == 1
    assert dialog.result() == QDialog.DialogCode.Accepted

    nested = InputParametersDialog(
        InputParameters.for_task("DOS"), allow_incomplete=True,
    )
    nested.ok_btn.click()
    assert nested.result() == QDialog.DialogCode.Accepted
