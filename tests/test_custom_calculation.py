"""Standalone input and native-task chooser regressions."""
from __future__ import annotations

import os
from pathlib import Path
from shutil import copyfile
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from ase import Atoms
import ase2sprkkr
from ase2sprkkr import InputParameters
import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QTabWidget, QWidget

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.sprkkr_execution import SprkkrExecution
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs import expert_input
from ase2sprkkr_gui.gui.dialogs import task_chooser
from ase2sprkkr_gui.gui.dialogs.task_chooser import (
    TaskChoice, TaskChooserDialog, applicability, order_choices,
)
from ase2sprkkr_gui.gui.flows import custom_calculation as custom_flow
from ase2sprkkr_gui.gui.misc.modal_task import _ModalTaskDialog
from ase2sprkkr_gui.main import GuiApplication


def _app():
    return QApplication.instance() or QApplication([])


def _rows():
    return (
        TaskChoice("A", False, "Yes", "Ordinary"),
        TaskChoice("Z", True, "Yes", "Experimental"),
        TaskChoice("B", True, "No", "Unsupported", "Task not supported"),
        TaskChoice("C", False, "Unknown", "Unverified", "Support unverified"),
    )


def _names(table):
    name_col = next(
        i for i in range(table.columnCount())
        if table.horizontalHeaderItem(i).text() == "Name"
    )
    return [
        table.item(row, name_col).text() for row in range(table.rowCount())
    ]


def test_default_sort_then_column_primary_keeps_other_tie_breakers():
    assert [row.name for row in order_choices(_rows())] == ["A", "Z", "B", "C"]
    assert [row.name for row in order_choices(_rows(), primary="name")] == [
        "A", "B", "C", "Z"
    ]
    assert [row.name for row in order_choices(
        _rows(), primary="name", descending=True
    )] == ["Z", "C", "B", "A"]
    assert [row.name for row in order_choices(
        _rows(), has_structure=False
    )] == ["A", "C", "B", "Z"]

    # Experimental column: first click No/Yes, second click Yes/No.
    assert [row.name for row in order_choices(
        _rows(), primary="experimental", descending=True
    )] == ["A", "C", "Z", "B"]
    assert [row.name for row in order_choices(
        _rows(), primary="experimental", descending=False
    )] == ["Z", "B", "A", "C"]

    # Applicable, then non-experimental, then alphabetical name.
    mixed = (
        TaskChoice("Z", True, "Yes", ""),
        TaskChoice("C", False, "No", ""),
        TaskChoice("Y", False, "Yes", ""),
        TaskChoice("B", True, "No", ""),
        TaskChoice("A", False, "Yes", ""),
    )
    assert [row.name for row in order_choices(mixed)] == [
        "A", "Y", "Z", "C", "B"
    ]


def test_info_column_uses_short_summary_and_full_help_only_in_tooltip(monkeypatch):
    _app()
    task = SimpleNamespace(
        name="TEST", experimental=False, executable="kkrgen",
        supports={"3d"},
    )

    class Registry(dict):
        def names(self):
            return tuple(self)

    schema = SimpleNamespace(
        info="Short purpose of the calculation.",
        description="Long technical help about this calculation. More limitations.",
    )
    monkeypatch.setattr(task_chooser.InputParameters, "task_registry", Registry(TEST=task))
    monkeypatch.setattr(
        task_chooser.InputParameters, "input_parameters_registry",
        SimpleNamespace(definition_for_task=lambda _task: schema),
    )
    monkeypatch.setattr(task_chooser, "system_kind_for_atoms", lambda _atoms: "3d")

    chooser = TaskChooserDialog(object())
    info_col = chooser._fields.index("info")
    info_item = chooser.table.item(0, info_col)
    assert info_item.text() == schema.info
    assert info_item.toolTip() == schema.description
    chooser.search.setText("limitations")
    assert _names(chooser.table) == ["TEST"]
    chooser.close()


def test_info_falls_back_to_first_sentence_when_short_summary_is_missing(monkeypatch):
    task = SimpleNamespace(
        name="TEST", experimental=False, executable="kkrgen",
        supports={"3d"},
    )

    class Registry(dict):
        def names(self):
            return tuple(self)

    schema = SimpleNamespace(
        info="", description="An informative first sentence. Extended instructions.",
    )
    monkeypatch.setattr(task_chooser.InputParameters, "task_registry", Registry(TEST=task))
    monkeypatch.setattr(
        task_chooser.InputParameters, "input_parameters_registry",
        SimpleNamespace(definition_for_task=lambda _task: schema),
    )
    rows = task_chooser.task_choices()
    assert len(rows) == 1
    assert rows[0].info == "An informative first sentence."
    assert rows[0].details == schema.description


def test_applicability_is_not_conflated_with_execution_readiness():
    task = SimpleNamespace(name="TEST", executable="kkrgen", supports={"3d"})
    assert applicability(task, "cluster")[0] == "No"
    assert "free clusters" in applicability(task, "cluster")[1]
    assert applicability(task, "2d")[0] == "No"
    assert applicability(task, "3d")[0] == "Yes"

    task.supports = {"3d", "2d"}
    assert applicability(task, "2d")[0] == "Yes"
    task.supports = {"2d"}
    assert applicability(task, "3d")[0] == "No"

    task.supports = {"3d", "embedded"}
    assert applicability(task, "embedded")[0] == "Yes"
    assert applicability(task, "cluster")[0] == "No"
    task.supports = {"3d", "cluster"}
    assert applicability(task, "cluster")[0] == "Yes"
    assert applicability(task, "embedded")[0] == "No"


def test_custom_calculation_rejects_unsupported_free_cluster():
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    error = custom_flow.calculation_unavailable_reason(controller, InputParameters.for_task("SCF"))
    assert "free clusters without a host" in error


def test_task_chooser_filters_sorts_and_keeps_unsupported_selectable(monkeypatch):
    _app()
    monkeypatch.setattr(task_chooser, "task_choices", lambda _atoms: _rows())
    chooser = TaskChooserDialog(object())
    assert [chooser.table.horizontalHeaderItem(i).text()
            for i in range(chooser.table.columnCount())] == [
        "Name", "Possible", "Preferred", "Supported", "Experimental", "Info"
    ]
    assert _names(chooser.table) == ["A", "Z", "B", "C"]

    experimental_col = chooser._fields.index("experimental")
    chooser._sort_by_column(experimental_col)
    assert chooser._descending is True
    assert _names(chooser.table) == ["A", "C", "Z", "B"]
    chooser._sort_by_column(experimental_col)
    assert chooser._descending is False
    assert _names(chooser.table) == ["Z", "B", "A", "C"]

    chooser._sort_by_column(chooser._fields.index("name"))
    assert _names(chooser.table) == ["A", "B", "C", "Z"]
    chooser.search.setText("unsupported")
    assert _names(chooser.table) == ["B"]
    chooser.search.clear()
    chooser.applicability_filter.setCurrentText("No")
    assert _names(chooser.table) == ["B"]

    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: (
        messages.append(True) or QMessageBox.StandardButton.Yes
    ))
    chooser._accept_selection()
    assert chooser.result() == QDialog.DialogCode.Accepted
    assert chooser.selected_task == "B"
    assert messages


def test_task_chooser_without_structure_has_no_applicability_column(monkeypatch):
    _app()
    monkeypatch.setattr(task_chooser, "task_choices", lambda _atoms: _rows())
    chooser = TaskChooserDialog(None)
    assert [chooser.table.horizontalHeaderItem(i).text()
            for i in range(chooser.table.columnCount())] == [
        "Name", "Preferred", "Supported", "Experimental", "Info"
    ]
    assert chooser.applicability_filter is None
    assert _names(chooser.table) == ["A", "C", "B", "Z"]
    experimental_col = chooser._fields.index("experimental")
    chooser._sort_by_column(experimental_col)
    assert chooser._descending is True
    assert _names(chooser.table) == ["A", "C", "B", "Z"]
    chooser._sort_by_column(experimental_col)
    assert chooser._descending is False
    assert _names(chooser.table) == ["B", "Z", "A", "C"]
    chooser.reject()


def test_custom_input_is_available_without_structure_and_does_not_publish_ipd(
    tmp_path, monkeypatch,
):
    _app()
    controller = WorkspaceController(WorkspaceState())
    history = RecentFiles(tmp_path / "recent.json")
    edited = []
    monkeypatch.setattr(custom_flow, "TaskChooserDialog", lambda *_args, **_kwargs: SimpleNamespace(
        exec=lambda: QDialog.DialogCode.Accepted, selected_task="SCF",
    ))
    monkeypatch.setattr(
        custom_flow, "edit_custom_parameters",
        lambda ctrl, files, parent, parameters, **_kw: (
            edited.append((ctrl, files, parameters.task_name)) or True
        ),
    )
    assert custom_flow.choose_custom_task(
        controller, history, None, dataset_default_mode="empty"
    )
    assert edited == [(controller, history, "SCF")]
    assert controller.input_parameters is None
    assert controller.atoms is None
    assert "CONTROL.POTFIL" in custom_flow.calculation_unavailable_reason(
        controller, InputParameters.for_task("SCF"),
    )


@pytest.mark.parametrize(("guided", "embedded"), [(True, False), (False, True)])
def test_file_input_prepares_without_workspace_structure(tmp_path, monkeypatch, guided, embedded):
    _app()
    controller = WorkspaceController(WorkspaceState())
    history = RecentFiles(tmp_path / "recent.json")
    source = tmp_path / "Fe.pot"
    cluster = tmp_path / "Fe3CoFe3.clupot"
    examples = Path(ase2sprkkr.__file__).parent / "potentials" / "examples"
    copyfile(examples / "Fe3CoFe3.host.pot", source)
    if embedded:
        copyfile(examples / "Fe3CoFe3.clu.pot", cluster)
    original = {path: path.read_bytes() for path in (source, cluster) if path.is_file()}
    run_path = tmp_path / "run"
    run_path.mkdir()
    monkeypatch.setattr(custom_flow, "is_guided_task", lambda _task: guided)
    dialog_type = (
        custom_flow.GuidedInputParametersDialog if guided
        else custom_flow.InputParametersDialog
    )

    def configure(dialog):
        if guided:
            assert dialog.navigation.item(0).text() == "Input files"
        else:
            assert dialog.findChild(QTabWidget).tabText(0) == "Input files"
        assert not dialog.calculate_button.isEnabled()
        if embedded:
            assert dialog.session.set_value(("CONTROL", "CLUTYPE"), "embedded")
        assert dialog.session.set_value(("CONTROL", "POTFIL"), source.name)
        if embedded:
            assert not dialog.calculate_button.isEnabled()
            assert dialog.session.set_value(("CONTROL", "POTFIL_CLU"), cluster.name)
        assert dialog.session.set_value(("CONTROL", "ADSI"), "")
        assert dialog.calculate_button.isEnabled()
        return QDialog.DialogCode.Accepted

    prepared_files = []
    prepare_files = SprkkrExecution.prepare_files

    def prepare(execution):
        request = execution.request
        assert request.directory == str(run_path)
        assert request.potential is False
        assert request.structure_id is None
        assert request.state_id is None
        assert request.input_parameters.CONTROL.DATASET() == ("CoFe6" if embedded else "Fe")
        files = prepare_files(execution)
        _, input_file, host_file, _ = files
        prepared_files.append(input_file)
        saved = InputParameters.from_file(input_file)
        assert Path(host_file) == source
        assert saved.CONTROL.POTFIL() == "../Fe.pot"
        if embedded:
            assert saved.CONTROL.POTFIL_CLU() == "../Fe3CoFe3.clupot"
        assert saved.CONTROL.ADSI() == ""
        return files

    def select_profile(_parent, *, directory, **_options):
        assert directory == str(tmp_path)
        return True, None, None, str(run_path), None, True, False

    monkeypatch.setattr(dialog_type, "exec", configure)
    monkeypatch.setattr(custom_flow.calculation_flow, "_select_profile", select_profile)
    monkeypatch.setattr(SprkkrExecution, "prepare_files", prepare)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, _title, message: pytest.fail(message),
    )
    assert custom_flow.edit_custom_parameters(
        controller, history, None, InputParameters.for_task("SCF"),
        input_directory=tmp_path,
    )
    assert len(prepared_files) == 1
    assert controller.atoms is None
    assert controller.input_parameters is None
    assert all(path.read_bytes() == content for path, content in original.items())



def test_file_input_keeps_working_dialog_until_editor_is_prepared(tmp_path, monkeypatch):
    app = _app()
    parent = QWidget()
    controller = WorkspaceController(WorkspaceState())
    recent = RecentFiles(tmp_path / "recent.json")
    path = tmp_path / "Fe.inp"
    path.write_text("test input", encoding="utf-8")
    parsed = object()
    prepared = QDialog(parent)
    events = []

    def read(input_path):
        assert QThread.currentThread() is not app.thread()
        assert input_path == path
        events.append("read")
        return parsed

    def build(ctrl, owner, parameters, input_directory, *, recent_files):
        assert recent_files is recent
        assert QThread.currentThread() is app.thread()
        assert (ctrl, owner, parameters, input_directory) == (
            controller, parent, parsed, tmp_path,
        )
        waiting = parent.findChild(_ModalTaskDialog)
        assert waiting is not None and waiting.isVisible()
        events.append("build")
        return prepared

    def edit(ctrl, files, owner, parameters, **options):
        assert (ctrl, files, owner, parameters) == (
            controller, recent, parent, parsed,
        )
        assert options["prepared_dialog"] is prepared
        assert not parent.findChild(_ModalTaskDialog).isVisible()
        events.append("edit")
        return True

    def refresh():
        waiting = parent.findChild(_ModalTaskDialog)
        assert waiting is not None and waiting.isVisible()
        events.append("refresh")

    recent.changed.connect(refresh)
    monkeypatch.setattr(custom_flow.InputParameters, "from_file", staticmethod(read))
    monkeypatch.setattr(custom_flow, "_custom_input_dialog", build)
    monkeypatch.setattr(custom_flow, "edit_custom_parameters", edit)

    assert custom_flow.load_custom_input(controller, recent, parent, path)
    assert events == ["read", "build", "refresh", "edit"]
    assert recent.paths("input") == (str(path),)


def test_cli_input_uses_standalone_editor_and_not_workspace_document(tmp_path, monkeypatch):
    _app()
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    path = tmp_path / "input.inp"
    path.write_text("not actually parsed", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        custom_flow, "load_custom_input",
        lambda controller, history, parent, input_path, **kwargs: (
            calls.append((controller, history, parent, input_path)) or True
        ),
    )
    assert gui.open_startup_selection("input", str(path))
    assert calls == [(gui.controller, gui.recent_files, gui.create_workflow_window(), path)]
    assert gui.controller.input_parameters is None
    gui.create_workflow_window().close()


def test_expert_input_supports_independent_save_and_calculation_reason(monkeypatch):
    _app()
    dialog = expert_input.InputParametersDialog(
        InputParameters.for_task("SCF"),
        calculation_mode=True,
        calculation_unavailable_reason=lambda _params: "No structure loaded",
    )
    assert dialog.ok_btn.text() == "Calculate"
    assert not dialog.ok_btn.isEnabled()
    assert "No structure loaded" in dialog.ok_btn.toolTip()
    assert dialog.save_btn.isEnabled()
    saved = []
    monkeypatch.setattr(dialog.tree_editor, "commit_pending", lambda: True)
    monkeypatch.setattr(
        expert_input, "choose_and_save_input_parameters",
        lambda params, parent, **_options: saved.append((params, parent)) or True,
    )
    dialog.save_btn.click()
    assert len(saved) == 1
    assert saved[0][1] is dialog
    assert saved[0][0] is not dialog.session.working_parameters
    assert dialog.result() == 0
    dialog.close()

def test_expert_schema_load_accepts_task_switch_but_guided_restricts_it(
    tmp_path, monkeypatch,
):
    from ase2sprkkr_gui.gui.input_parameters.session import create_input_parameters_session
    from ase2sprkkr_gui.gui.flows import input_parameters as input_flows

    _app()
    source = InputParameters.for_task("BSFEK")
    new_task = InputParameters.for_task("BSFKK")
    path = tmp_path / "task.inp"
    monkeypatch.setattr(
        input_flows.InputParameters, "from_file", lambda _path: new_task,
    )
    session = create_input_parameters_session(source)
    assert input_flows.load_input_parameters(session, path, None)
    assert session.working_parameters.task_name == "BSFKK"

    guided_session = create_input_parameters_session(source)
    errors = []
    monkeypatch.setattr(
        input_flows.QMessageBox, "critical",
        lambda _parent, _title, message: errors.append(message),
    )
    assert not input_flows.load_input_parameters(
        guided_session, path, None, compatible_tasks=("BSFEK",),
    )
    assert guided_session.working_parameters.task_name == "BSFEK"
    assert "Expected BSFEK" in errors[0]


def test_native_2d_applicability_uses_registered_task_metadata():
    from ase2sprkkr.sprkkr.build import semiinfinite_system

    bulk = Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True)
    layer = semiinfinite_system(bulk, repeat=2)
    surface_choices = {row.name: row for row in task_chooser.task_choices(layer)}
    for name in ("SCF", "DOS", "JXC", "BSF", "ARPES"):
        assert surface_choices[name].applicable == "Yes"
    for name in ("CHILANDAU", "POSANI", "POSANIPREP", "POSANITAU",
                 "BONDING", "PLOT2DRHO"):
        assert surface_choices[name].applicable == "No"

    bulk_choices = {row.name: row for row in task_chooser.task_choices(bulk)}
    assert bulk_choices["CHILANDAU"].applicable == "Yes"
    assert bulk_choices["BONDING"].applicable == "No"



def test_expert_explicit_save_populates_recent_history(tmp_path, monkeypatch):
    _app()
    history = RecentFiles(tmp_path / "recent.json")
    dialog = expert_input.InputParametersDialog(
        InputParameters.create("scf"), recent_files=history,
    )
    target = tmp_path / "expert_scf.inp"
    from ase2sprkkr_gui.gui.flows import input_parameters as input_flows
    monkeypatch.setattr(
        input_flows.QFileDialog, "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )
    dialog.save_btn.click()
    assert target.is_file()
    assert history.paths("input") == (str(target.resolve()),)
    dialog.close()
