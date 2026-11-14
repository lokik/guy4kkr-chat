"""Read and track ASE2SPRKKR persistent-run history behind a GUI-facing API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from kkrunner.backends.contracts import BackendCapability
from kkrunner.files.versions import file_digest
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
from guy4ase.gui.application.imported_project_results import (
    assignments, reference_id, reassign_references, remove_reference,
)
from guy4ase.gui.application.result_loading import load_result_file
from guy4ase.gui.application.run_file_deletion import (
    FileDeletionPlan, delete_local_files, plan_file_deletion,
    referenced_local_paths, referenced_remote_paths,
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
        return False, f"The {backend.name} backend does not support reattachment."
    if backend.name == "direct":
        local = record.execution.transport.is_local
        streams = (record.files.stdout, record.files.stderr)
        if not any(
            stream is not None and (
                stream.local_path if local else stream.remote_path
            )
            for stream in streams
        ):
            return (
                False,
                "Direct execution has no saved output or error file to monitor. "
                "Refresh statuses to check whether its process still exists.",
            )
    return True, None


def _cancellation_availability(record: Any, state: str) -> tuple[bool, str | None]:
    """Do not offer unverified process killing for legacy direct identities."""
    if state in _FINAL_STATES:
        return False, None
    token = record.execution.backend_id
    if token is None:
        return False, "This calculation has no saved process reference to cancel."
    backend = record.execution.backend.create()
    if BackendCapability.CANCEL not in backend.supports:
        return False, f"The {backend.name} backend cannot cancel persisted processes."
    if backend.name == "direct" and not token.startswith("direct:"):
        return (
            False,
            "This older direct run has no verified PID/start-time identity. "
            "It cannot be safely killed; you can remove its history record instead.",
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
    profile: str | None = None
    cancelable: bool = False
    cancel_unavailable_reason: str | None = None
    imported_path: str | None = None
    imported_key: str | None = None

    @property
    def started_at(self) -> str:
        return self.created_at

    @property
    def is_final(self) -> bool:
        return self.state in _FINAL_STATES or self.imported_path is not None

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
        cancelable, cancel_unavailable_reason = _cancellation_availability(record, state)
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
            profile=metadata.get("profile"),
            cancelable=cancelable,
            cancel_unavailable_reason=cancel_unavailable_reason,
        )

    @classmethod
    def from_external_reference(
        cls, key: str, project_id: str | None,
    ) -> "PersistentJob":
        """Project-visible result backed by a file, not a fabricated run."""
        path = Path(key.split("::", 1)[0])
        try:
            modified = path.stat().st_mtime
            timestamp = datetime.fromtimestamp(modified, timezone.utc).isoformat()
            files_state = "current"
        except OSError:
            timestamp = "1970-01-01T00:00:00+00:00"
            files_state = "missing"
        return cls(
            id=reference_id(key), state="imported", created_at=timestamp,
            updated_at=timestamp, task="—", directory=str(path.parent),
            dataset=path.name, target="External file", return_code=None,
            message=(
                "Imported output: original execution status and settings are unknown. "
                "Finish time is estimated from the file's last modification time."
            ),
            finished_at=timestamp if files_state == "current" else None,
            result_files_state=files_state,
            result_files_verified=True,
            project_id=project_id,
            imported_path=str(path),
            imported_key=key,
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

    def __init__(
        self, manager: Any | None = None, *, projects: ProjectRepository | None = None
    ) -> None:
        self._manager = manager
        self._projects = projects
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
    def supports_cancel(self) -> bool:
        return self.available and callable(getattr(self._manager, "cancel", None))

    @property
    def supports_forget(self) -> bool:
        return self.available and callable(getattr(self._manager, "forget", None))

    @property
    def supports_result_file_check(self) -> bool:
        return self.available

    @property
    def supports_reassignment(self) -> bool:
        return self._projects is not None or (
            self.available and callable(getattr(ProjectRepository, "reassign_runs", None))
        )

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
        if self._projects is not None:
            for key, project_id in assignments(self._projects).items():
                imported = PersistentJob.from_external_reference(key, project_id)
                loaded[imported.id] = imported
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
        if job_id.startswith("external:") and self._projects is not None:
            self.reload()
            return self.job(job_id)
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
        jobs = self.reload()
        # Recover any processing/downloading work that just became eligible
        # after a backend status refresh; never resubmit its calculation.
        self._recover_incomplete(jobs)
        return jobs

    def check_result_files(self, job_id: str) -> PersistentJob:
        job = self.job(str(job_id))
        if job is not None and job.imported_path is not None:
            self.reload()
            current = self.job(str(job_id))
            if current is None:
                raise FileNotFoundError(job_id)
            return current
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

    def cancel(self, job_id: str) -> PersistentJob | None:
        """Ask the backend to stop the native process, then refresh its record."""
        if not self.supports_cancel:
            raise NotImplementedError("This runner cannot cancel persistent jobs")
        try:
            self._manager.cancel(str(job_id))
        finally:
            self.job_changed(str(job_id))
        return self.job(str(job_id))

    def referenced_file_deletion(self, job_id: str) -> FileDeletionPlan:
        """Preview explicit local-file cleanup using authoritative persisted refs.

        Another run or import referencing a physical file always protects it.
        This includes references belonging to other applications in the store.
        """
        job_id = str(job_id)
        job = self.job(job_id)
        if job is None:
            raise KeyError(job_id)
        if not job.is_final:
            raise RuntimeError("Files of active or unknown calculations cannot be deleted")

        runs = tuple(self._manager.store.runs())
        imported = assignments(self._projects) if self._projects is not None else {}
        remote: tuple[str, ...] = ()
        if job.imported_path is not None:
            if job.imported_key not in imported:
                raise RuntimeError("The imported result reference has changed; refresh first")
            candidates = (job.imported_path,)
            ignored_key = job.imported_key
            ignored_run_id = None
        else:
            record = self._manager.store.get(job_id)
            if _value(record.state) not in _FINAL_STATES:
                raise RuntimeError("The calculation is no longer in a final state")
            directory = str(record.execution.directory.local)
            candidates = referenced_local_paths(record.files, directory)
            remote = (
                referenced_remote_paths(record.files)
                if not record.execution.transport.is_local else ()
            )
            ignored_key = None
            ignored_run_id = job_id

        other_paths = [
            path
            for record in runs if str(record.id) != ignored_run_id
            for path in referenced_local_paths(
                record.files, str(record.execution.directory.local)
            )
        ]
        other_paths.extend(
            key.split("::", 1)[0]
            for key in imported if key != ignored_key
        )
        return plan_file_deletion(
            candidates, other_references=other_paths, remote_references=remote,
        )

    def forget(
        self, job_id: str, *, force: bool = False, delete_files: bool = False,
        expected_files: tuple[str, ...] | None = None,
        expected_file_snapshots: tuple | None = None,
    ) -> Any:
        """Remove a history/reference entry; optionally delete reviewed local files.

        File cleanup is strictly opt-in and happens before removing the record so
        a file-removal failure leaves a retriable history entry.
        """
        job_id = str(job_id)
        job = self.job(job_id)
        if delete_files:
            if expected_files is None:
                raise ValueError("File deletion requires a confirmed file preview")
            plan = self.referenced_file_deletion(job_id)
            if tuple(expected_files) != plan.files:
                raise RuntimeError(
                    "Referenced files changed since confirmation; review them again"
                )
            if expected_file_snapshots is None or (
                tuple(expected_file_snapshots) != plan.snapshots
            ):
                raise RuntimeError(
                    "A file changed since the displayed last-modified times; "
                    "review the deletion list again"
                )
            delete_local_files(plan.files)

        if job is not None and job.imported_path is not None:
            if self._projects is None:
                raise RuntimeError("Imported project repository is unavailable")
            remove_reference(self._projects, job.id)
            self.reload()
            return job
        if not self.supports_forget:
            raise NotImplementedError("This runner cannot remove persistent history")
        removed = self._manager.forget(job_id, force=force)
        self.job_changed(job_id)
        return removed

    def retry_postprocessing(self, job_id: str) -> Any:
        """Reprocess persisted output files without executing the run again."""
        if not self.supports_retry_postprocessing:
            raise NotImplementedError("This runner cannot retry postprocessing")
        try:
            return retry_project_postprocessing(self._manager, str(job_id))
        finally:
            self.job_changed(str(job_id))

    def reassign_runs(
        self, projects: ProjectRepository, job_ids, project_id: str | None,
        *, expected_project_ids,
    ) -> None:
        """Move tracked runs through KKRunner and external references through their store."""
        if not self.supports_reassignment:
            raise NotImplementedError("Project reassignment is unavailable")
        imported_ids = tuple(
            job_id for job_id in job_ids
            if (job := self.job(job_id)) is not None and job.imported_path is not None
        )
        run_ids = tuple(job_id for job_id in job_ids if job_id not in imported_ids)
        if run_ids:
            records = projects.reassign_runs(
                run_ids, project_id, store=self._manager.store,
                expected_project_ids={key: expected_project_ids[key] for key in run_ids},
            )
            for record in records:
                self.job_changed(record.id)
        if imported_ids:
            reassign_references(
                projects, imported_ids, project_id,
                expected_project_ids={key: expected_project_ids[key] for key in imported_ids},
            )
            self.reload()

    def load_result(self, job_id: str) -> Any:
        job = self.job(str(job_id))
        if job is not None and job.imported_path is not None:
            expected_digest = job.imported_key.partition("::")[2]
            if expected_digest and file_digest(job.imported_path) != expected_digest:
                raise RuntimeError(
                    "The imported output file has changed since it was assigned. "
                    "Add the updated file again to capture its new version."
                )
            return load_result_file(job.imported_path).result
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
