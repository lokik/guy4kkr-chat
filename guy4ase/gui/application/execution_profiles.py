"""Qt-independent execution-profile adaptation and persistence."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any

from ase2sprkkr import config
from ase2sprkkr.sprkkr.profile import resolve_sprkkr_profile

_DEFAULT_PROFILE_VALUES = {"executor": "local", "mpi": "auto", "mpi_warning": True}


@dataclass
class ProfileDraft:
    """Editable snapshot of one execution profile."""

    name: str
    values: dict[str, Any]
    read_only: bool = False


def profile_values(profile: Any) -> dict[str, Any]:
    """Return the explicitly configured, user-editable values of a profile."""
    values = dict(profile.as_dict(only_changed="explicit", generated=False) or {})
    values.pop("command", None)
    return values


def backend_kind(profile: Any) -> str:
    """Return the UI execution kind represented by a resolved runtime profile."""
    executor = profile.executor or "local"
    if executor == "ssh" and profile.backend_config.name == "psij":
        return "ssh-psij"
    return str(executor)


def draft_kind(values: dict[str, Any]) -> str:
    """Return the UI execution kind represented by persisted profile values."""
    executor = values.get("executor") or "local"
    backend = values.get("backend")
    if executor == "ssh" and (
        backend == "psij"
        or (backend is None and (
            values.get("psij_backend") is not None
            or values.get("psij_url") is not None
        ))
    ):
        return "ssh-psij"
    return str(executor)


def kind_label(kind: str) -> str:
    """Return the user-facing label for an execution kind."""
    return {
        "local": "Local computer",
        "ssh": "Remote computer (SSH)",
        "psij": "Workload manager (PSI/J)",
        "ssh-psij": "Remote workload manager (SSH + PSI/J)",
    }.get(kind, kind)


def profile_description(name: str | None, *, configuration: Any | None = None) -> str:
    """Return a short user-facing description of one resolved profile."""
    profile = resolve_sprkkr_profile(name, configuration=configuration)
    kind = backend_kind(profile)
    if kind == "local":
        where = "Local execution"
    elif kind == "ssh":
        where = f"SSH to {profile.host or '(host not set)'}"
    elif kind == "ssh-psij":
        backend = profile.psij_backend or "slurm"
        where = f"SSH to {profile.host or '(host not set)'} + PSI/J ({backend})"
    elif kind == "psij":
        where = f"PSI/J ({profile.psij_backend or 'slurm'})"
    else:
        where = f"{profile.executor} execution"

    if kind in {"local", "ssh"}:
        mode = "supervised" if profile.backend_config.name == "process" else "direct"
        where = f"{where} · {mode}"

    mpi = profile.mpi
    if mpi is False:
        mpi_text = "MPI disabled"
    elif mpi is True:
        mpi_text = "MPI enabled"
    elif mpi is None or mpi == "auto":
        mpi_text = "MPI automatic"
    elif isinstance(mpi, int):
        mpi_text = f"MPI: {mpi} processes"
    elif isinstance(mpi, (tuple, list)):
        mpi_text = "MPI: " + shlex.join(str(item) for item in mpi)
    else:
        mpi_text = f"MPI: {mpi}"

    executable = profile.executable_dir or "PATH"
    if profile.executable_suffix:
        executable = f"{executable} (suffix {profile.executable_suffix})"
    return f"{where} · {mpi_text}\nExecutables: {executable}"


class ExecutionProfileStore:
    """Persistence boundary for ASE2SPRKKR execution profiles."""

    def __init__(self, configuration: Any | None = None) -> None:
        self._config = config if configuration is None else configuration

    @property
    def reserved_names(self) -> frozenset[str]:
        """Names that the backend reserves for special profile views."""
        return frozenset(str(name) for name in self._config.profiles.reserved_names)

    def drafts(self) -> dict[str, ProfileDraft]:
        """Load editable snapshots of all configured profiles."""
        return {
            str(name): ProfileDraft(
                str(name),
                profile_values(profile),
                bool(profile.read_only),
            )
            for name, profile in self._config.profiles.items()
        }

    def names(self) -> tuple[str, ...]:
        """Return configured profile names in backend order."""
        return tuple(str(name) for name in self._config.profiles)

    def resolved_name(self, name: str | None) -> str | None:
        """Resolve ``None`` to the configured default profile name."""
        return self._config.profiles.resolve_name(name)

    def describe(self, name: str | None) -> str:
        """Describe a profile using this store's configuration context."""
        return profile_description(name, configuration=self._config)

    def save(self, drafts: dict[str, ProfileDraft]) -> None:
        """Persist mutable drafts and keep the default profile valid."""
        editable = {
            name: draft.values
            for name, draft in drafts.items()
            if not draft.read_only
        }
        self._config.profiles.set(editable)
        default_profile = self._config.default_profile()
        if default_profile is not None and default_profile not in drafts:
            self._config.default_profile.set(None)
        self._config.save_user_preferences()


class ExecutionProfileEditor:
    """Qt-independent editing model for a set of execution profiles."""

    def __init__(self, store: ExecutionProfileStore) -> None:
        self._store = store
        self.drafts = store.drafts()

    def add(self, name: str) -> ProfileDraft:
        name = name.strip()
        if not name or name in self._store.reserved_names or name in self.drafts:
            raise ValueError(f"Profile {name!r} already exists or is reserved.")
        draft = ProfileDraft(name, dict(_DEFAULT_PROFILE_VALUES))
        self.drafts[name] = draft
        return draft

    def delete(self, name: str) -> None:
        draft = self.drafts[name]
        if draft.read_only:
            raise ValueError(f"Profile {name!r} is read-only.")
        del self.drafts[name]

    def save(self) -> None:
        self._store.save(self.drafts)
