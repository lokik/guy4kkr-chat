from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.flows import calculation as calculation_flow


def _controller(record, replacements):
    structure_generation = object()
    input_generation = object()

    def replace(parameters, **kwargs):
        replacements.append((parameters, kwargs))
        return object()

    return SimpleNamespace(
        result_store=SimpleNamespace(result=lambda result_id: record),
        directory="calculation",
        structure_generation=structure_generation,
        input_parameters_generation=input_generation,
        atoms=Atoms("Fe"),
        replace_input_parameters=replace,
    )


def test_non_guided_result_recompute_uses_expert_editor(monkeypatch):
    historical = InputParameters.create("TORQUE")
    edited = historical.copy(copy_values=True)
    record = SimpleNamespace(
        task_name="torque",
        input_parameters=historical,
    )
    replacements = []
    controller = _controller(record, replacements)
    editor_calls = []

    def edit(parameters, *, parent, atoms):
        editor_calls.append((parameters, parent, atoms))
        return edited

    monkeypatch.setattr(calculation_flow, "edit_input_parameters", edit)
    monkeypatch.setattr(
        calculation_flow,
        "document_change_applied",
        lambda parent, change: True,
    )
    launched = object()
    launch_calls = []

    def run(controller_arg, recent_files, parent, **kwargs):
        launch_calls.append((controller_arg, recent_files, parent, kwargs))
        return launched

    monkeypatch.setattr(calculation_flow, "run_calculation", run)
    parent = object()
    recent_files = object()

    result = calculation_flow.recompute_result(
        controller,
        recent_files,
        parent,
        17,
    )

    assert result is launched
    assert len(editor_calls) == 1
    editor_parameters, editor_parent, editor_atoms = editor_calls[0]
    assert editor_parameters is not historical
    assert editor_parameters.task_name.lower() == "torque"
    assert editor_parent is parent
    assert editor_atoms is controller.atoms
    assert replacements == [(
        edited,
        {
            "expected_input_parameters_generation": controller.input_parameters_generation,
            "expected_structure_generation": controller.structure_generation,
        },
    )]
    assert launch_calls == [(
        controller,
        recent_files,
        parent,
        {"position_like_window": "expert-input", "track_launch_monitor": None},
    )]


def test_recompute_routes_editor_by_effective_task(monkeypatch):
    historical = InputParameters.create("ARPES")
    historical.TASK.TASK = "SPLEED"
    edited = historical.copy(copy_values=True)
    assert historical.definition_name.upper() == "ARPES"
    assert historical.task_name.upper() == "SPLEED"
    record = SimpleNamespace(
        task_name="spleed",
        input_parameters=historical,
    )
    replacements = []
    controller = _controller(record, replacements)
    editor_calls = []

    def edit(parameters, *, parent, atoms):
        editor_calls.append((parameters, parent, atoms))
        return edited

    monkeypatch.setattr(calculation_flow, "edit_input_parameters", edit)
    monkeypatch.setattr(
        calculation_flow,
        "GuidedInputParametersDialog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("effective SPLEED must use the Expert editor")
        ),
    )
    monkeypatch.setattr(
        calculation_flow,
        "document_change_applied",
        lambda parent, change: True,
    )
    launched = object()
    launch_calls = []

    def run(controller_arg, recent_files, parent, **kwargs):
        launch_calls.append((controller_arg, recent_files, parent, kwargs))
        return launched

    monkeypatch.setattr(calculation_flow, "run_calculation", run)
    parent = object()
    recent_files = object()

    result = calculation_flow.recompute_result(
        controller,
        recent_files,
        parent,
        18,
    )

    assert result is launched
    assert len(editor_calls) == 1
    editor_parameters, editor_parent, editor_atoms = editor_calls[0]
    assert editor_parameters is not historical
    assert editor_parameters.definition_name.upper() == "ARPES"
    assert editor_parameters.task_name.upper() == "SPLEED"
    assert editor_parent is parent
    assert editor_atoms is controller.atoms
    assert replacements == [(
        edited,
        {
            "expected_input_parameters_generation": controller.input_parameters_generation,
            "expected_structure_generation": controller.structure_generation,
        },
    )]
    assert launch_calls == [(
        controller,
        recent_files,
        parent,
        {"position_like_window": "expert-input", "track_launch_monitor": None},
    )]
