"""Read and track ASE2SPRKKR persistent-run history behind a GUI-facing API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

from kkrunner.backends.contracts import BackendCapability
from kkrunner.projects import ProjectRepository, ProjectRunManager
from ase2sprkkr.outputs.project_results import (
    attach_project_run,
    load_project_result,
    retry_project_postprocessing,
)
from ase2sprkkr.sprkkr.projects import (
    default_project_repository,
    project_execution_manager,
)

logger = logging.getLogger(__name__)

_FINAL_STATES = frozenset(
    {"finished", "failed", "cancelled"}
)
JobChangedListener = Callable[[str], None]
_RECOVERING = object()


def project_run_manager(projects: ProjectRepository) -> ProjectRunManager:
    """Use ASE2SPRKKR's storage policy with KKRunner's project-run manager."""
    return project_execution_manager(project_repository=projects)


def _value(value: Any) -> str:
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _execution_target(record: Any) -> str:
    """Describe transport and native backend separately."""
    transport = record.execution.transport
    backend = record.execution.backend
    kind = _value(transport.kind)
    label = "Local" if transport.is_local else f"{kind.upper()} · {transport.host}"
    if backend.name == "psij":
        executor_name = dict(backend.options).get("executor_name", "slurm")
        return (f"PSI/J · {executor_name}" if transport.is_local
                else f"{label} · PSI/J {executor_name}")
    if backend.name == "process":
        return f"{label} · supervised"
    return label


def _attachment_availability(record: Any, state: str) -> tuple[bool, str | None]:
    """Explain whether a persisted execution can be observed after a GUI restart."""
    if state in _FINAL_STATES:
        return False, None
    if record.execution.backend_id is None:
        return (
            False,
            "No backend identity has been saved for this calculation yet. "
            "Refresh statuses to attempt submission recovery.",
        )
    backend = record.execution.backend.create()
    if BackendCapability.REATTACH not in backend.supports:
        return (
            False,
            f"The {backend.name} backend cannot reattach to an existing calculation. "
            "A remote calculation may still be running, even when its status is Unknown. "
            "For future SSH calculations, enable 'Reattachable process' in the run profile.",
        )
    return True, None


@dataclass(frozen=True)
class PersistentJob:
    """Stable presentation model for one persistent ASE2SPRKKR run."""

    id: str
    state: str
    created_at: str
    updated_at: str
    task: str
    directory: str
    dataset: str | None
    target: str
    return_code: int | None
    message: str | None
    result_files_state: str | None = None
    finished_at: str | None = None
    attachable: bool = False
    reattach_unavailable_reason: str | None = None
    result_files_verified: bool = False
    failure_phase: str | None = None
    project_id: str | None = None

    @property
    def started_at(self) -> str:
        return self.created_at

    @property
    def is_final(self) -> bool:
        return self.state in _FINAL_STATES

    @property
    def can_retry_download(self) -> bool:
        """Whether an explicit retry of failed output transfer is meaningful."""
        return self.state == "failed" and self.failure_phase == "download" and self.return_code == 0

    @property
    def can_retry_postprocessing(self) -> bool:
        """Whether failed result processing can be retried without execution."""
        return (
            self.state == "failed"
            and self.failure_phase == "postprocessing"
            and self.return_code == 0
        )

    @classmethod
    def from_run_record(
        cls,
        record: Any,
        *,
        result_files_verified: bool = False,
    ) -> "PersistentJob":
        state = _value(record.state)
        result_files = record.files
        result_files_state = None if result_files is None else _value(result_files.state)
        finished_at = getattr(record, "finished_at", None)
        metadata = record.metadata.get("ase2sprkkr", {})
        attachable, reattach_unavailable_reason = _attachment_availability(record, state)
        return cls(
            id=str(record.id),
            state=state,
            created_at=str(record.created_at),
            updated_at=str(record.updated_at),
            task=str(metadata.get("task") or "Unknown").upper(),
            directory=str(record.execution.directory.local),
            dataset=(None if metadata.get("dataset") is None else str(metadata["dataset"])),
            target=_execution_target(record),
            return_code=getattr(record, "return_code", None),
            message=getattr(record, "message", None),
            result_files_state=result_files_state or None,
            finished_at=None if finished_at is None else str(finished_at),
            attachable=attachable,
            reattach_unavailable_reason=reattach_unavailable_reason,
            result_files_verified=result_files_verified,
            failure_phase=(None if record.failure_phase is None else _value(record.failure_phase)),
            project_id=getattr(record, "project_id", None),
        )


class PersistentJobSource:
    """Application-owned persistent-job cache and lifecycle adapter.

    ASE2SPRKKR's persisted ``RunRecord`` remains authoritative. ``job_changed``
    receives only a stable run id and reloads the record from the persistent
    store instead of accepting a parallel copy of lifecycle state.

    Recovery of interrupted ``downloading`` and ``postprocessing`` jobs is an implementation detail of
    this source. Presentation code never owns or classifies recovery failures.
    A failed download is terminal until the user explicitly retries it;
    the backend then owns the transfer and postprocessing transitions.
    """

    def __init__(self, manager: Any | None = None) -> None:
        self._manager = manager
        self.unavailable_reason: str | None = None
        self._lock = RLock()
        self._jobs: dict[str, PersistentJob] = {}
        self._listeners: set[JobChangedListener] = set()
        self._recovery_runners: dict[str, Any] = {}

        if manager is None:
            # The backend stores project runs globally, not in a legacy default
            # persistent-run manager. Browse that same authoritative store.
            manager = project_run_manager(default_project_repository())
            self._manager = manager

        try:
            store = manager.store
        except AttributeError as exc:
            raise TypeError("persistent job manager must expose a run store") from exc
        if not callable(getattr(store, "runs", None)) or not callable(
            getattr(store, "get", None)
        ):
            raise TypeError("persistent run store must provide runs() and get()")

        self.reload(notify=False)
        # Recover persisted work at startup. Ordinary state notifications can
        # describe runs still owned by their original live monitor.
        self._recover_incomplete(self.jobs())

    @property
    def available(self) -> bool:
        return self._manager is not None

    @property
    def supports_refresh(self) -> bool:
        return self.available and callable(getattr(self._manager, "refresh", None))

    @property
    def supports_results(self) -> bool:
        return self.available and callable(getattr(self._manager, "retrieve_result_files", None))

    @property
    def supports_attach(self) -> bool:
        return self.available and callable(getattr(self._manager, "attach", None))

    @property
    def supports_retry_download(self) -> bool:
        return self.supports_attach

    @property
    def supports_retry_postprocessing(self) -> bool:
        return self.available and callable(getattr(self._manager, "retry_postprocessing", None))

    @property
    def supports_result_file_check(self) -> bool:
        return self.available

    @property
    def active_recovery_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._recovery_runners)

    def subscribe(self, listener: JobChangedListener) -> Callable[[], None]:
        """Subscribe to metadata changes and return an unsubscribe callback."""
        with self._lock:
            self._listeners.add(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe

    def _notify(self, job_id: str) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(job_id)
            except Exception:  # noqa: BLE001 - subscriber isolation boundary
                logger.exception("Persistent-job listener failed for %s", job_id)

    def jobs(self) -> tuple[PersistentJob, ...]:
        """Return cached history without backend or filesystem I/O."""
        with self._lock:
            jobs = tuple(self._jobs.values())
        return tuple(sorted(jobs, key=lambda job: job.started_at, reverse=True))

    def job(self, job_id: str) -> PersistentJob | None:
        with self._lock:
            return self._jobs.get(str(job_id))

    def reload(self, *, notify: bool = True) -> tuple[PersistentJob, ...]:
        """Reload authoritative metadata without starting another runner."""
        if self._manager is None:
            return ()
        records = self._manager.store.runs()
        loaded = {
            str(record.id): PersistentJob.from_run_record(record)
            for record in records
            if "ase2sprkkr" in record.metadata
        }
        with self._lock:
            previous = self._jobs
            self._jobs = loaded
        changed = tuple(
            job_id
            for job_id in set(previous) | set(loaded)
            if previous.get(job_id) != loaded.get(job_id)
        )
        if notify:
            for job_id in changed:
                self._notify(job_id)
        return self.jobs()

    def job_changed(self, job_id: str) -> PersistentJob | None:
        """Reload one authoritative record after an external lifecycle event."""
        if self._manager is None:
            return None
        job_id = str(job_id)
        try:
            record = self._manager.store.get(job_id)
        except FileNotFoundError:
            with self._lock:
                existed = self._jobs.pop(job_id, None) is not None
            if existed:
                self._notify(job_id)
            return None

        if "ase2sprkkr" not in record.metadata:
            with self._lock:
                existed = self._jobs.pop(job_id, None) is not None
            if existed:
                self._notify(job_id)
            return None

        job = PersistentJob.from_run_record(record)
        changed = self._replace_cached_job(job)
        if changed:
            self._notify(job_id)
        return job

    def refresh(self) -> tuple[PersistentJob, ...]:
        """Recover interrupted submissions, refresh backend state, and reload."""
        if self._manager is None:
            return ()
        recover_submitting = getattr(self._manager, "recover_submitting", None)
        if callable(recover_submitting):
            for record in self._manager.store.runs():
                if _value(record.state) == "submitting":
                    recover_submitting(record)
        if self.supports_refresh:
            self._manager.refresh()
        return self.reload()

    def check_result_files(self, job_id: str) -> PersistentJob:
        if not self.supports_result_file_check:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot verify persistent result files."
            )
        record = self._manager.store.get(str(job_id))
        job = PersistentJob.from_run_record(record, result_files_verified=True)
        if self._replace_cached_job(job):
            self._notify(job.id)
        return job

    def attach(
        self,
        job_id: str,
        *,
        callback=None,
        output_listener=None,
    ) -> Any:
        """Attach to an active run or explicitly retry a failed download."""
        if not self.supports_attach:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot attach to persistent calculations."
            )
        job = self.job(str(job_id))
        if (
            job is not None
            and job.can_retry_download
            and not self.supports_retry_download
        ):
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot retry a failed download."
            )
        return attach_project_run(
            self._manager,
            str(job_id),
            callback=callback,
            output_listener=output_listener,
        )

    def retry_postprocessing(self, job_id: str) -> Any:
        """Reprocess persisted output files without executing the run again."""
        if not self.supports_retry_postprocessing:
            raise NotImplementedError("This runner cannot retry postprocessing")
        try:
            return retry_project_postprocessing(self._manager, str(job_id))
        finally:
            self.job_changed(str(job_id))

    def load_result(self, job_id: str) -> Any:
        if not self.supports_results:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot load persistent historical results."
            )
        result = load_project_result(self._manager, str(job_id))
        record = getattr(result, "run_record", None)
        if record is not None:
            job = PersistentJob.from_run_record(record, result_files_verified=True)
            if self._replace_cached_job(job):
                self._notify(job.id)
        return result

    def _replace_cached_job(self, job: PersistentJob) -> bool:
        with self._lock:
            previous = self._jobs.get(job.id)
            self._jobs[job.id] = job
        return previous != job

    def _refresh_after_recovery_failure(self, job_id: str) -> None:
        """Refresh cache after recovery without recursively attempting recovery."""
        try:
            record = self._manager.store.get(job_id)
        except (OSError, RuntimeError, ValueError):
            logger.exception(
                "Failed to refresh persistent run %s after recovery failure", job_id
            )
            return
        job = PersistentJob.from_run_record(record)
        if self._replace_cached_job(job):
            self._notify(job.id)

    def _recover_incomplete(self, jobs: tuple[PersistentJob, ...]) -> None:
        if not self.supports_attach:
            return
        for job in jobs:
            if job.state not in ("downloading", "postprocessing") or not job.attachable:
                continue
            try:
                self._recover(job.id)
            except Exception:  # noqa: BLE001 - persisted/backend recovery boundary
                logger.exception("Failed to recover persistent run %s", job.id)
                self._refresh_after_recovery_failure(job.id)

    def _recover(self, job_id: str) -> Any | None:
        # Reserve the identity before attach, then release the lock. A second
        # reload sees the sentinel and cannot attach the same recovering run.
        with self._lock:
            if job_id in self._recovery_runners:
                value = self._recovery_runners[job_id]
                return None if value is _RECOVERING else value
            self._recovery_runners[job_id] = _RECOVERING

        completed_synchronously = False

        def completed(_result: Any) -> None:
            nonlocal completed_synchronously
            completed_synchronously = True
            with self._lock:
                self._recovery_runners.pop(job_id, None)
            try:
                self.job_changed(job_id)
            except Exception:  # noqa: BLE001 - recovery completion boundary
                logger.exception(
                    "Recovered persistent run %s completed, but its metadata "
                    "could not be refreshed",
                    job_id,
                )

        try:
            runner = self.attach(job_id, callback=completed)
        except BaseException:
            with self._lock:
                if self._recovery_runners.get(job_id) is _RECOVERING:
                    self._recovery_runners.pop(job_id, None)
            raise

        with self._lock:
            if completed_synchronously or job_id not in self._recovery_runners:
                return None
            self._recovery_runners[job_id] = runner
        return runner
