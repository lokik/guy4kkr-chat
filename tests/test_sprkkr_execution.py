from __future__ import annotations

from ase import Atoms

from guy4ase.gui.application import sprkkr_execution as execution_module
from guy4ase.gui.application.execution_cancellation import ExecutionCancelled
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace_controller import CalculationRequest


class _Cancellation:
    def __init__(self, *, requested: bool = False, register: bool = True):
        self.requested = requested
        self._register = register
        self.runner = None

    def register(self, runner):
        self.runner = runner
        return self._register and not self.requested


def _request(tmp_path, *, restart_scf: bool = False) -> CalculationRequest:
    return CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        structure_id=1,
        state_id=1,
        restart_scf=restart_scf,
    )


def test_execution_constructs_sprkkr_with_selected_profile(monkeypatch, tmp_path):
    captured = {}

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    class Runner:
        reference = None
        id = "run-1"

        def submit(self):
            pass

        def wait(self):
            return object()

    def make_calculator(*, profile):
        captured["profile"] = profile
        return Calculator()

    monkeypatch.setattr(execution_module, "SPRKKR", make_calculator)
    monkeypatch.setattr(execution_module, "load_result", lambda *_args, **_kwargs: object())

    SprkkrExecution(
        _request(tmp_path),
        _Cancellation(),
        profile_name="cluster",
    ).run()

    assert captured == {"profile": "cluster"}


def test_execution_requests_persistent_backend_run(monkeypatch, tmp_path):
    captured = {}

    class Runner:
        reference = None
        id = "run-1"

        def submit(self):
            pass

        def wait(self):
            return object()

    class Calculator:
        def create_run(self, **kwargs):
            captured.update(kwargs)
            return Runner()

    execution = SprkkrExecution(_request(tmp_path), _Cancellation())
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(execution_module, "load_result", lambda *_args, **_kwargs: object())

    execution.run()

    assert captured["persistent"] is True
    assert captured["print_output"] is False
    assert captured["empty_spheres"] is False


def test_execution_binds_persistent_manager_to_launch_project(monkeypatch, tmp_path):
    captured = {}
    bound_manager = object()

    class Manager:
        def for_project(self, project_id):
            captured["project_id"] = project_id
            return bound_manager

    class Runner:
        reference = None
        id = "run-1"

        def submit(self):
            pass

        def wait(self):
            return object()

    class Calculator:
        def create_run(self, **kwargs):
            captured.update(kwargs)
            return Runner()

    execution = SprkkrExecution(
        _request(tmp_path),
        _Cancellation(),
        execution_manager=Manager(),
        project_id="project-17",
    )
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(execution_module, "load_result", lambda *_args, **_kwargs: object())

    execution.run()

    assert captured["project_id"] == "project-17"
    assert captured["persistent"] is bound_manager


def test_cancel_before_registration_never_submits(monkeypatch, tmp_path):
    cancellation = _Cancellation(requested=True)
    events = []

    class Runner:
        def cancel(self):
            events.append("cancel")

        def submit(self):  # pragma: no cover - contract forbids this
            events.append("submit")

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    execution = SprkkrExecution(_request(tmp_path), cancellation)
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())

    try:
        execution.run()
    except ExecutionCancelled:
        pass
    else:  # pragma: no cover - assertion helper
        raise AssertionError("cancelled execution must not continue")

    assert events == ["cancel"]


def test_cancel_racing_with_submit_is_not_cancelled_twice(monkeypatch, tmp_path):
    cancellation = _Cancellation()
    events = []

    class Runner:
        def submit(self):
            events.append("submit")
            cancellation.requested = True
            self.cancel()

        def cancel(self):
            events.append("cancel")

        def wait(self):  # pragma: no cover - cancellation stops before wait
            events.append("wait")

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    execution = SprkkrExecution(_request(tmp_path), cancellation)
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())

    try:
        execution.run()
    except ExecutionCancelled:
        pass
    else:  # pragma: no cover - assertion helper
        raise AssertionError("cancelled execution must not continue")

    assert events == ["submit", "cancel"]


def test_persistent_reference_is_forwarded_to_result_loader(monkeypatch, tmp_path):
    backend_result = object()
    loaded_result = object()
    calls = []

    class Runner:
        reference = None
        id = "persistent-run-42"

        def submit(self):
            pass

        def wait(self):
            return backend_result

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    def load_result(result, *, fallback_directory, persistent_ref):
        calls.append((result, fallback_directory, persistent_ref))
        return loaded_result

    execution = SprkkrExecution(_request(tmp_path), _Cancellation())
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(execution_module, "load_result", load_result)

    assert execution.run() is loaded_result
    assert calls == [(backend_result, str(tmp_path), "persistent-run-42")]


def test_execution_notifies_persistent_job_id_after_submit_and_completion(
    monkeypatch, tmp_path
):
    changes = []

    class Runner:
        reference = None
        id = "persistent-run-17"

        def submit(self):
            pass

        def wait(self):
            return object()

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    execution = SprkkrExecution(
        _request(tmp_path),
        _Cancellation(),
        persistent_job_changed=changes.append,
    )
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(execution_module, "load_result", lambda *_args, **_kwargs: object())

    execution.run()

    assert changes == ["persistent-run-17", "persistent-run-17"]


def test_persistent_job_observer_failure_does_not_fail_calculation(
    monkeypatch, tmp_path
):
    class Runner:
        reference = None
        id = "persistent-run-17"

        def submit(self):
            pass

        def wait(self):
            return object()

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    def broken_observer(_job_id):
        raise RuntimeError("observer failure")

    execution = SprkkrExecution(
        _request(tmp_path),
        _Cancellation(),
        persistent_job_changed=broken_observer,
    )
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(execution_module, "load_result", lambda *_args, **_kwargs: object())

    assert execution.run() is not None
