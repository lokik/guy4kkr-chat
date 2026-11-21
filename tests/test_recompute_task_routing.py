"""Recompute a historical result as a detached run, never a workspace input edit."""
from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.flows import calculation as calculation_flow


def _controller(record, replacements):
    def replace(parameters, **kwargs):
        replacements.append((parameters, kwargs))
        raise AssertionError("Recompute must not publish input parameters to workspace")

    return SimpleNamespace(
        result_store=SimpleNamespace(result=lambda result_id: record),
        directory="calculation",
        structure_generation=object(),
        input_parameters_generation=object(),
        structure_id=13,
        state_id=29,
        restarted=False,
        atoms=Atoms("Fe"),
        input_parameters=InputParameters.create("SCF"),
        replace_input_parameters=replace,
    )


def _assert_detached_request(calls, controller, recent_files, parent, edited,
                             *, task, project_repository=None):
    assert len(calls) == 1
    actual_controller, actual_files, actual_parent, options = calls[0]
    assert actual_controller is controller
    assert actual_files is recent_files
    assert actual_parent is parent
    assert options["position_like_window"] == "expert-input"
    assert options["track_launch_monitor"] is None
    assert options["project_repository"] is project_repository
    assert set(options) == {
        "position_like_window", "track_launch_monitor",
        "project_repository", "request_override",
    }

    request = options["request_override"]
    assert request.atoms is controller.atoms
    assert request.structure_id == controller.structure_id
    assert request.state_id == controller.state_id
    assert request.directory == (controller.directory or "")
    assert request.restart_scf == controller.restarted
    assert request.input_parameters is not edited
    assert request.input_parameters is not controller.input_parameters
    assert request.input_parameters.task_name.lower() == task
    return request


def test_non_guided_result_recompute_uses_expert_and_detached_request(monkeypatch):
    historical = InputParameters.create("TORQUE")
    edited = historical.copy(copy_values=True)
    record = SimpleNamespace(task_name="torque", input_parameters=historical)
    replacements = []
    controller = _controller(record, replacements)
    controller.directory = None
    input_generation = controller.input_parameters_generation
    workspace_input = controller.input_parameters
    editor_calls = []

    def edit(parameters, *, parent, atoms, directory):
        assert directory == controller.directory
        editor_calls.append((parameters, parent, atoms))
        return edited

    monkeypatch.setattr(calculation_flow, "edit_input_parameters", edit)
    launched = object()
    launch_calls = []

    def run(controller_arg, recent_files, parent, **kwargs):
        launch_calls.append((controller_arg, recent_files, parent, kwargs))
        return launched

    monkeypatch.setattr(calculation_flow, "run_calculation", run)
    parent = object()
    recent_files = object()
    project_repository = object()

    assert calculation_flow.recompute_result(
        controller, recent_files, parent, 17,
        project_repository=project_repository,
    ) is launched

    assert len(editor_calls) == 1
    editor_parameters, editor_parent, editor_atoms = editor_calls[0]
    assert editor_parameters is not historical
    assert editor_parameters.task_name.lower() == "torque"
    assert editor_parent is parent
    assert editor_atoms is controller.atoms
    request = _assert_detached_request(
        launch_calls, controller, recent_files, parent, edited,
        task="torque", project_repository=project_repository,
    )
    assert request.input_parameters is not historical
    assert replacements == []
    assert controller.input_parameters is workspace_input
    assert controller.input_parameters_generation is input_generation


def test_recompute_uses_effective_task_without_adopting_expert_input(monkeypatch):
    historical = InputParameters.create("ARPES")
    historical.TASK.TASK = "SPLEED"
    edited = historical.copy(copy_values=True)
    assert historical.definition_name.upper() == "ARPES"
    assert historical.task_name.upper() == "SPLEED"
    record = SimpleNamespace(task_name="spleed", input_parameters=historical)
    replacements = []
    controller = _controller(record, replacements)
    workspace_input = controller.input_parameters
    input_generation = controller.input_parameters_generation
    editor_calls = []

    def edit(parameters, *, parent, atoms, directory):
        assert directory == controller.directory
        editor_calls.append((parameters, parent, atoms))
        return edited

    monkeypatch.setattr(calculation_flow, "edit_input_parameters", edit)
    monkeypatch.setattr(
        calculation_flow, "GuidedInputParametersDialog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Effective SPLEED must use the Expert editor")
        ),
    )
    launched = object()
    launch_calls = []

    def run(controller_arg, recent_files, parent, **kwargs):
        launch_calls.append((controller_arg, recent_files, parent, kwargs))
        return launched

    monkeypatch.setattr(calculation_flow, "run_calculation", run)
    parent = object()
    recent_files = object()

    assert calculation_flow.recompute_result(
        controller, recent_files, parent, 18,
    ) is launched

    assert len(editor_calls) == 1
    editor_parameters, editor_parent, editor_atoms = editor_calls[0]
    assert editor_parameters is not historical
    assert editor_parameters.definition_name.upper() == "ARPES"
    assert editor_parameters.task_name.upper() == "SPLEED"
    assert editor_parent is parent
    assert editor_atoms is controller.atoms
    request = _assert_detached_request(
        launch_calls, controller, recent_files, parent, edited, task="spleed",
    )
    assert request.input_parameters.definition_name.upper() == "ARPES"
    assert replacements == []
    assert controller.input_parameters is workspace_input
    assert controller.input_parameters_generation is input_generation


def test_expert_recompute_rejects_stale_structure_before_launch(monkeypatch):
    historical = InputParameters.create("TORQUE")
    record = SimpleNamespace(input_parameters=historical)
    replacements = []
    controller = _controller(record, replacements)
    messages = []

    def change_structure_while_editing(*_args, **_kwargs):
        controller.structure_generation = object()
        return historical.copy(copy_values=True)

    monkeypatch.setattr(
        calculation_flow, "edit_input_parameters", change_structure_while_editing,
    )
    monkeypatch.setattr(
        calculation_flow.QMessageBox, "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        calculation_flow, "run_calculation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Stale structure must not be submitted")
        ),
    )

    assert calculation_flow.recompute_result(
        controller, object(), None, 19,
    ) is None
    assert messages and messages[0][0] == "Structure Changed"
    assert replacements == []
