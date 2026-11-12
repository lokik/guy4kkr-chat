from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr import InputParameters, TaskResult
from ase2sprkkr.execution.manager import ExecutionManager
from ase2sprkkr.execution import (
    FileEntry,
    FileManifest,
    RunState,
    RunStore,
)
from ase2sprkkr.outputs.reader_registry import reader_registry

from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.flows import calculation as calculation_flow


def test_persistent_task_identity_round_trip_drives_recompute_editor(
    monkeypatch,
    tmp_path,
):
    """Preserve effective task and schema across persistence and Guy routing."""
    parameters = InputParameters.create("ARPES")
    parameters.TASK.TASK = "SPLEED"
    parameters.CONTROL.DATASET = "contract"
    assert parameters.definition_name.upper() == "ARPES"
    assert parameters.task_name.upper() == "SPLEED"

    input_path = tmp_path / "contract.inp"
    output_path = tmp_path / "contract.out"
    with input_path.open("w") as stream:
        parameters.save_to_file(stream, validate=False)
    output_path.write_text("synthetic persistent output\n")

    manager = ExecutionManager(RunStore(tmp_path / "runs"))
    run = manager.new_record(
        task="SPLEED",
        input_definition="ARPES",
        directory=tmp_path,
        files=FileManifest(
            inputs=(FileEntry(local_path=str(input_path)),),
            stdout=FileEntry(local_path=str(output_path)),
        ),
    )
    manager.store.save(run)
    run = manager.complete(run, state=RunState.FINISHED, return_code=0, artifacts_available=True)

    class Reader:
        def __init__(
            self,
            input_parameters,
            calculator,
            directory,
            task_name=None,
        ):
            self.input_parameters = input_parameters
            self.calculator = calculator
            self.directory = directory
            self.task_name = task_name

        def read_from_file(
            self,
            output_file,
            error_file=None,
            *,
            return_code,
            input_file=None,
            directory=None,
        ):
            result = TaskResult(
                self.input_parameters,
                self.calculator,
                directory or self.directory,
                output_file=output_file,
                input_file=input_file,
                task_name=self.task_name,
            )
            result.complete(None, return_code)
            return result

    resolved_tasks = []

    def reader_class_for_task(task):
        resolved_tasks.append(task)
        return Reader

    monkeypatch.setattr(reader_registry, "class_for_task", reader_class_for_task)

    loaded = PersistentJobSource(manager).load_result(run.id)

    assert len(resolved_tasks) == 1
    assert resolved_tasks[0].name == "SPLEED"
    assert resolved_tasks[0].input_parameters_definition_name == "ARPES"
    assert loaded.task_name.upper() == "SPLEED"
    assert loaded.input_parameters.definition_name.upper() == "ARPES"
    assert loaded.input_parameters.task_name.upper() == "SPLEED"
    assert loaded.run_record.task == "SPLEED"
    assert loaded.run_record.input_definition == "ARPES"

    history = ResultStore()
    record = history.add_external_result(
        loaded,
        atoms=None,
        input_parameters=loaded.input_parameters,
        directory=str(tmp_path),
        output_path=output_path,
        potential_path=None,
        persistent_ref=run.id,
    )
    assert record.task_name == "spleed"
    assert record.input_parameters.definition_name.upper() == "ARPES"
    assert record.input_parameters.task_name.upper() == "SPLEED"

    edited = record.input_parameters.copy(copy_values=True)
    replacements = []
    controller = SimpleNamespace(
        result_store=history,
        directory=str(tmp_path),
        structure_generation=object(),
        input_parameters_generation=object(),
        atoms=Atoms("Fe"),
        replace_input_parameters=lambda value, **kwargs: (
            replacements.append((value, kwargs)) or object()
        ),
    )
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
    monkeypatch.setattr(
        calculation_flow,
        "run_calculation",
        lambda *_args, **_kwargs: launched,
    )

    result = calculation_flow.recompute_result(
        controller,
        object(),
        object(),
        record.id,
    )

    assert result is launched
    assert len(editor_calls) == 1
    editor_parameters, _parent, editor_atoms = editor_calls[0]
    assert editor_parameters.definition_name.upper() == "ARPES"
    assert editor_parameters.task_name.upper() == "SPLEED"
    assert editor_atoms is controller.atoms
    assert replacements == [(
        edited,
        {
            "expected_input_parameters_generation": controller.input_parameters_generation,
            "expected_structure_generation": controller.structure_generation,
        },
    )]
