"""Backend execution service for one SPR-KKR calculation request."""
from __future__ import annotations

import logging
import warnings
from dataclasses import replace
from typing import Any, Callable

from ase2sprkkr import SPRKKR
from ase2sprkkr.execution import MpiNotFoundWarning

from guy4ase.gui.application.execution_cancellation import (
    Cancellation,
    ExecutionCancelled,
    register_runner,
    wait_for_runner,
)
from guy4ase.gui.application.result_loading import LoadedResult, load_result
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.input_parameters.dataset import dataset_value, filename_component

logger = logging.getLogger(__name__)


class SprkkrExecution:
    """Run one immutable calculation request without any Qt dependency."""

    def __init__(
        self,
        request: CalculationRequest,
        cancellation: Cancellation,
        *,
        profile_name: str | None = None,
        execution_manager=None,
        project_id: str | None = None,
        output: Callable[[str, str], None] | None = None,
        status: Callable[[str], None] | None = None,
        warning: Callable[[str], None] | None = None,
        persistent_job_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.request = replace(request, atoms=request.atoms.copy())
        self.cancellation = cancellation
        self.profile_name = profile_name
        self.execution_manager = execution_manager
        self.project_id = project_id
        self._output = output or (lambda _text, _kind: None)
        self._status = status or (lambda _text: None)
        self._warning = warning or (lambda _text: None)
        self._persistent_job_changed = persistent_job_changed

    def file_names(self) -> tuple[str, str, str]:
        """Return input, potential and output filename templates for the request."""
        dataset = dataset_value(self.request.input_parameters)
        if dataset is None:
            return "%a_%T.inp", "%a.pot", "%a_%T.out"
        base = filename_component(dataset)
        if not base:
            return "%a_%T.inp", "%a.pot", "%a_%T.out"
        return f"{base}_%T.inp", f"{base}.pot", f"{base}_%T.out"

    def _with_mpi_warnings(self, operation):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", MpiNotFoundWarning)
            result = operation()

        for item in caught:
            if issubclass(item.category, MpiNotFoundWarning):
                self._warning(str(item.message))
            else:
                warnings.showwarning(
                    item.message,
                    item.category,
                    item.filename,
                    item.lineno,
                    file=item.file,
                    line=item.line,
                )
        return result

    def _calculator(self) -> SPRKKR:
        return SPRKKR() if self.profile_name is None else SPRKKR(profile=self.profile_name)

    def _project_context(self):
        if self.project_id is None:
            return None
        if self.execution_manager is None:
            return self.project_id
        return self.execution_manager.for_project(self.project_id)

    def _create_runner(self, calculator: SPRKKR):
        input_file, potential_file, output_file = self.file_names()
        return self._with_mpi_warnings(
            lambda: calculator.create_run(
                atoms=self.request.atoms,
                input_parameters=self.request.input_parameters,
                directory=self.request.directory,
                input_file=input_file,
                potential_file=potential_file,
                output_file=output_file,
                empty_spheres=False,
                read_callback=self._output,
                print_output=False,
                project=self._project_context(),
                restart_scf=self.request.restart_scf,
            )
        )

    def _notify_persistent_job_changed(self, runner: Any) -> None:
        callback = self._persistent_job_changed
        if callback is None or self.project_id is None:
            return
        try:
            callback(str(runner.id))
        except Exception:  # noqa: BLE001 - observer must never fail execution
            logger.exception("Persistent-job change observer failed for %s", runner.id)

    def _submit(self, calculator: SPRKKR):
        runner = self._create_runner(calculator)
        register_runner(self.cancellation, runner)

        try:
            self._with_mpi_warnings(runner.submit)
        finally:
            # Submission is the first point at which ASE2SPRKKR may have written
            # the persistent RunRecord. The observer receives only its stable id
            # and must reload authoritative metadata from the store.
            self._notify_persistent_job_changed(runner)
        if self.cancellation.requested:
            raise ExecutionCancelled
        return runner

    def run(self) -> LoadedResult:
        """Execute the request and return its loaded result."""
        self._status("Preparing calculation…")
        runner = self._submit(self._calculator())

        record = runner.record if self.project_id is not None else None
        if record is not None and record.execution.endpoint.executor != "local":
            endpoint = record.execution.endpoint
            self._status(f"Running on {endpoint.host or endpoint.executor}…")
        else:
            self._status("Running…")

        try:
            result = wait_for_runner(self.cancellation, runner)
        finally:
            # A project runner persists its terminal record while waiting.
            self._notify_persistent_job_changed(runner)

        self._status("Loading result…")
        loaded = load_result(
            result,
            fallback_directory=self.request.directory,
            persistent_ref=(runner.id if self.project_id is not None else None),
        )
        self._status("Finished")
        return loaded
