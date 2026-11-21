from __future__ import annotations

import pytest
from ase import Atoms
from ase2sprkkr import InputParameters

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs import guided_input as guided_input_module
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedTaskUnavailable
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow


def _controller(tmp_path) -> WorkspaceController:
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            directory=str(tmp_path),
        )
    )


def test_missing_backend_task_becomes_unavailable_before_materialization(monkeypatch):
    created = []
    monkeypatch.setattr(
        guided_input_module.InputParameters,
        "is_task_name",
        lambda _task: False,
    )
    monkeypatch.setattr(
        guided_input_module.InputParameters,
        "create",
        lambda task: created.append(task),
    )

    with pytest.raises(GuidedTaskUnavailable, match="SCF backend task is not available"):
        guided_input_module.select_guided_input_parameters(
            "scf",
            dataset_default_mode="auto",
        )

    assert created == []


def test_backend_task_import_error_becomes_unavailable(monkeypatch):
    error = ImportError("missing backend module")
    monkeypatch.setattr(
        guided_input_module.InputParameters,
        "is_task_name",
        lambda _task: "SCF",
    )

    def fail_create(_task):
        raise error

    monkeypatch.setattr(guided_input_module.InputParameters, "create", fail_create)

    with pytest.raises(GuidedTaskUnavailable) as raised:
        guided_input_module.select_guided_input_parameters(
            "scf",
            dataset_default_mode="auto",
        )

    assert raised.value.__cause__ is error


@pytest.mark.parametrize(
    "error",
    (KeyError("broken definition"), RuntimeError("broken task definition")),
)
def test_backend_task_programming_errors_propagate(monkeypatch, error):
    monkeypatch.setattr(
        guided_input_module.InputParameters,
        "is_task_name",
        lambda _task: "SCF",
    )

    def fail_create(_task):
        raise error

    monkeypatch.setattr(guided_input_module.InputParameters, "create", fail_create)

    with pytest.raises(type(error)) as raised:
        guided_input_module.select_guided_input_parameters(
            "scf",
            dataset_default_mode="auto",
        )

    assert raised.value is error


def test_expected_guided_task_unavailability_is_reported(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    messages = []

    def unavailable(*_args, **_kwargs):
        raise GuidedTaskUnavailable("SCF backend task could not be loaded")

    monkeypatch.setattr(
        calculation_flow,
        "select_guided_input_parameters",
        unavailable,
    )
    monkeypatch.setattr(
        calculation_flow.QMessageBox,
        "critical",
        lambda parent, title, message: messages.append((title, message)),
    )

    result = calculation_flow.configure_and_run_task(
        controller,
        recent,
        object(),
        "scf",
        dataset_default_mode="auto",
    )

    assert result is None
    assert messages == [
        ("Task Unavailable", "SCF backend task could not be loaded")
    ]


def test_later_import_errors_are_not_misreported_as_task_unavailable(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    parameters = InputParameters.create("SCF")

    monkeypatch.setattr(
        calculation_flow,
        "select_guided_input_parameters",
        lambda *args, **kwargs: parameters,
    )

    def fail_run(*_args, **_kwargs):
        raise ImportError("programming error after task setup")

    monkeypatch.setattr(calculation_flow, "run_calculation", fail_run)

    with pytest.raises(ImportError, match="programming error after task setup"):
        calculation_flow.configure_and_run_task(
            controller,
            recent,
            object(),
            "scf",
            dataset_default_mode="auto",
        )

    # Guided parameters are transient even if later launch code raises.
    assert controller.input_parameters is None


def test_guided_parameter_editor_opens_without_directory_prompt(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    controller.change_directory(None)
    parameters = InputParameters.create("SCF")
    monkeypatch.setattr(
        calculation_flow, "choose_working_directory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Directory selection must follow input editing")
        ),
    )
    monkeypatch.setattr(
        calculation_flow, "select_guided_input_parameters",
        lambda *_args, **_kwargs: parameters,
    )
    calls = []
    monkeypatch.setattr(
        calculation_flow, "run_calculation",
        lambda *_args, **kwargs: calls.append(
            (controller.directory, kwargs["request_override"])
        ) or "run",
    )
    assert calculation_flow.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), object(),
        "scf", dataset_default_mode="auto"
    ) == "run"
    assert len(calls) == 1
    assert calls[0][0] is None
    assert calls[0][1].input_parameters.task_name.lower() == "scf"
    assert controller.input_parameters is None


def test_cluster_guided_task_requests_native_host_before_committing(monkeypatch, tmp_path):
    from ase2sprkkr_gui.gui.flows import files as file_flows
    from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
    from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController

    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe", pbc=False)))
    # 0D atoms without an embedding host are not a valid cluster; this verifies
    # that the Guided boundary refuses the host preparation before starting.
    request = []
    monkeypatch.setattr(calculation_flow, "select_guided_input_parameters",
                        lambda *_args, **_kwargs: object())
    monkeypatch.setattr(file_flows, "ensure_embedded_host_potential",
                        lambda ctrl, parent: request.append((ctrl, parent)) or False)
    assert calculation_flow.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), None, "scf",
        dataset_default_mode="auto",
    ) is None
    assert request == [(controller, None)]
    assert controller.input_parameters is None
