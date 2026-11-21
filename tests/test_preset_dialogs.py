"""Guided and Expert share the YAML input preset workflow."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from ase2sprkkr import InputParameters
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog


def test_expert_has_preset_buttons(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows

    monkeypatch.setattr(preset_flows, "PresetStore", lambda: PresetStore(tmp_path))
    app = QApplication.instance() or QApplication([])
    dialog = InputParametersDialog(InputParameters.for_task("DOS"))
    assert dialog.load_preset_btn.text() == "Replace by preset"
    assert dialog.merge_preset_btn.text() == "Load preset"
    assert dialog.save_preset_btn.text() == "Save as preset…"
    assert not dialog.load_preset_btn.isEnabled()
    assert not dialog.merge_preset_btn.isEnabled()


def test_guided_has_preset_menu(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows

    monkeypatch.setattr(preset_flows, "PresetStore", lambda: PresetStore(tmp_path))
    app = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog("dos", InputParameters.for_task("DOS"))
    assert dialog.presets_btn.text() == "Presets…"
    assert [a.text() for a in dialog.presets_menu.actions()] == [
        "Replace by preset", "Load preset", "Save as preset…",
    ]
    assert not dialog.replace_preset_menu.menuAction().isEnabled()
    assert not dialog.merge_preset_menu.menuAction().isEnabled()
    assert dialog.presets_menu.actions()[-1].isEnabled()


def test_replace_preset_resets_settings_but_preserves_dataset(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("DOS")
    source.ENERGY.NE.set(402)
    source.CONTROL.DATASET.set("from_preset")
    source.save_preset("preset_1", store=store)

    original = InputParameters.for_task("DOS")
    original.ENERGY.NE.set(422)
    original.TAU.NKTAB.set(777)
    original.CONTROL.DATASET.set("my_dataset")
    session = InputParametersSession(original)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    assert preset_flows.load_preset(session, None, name="preset_1")
    result = session.result()
    assert int(result.ENERGY.NE()[0]) == 402
    assert result.TAU.NKTAB() != 777
    assert str(result.CONTROL.DATASET()) == "my_dataset"
    assert session.undo_stack.count() == 1
    session.undo_stack.undo()
    undone = session.result()
    assert int(undone.ENERGY.NE()[0]) == 422
    assert undone.TAU.NKTAB() == 777
    assert str(undone.CONTROL.DATASET()) == "my_dataset"


def test_merge_preset_keeps_unmentioned_settings(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("DOS")
    source.ENERGY.NE.set(451)
    source.save_preset("mesh", store=store)
    original = InputParameters.for_task("DOS")
    original.TAU.NKTAB.set(711)
    session = InputParametersSession(original)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    assert preset_flows.load_preset(session, None, name="mesh", clear_first=False)
    assert int(session.result().ENERGY.NE()[0]) == 451
    assert session.result().TAU.NKTAB() == 711
    assert session.undo_stack.count() == 1
    session.undo_stack.undo()
    assert session.result().TAU.NKTAB() == 711
    assert int(session.result().ENERGY.NE()[0]) != 451


def test_save_preset_does_not_change_editor_history(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    original = InputParameters.for_task("DOS")
    original.ENERGY.NE.set(471)
    session = InputParametersSession(original)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *_args, **_kwargs: ("saved", True))

    assert preset_flows.save_preset(session, None)
    assert (tmp_path / "input_parameters" / "dos" / "saved.yaml").is_file()
    assert session.undo_stack.count() == 0
    assert not session.is_modified()


def test_merge_and_resave_preserves_explicit_false_at_default(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("DOS")
    source.CONTROL.NOSYM = False
    source.save_preset("with_symmetry", store=store)
    session = InputParametersSession(InputParameters.for_task("DOS"))
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    assert preset_flows.load_preset(session, None, name="with_symmetry", clear_first=False)
    assert session.result().CONTROL.NOSYM.is_set()
    session.undo_stack.undo()
    assert not session.result().CONTROL.NOSYM.is_set()
    session.undo_stack.redo()
    session.result().save_preset("resaved", store=store)
    target = InputParameters.for_task("DOS")
    target.CONTROL.NOSYM = True
    target.load_preset("resaved", clear_first=False, store=store)
    assert target.CONTROL.NOSYM() is False


def test_guided_bsf_preset_can_switch_task_on_replace(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("BSFEK")
    source.ENERGY.NE.set([270])
    source.save_preset("task:bsfek.ek_mesh", store=store)
    original = InputParameters.for_task("BSFKK")
    session = InputParametersSession(original)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    assert preset_flows.load_preset(
        session, None, name="task:bsfek.ek_mesh",
        compatible_tasks=("bsfek", "bsfkk"),
    )
    assert session.result().task_name == "BSFEK"
    assert session.undo_stack.count() == 1
    session.undo_stack.undo()
    assert session.result().task_name == "BSFKK"


def test_expert_schema_editor_discovers_both_bsf_tasks(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    ek = InputParameters.for_task("BSFEK")
    ek.ENERGY.NE.set([250])
    ek.save_preset("task:bsfek.ek", store=store)
    kk = InputParameters.for_task("BSFKK")
    kk.ENERGY.NE.set([1])
    kk.save_preset("task:bsfkk.kk", store=store)
    original = InputParameters.for_definition("BSF")
    original.ENERGY.NE.set([2])
    session = InputParametersSession(original)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    names = preset_flows.available_presets(session)
    assert "task:bsfek.ek" in names
    assert "task:bsfkk.kk" in names
    assert preset_flows.load_preset(session, None, name="task:bsfkk.kk")
    assert session.result().task_name == "BSFKK"
    session.undo_stack.undo()
    assert session.result().task_name == "BSFEK"


def test_guided_hides_task_presets_outside_supported_family(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows
    from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("BSFEK")
    source.ENERGY.NE.set([220])
    source.save_preset("task:bsfek.ek", store=store)
    session = InputParametersSession(InputParameters.for_task("BSFKK"))
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)

    assert preset_flows.available_presets(
        session, compatible_tasks=("bsfkk",),
    ) == ()
    assert session.undo_stack.count() == 0



def test_expert_buttons_dispatch_replace_and_merge(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("DOS")
    source.ENERGY.NE.set([251])
    source.save_preset("mesh", store=store)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    dialog = InputParametersDialog(InputParameters.for_task("DOS"))
    selections = []
    monkeypatch.setattr(dialog, "_commit_pending", lambda: True)
    monkeypatch.setattr(
        preset_flows, "load_preset",
        lambda _session, _parent, **options: selections.append(
            (options["name"], options["clear_first"])
        ) or True,
    )
    assert dialog.load_preset_btn.isEnabled()
    assert dialog.merge_preset_btn.isEnabled()
    dialog.replace_preset_menu.actions()[0].trigger()
    dialog.merge_preset_menu.actions()[0].trigger()
    assert selections == [
        ("input_parameters:dos.mesh", True),
        ("input_parameters:dos.mesh", False),
    ]


def test_guided_menu_dispatches_replace_and_merge(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    source = InputParameters.for_task("DOS")
    source.ENERGY.NE.set([252])
    source.save_preset("mesh", store=store)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    dialog = GuidedInputParametersDialog("dos", InputParameters.for_task("DOS"))
    selections = []
    monkeypatch.setattr(dialog, "_commit_pending", lambda: True)
    monkeypatch.setattr(
        preset_flows, "load_preset",
        lambda _session, _parent, **options: selections.append(
            (options["name"], options["clear_first"])
        ) or True,
    )
    assert [action.text() for action in dialog.replace_preset_menu.actions()] == [
        "mesh"
    ]
    dialog.replace_preset_menu.actions()[0].trigger()
    dialog.merge_preset_menu.actions()[0].trigger()
    assert selections == [
        ("input_parameters:dos.mesh", True),
        ("input_parameters:dos.mesh", False),
    ]


def test_multiple_presets_and_incompatible_merge_action(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    for task, name, ne in (("BSFEK", "ek", 250), ("BSFKK", "kk", 1)):
        source = InputParameters.for_task(task)
        source.ENERGY.NE.set([ne])
        source.save_preset(f"task:{task.lower()}.{name}", store=store)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)

    dialog = GuidedInputParametersDialog("bsf", InputParameters.for_task("BSFEK"))
    replace = dialog.replace_preset_menu.actions()
    merge = dialog.merge_preset_menu.actions()
    assert [action.data() for action in replace] == [
        "task:bsfek.ek", "task:bsfkk.kk",
    ]
    assert all(action.isEnabled() for action in replace)
    assert merge[0].isEnabled()
    assert not merge[1].isEnabled()
    assert "use Replace by preset" in merge[1].toolTip()


def test_preset_save_refreshes_choices(tmp_path, monkeypatch):
    from ase2sprkkr.input_parameters.presets import PresetStore
    from ase2sprkkr_gui.gui.flows import presets as preset_flows

    app = QApplication.instance() or QApplication([])
    store = PresetStore(tmp_path)
    monkeypatch.setattr(preset_flows, "PresetStore", lambda: store)
    dialog = InputParametersDialog(InputParameters.for_task("DOS"))
    assert not dialog.load_preset_btn.isEnabled()
    source = InputParameters.for_task("DOS")
    source.ENERGY.NE.set([255])
    source.save_preset("saved", store=store)
    dialog._refresh_preset_menus()
    assert dialog.load_preset_btn.isEnabled()
    assert dialog.merge_preset_btn.isEnabled()
    assert dialog.replace_preset_menu.actions()[0].data() == (
        "input_parameters:dos.saved"
    )


def test_preset_labels_omit_redundant_arpes_scope():
    from ase2sprkkr_gui.gui.flows.presets import preset_labels

    names = (
        "input_parameters:arpes.default",
        "input_parameters:arpes.high_resolution",
    )
    assert preset_labels(names) == {
        "input_parameters:arpes.default": "default",
        "input_parameters:arpes.high_resolution": "high_resolution",
    }


def test_preset_labels_distinguish_multiple_tasks_and_scopes():
    from ase2sprkkr_gui.gui.flows.presets import preset_labels

    names = (
        "input_parameters:bsf.mesh",
        "task:bsfek.mesh",
        "task:bsfkk.mesh",
    )
    assert preset_labels(names) == {
        "input_parameters:bsf.mesh": "mesh (BSF input parameters)",
        "task:bsfek.mesh": "mesh (BSFEK task)",
        "task:bsfkk.mesh": "mesh (BSFKK task)",
    }
    same_task = ("input_parameters:arpes.mesh", "task:arpes.mesh")
    assert preset_labels(same_task) == {
        "input_parameters:arpes.mesh": "mesh (input parameters)",
        "task:arpes.mesh": "mesh (task)",
    }


def test_preset_labels_single_task_scope_stays_short():
    from ase2sprkkr_gui.gui.flows.presets import preset_labels

    names = ("task:arpes.default", "task:arpes.high_resolution")
    assert preset_labels(names) == {
        "task:arpes.default": "default",
        "task:arpes.high_resolution": "high_resolution",
    }
