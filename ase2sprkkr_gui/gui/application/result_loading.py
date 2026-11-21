"""Interpret calculation results and result files without changing a workspace."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase2sprkkr import Potential, TaskResult
from ase2sprkkr.outputs.file_provenance import result_file_manifest, result_file_version
from ase2sprkkr.potentials.potentials import PotentialFileChanged

from ase2sprkkr_gui.gui.application.potential_version import PotentialFileVersion


class PotentialVersionChanged(RuntimeError):
    """The potential file no longer matches the version approved by the user."""


@dataclass(frozen=True)
class FileBackedInput:
    """Parsed structure and all potential input versions verified at launch."""

    atoms: Any
    input_versions: tuple[PotentialFileVersion, ...]

    @property
    def potential_version(self) -> PotentialFileVersion:
        # The cluster potential is the primary structural state for embedding.
        return self.input_versions[-1]


@dataclass(frozen=True)
class LoadedResult:
    """A result whose filesystem references have already been interpreted.

    ``output_path`` and ``potential_path`` are provenance file locations.
    The authoritative physical potential, when successfully loaded, is attached
    to ``atoms``. A missing referenced potential is different: reconstructing
    atoms depends on it, so ``potential_error`` contains ``FileNotFoundError``.

    ``persistent_ref`` is the stable ASE2SPRKKR persistent-run identity when
    this result originated from a persistent execution. It deliberately does
    not duplicate the backend-specific run reference.
    """

    result: TaskResult
    output_path: Path | None
    potential_path: Path | None
    atoms: Any | None
    potential_error: Exception | None
    directory: str | None
    input_parameters: Any | None = None
    input_parameters_error: Exception | None = None
    persistent_ref: str | None = None
    file_backed_input: FileBackedInput | None = None
    output_potential_version: PotentialFileVersion | None = None
    source_versions: tuple[PotentialFileVersion, ...] = ()


def load_potential_atoms(file_path: str | Path, *, embedding_host=None) -> Any:
    """Read a periodic POTFIL or CLUPOT, preserving native radial information."""
    path = Path(file_path).resolve()
    if Potential.is_cluster_file(path):
        if embedding_host is None:
            raise ValueError(
                f"Embedded cluster {path} requires a host SPR-KKR Potential"
            )
        from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
        potential = ClusterPotential.from_file(path, host=embedding_host)
    else:
        potential = Potential.from_file(str(path), check_file_unchanged=True)
    atoms = potential.atoms
    if atoms is None:
        raise ValueError(f"Potential file contains no structure: {path}")
    return atoms


def require_potential_version_current(version: PotentialFileVersion) -> None:
    """Reject a POTFIL path that no longer contains ``version``."""
    current = version.current()
    if not current.available or current != version:
        raise PotentialVersionChanged(
            f"Potential file changed after it was presented: {version.path}"
        )


def load_potential_version(
    version: PotentialFileVersion, *, embedding_host=None
) -> Any:
    """Load a versioned POTFIL or CLUPOT, rejecting pre/read/post races."""
    require_potential_version_current(version)
    try:
        atoms = load_potential_atoms(
            version.path, embedding_host=embedding_host
        )
    except PotentialFileChanged as exc:
        raise PotentialVersionChanged(
            f"Potential file changed while it was being read: {version.path}"
        ) from exc

    after = version.current()
    if not after.available or after != version:
        raise PotentialVersionChanged(
            f"Potential file changed while it was being read: {version.path}"
        )
    return atoms


def load_result_file(file_path: str | Path) -> LoadedResult:
    """Parse an external result and all usable referenced result files."""
    path = Path(file_path).resolve()
    result = TaskResult.from_file(path)
    return load_result(
        result,
        fallback_directory=path.parent,
        output_fallback=path,
    )


def load_result(
    result: TaskResult,
    *,
    fallback_directory: str | Path | None,
    output_fallback: str | Path | None = None,
    persistent_ref: str | None = None,
    embedding_host=None,
) -> LoadedResult:
    """Resolve result files for an already constructed calculation result."""
    output, potential = _result_files(result, fallback_directory)
    manifest = result_file_manifest(result)
    if output is None and output_fallback is not None:
        output = Path(output_fallback).resolve()

    # Native embedded output identifies its host through CONTROL.POTFIL.
    # Capture that file before parsing the CLUPOT, then verify the very same
    # version afterwards. Do not guess a host from neighboring filenames.
    host_version = None
    host_version_error = None
    if potential is not None and getattr(result, "is_embedded", False):
        try:
            host_path = result.host_potential_filename
        except (AttributeError, KeyError, ValueError):
            pass  # Without native input settings, host provenance is unknown.
        else:
            host_path = _resolve_path(host_path, result, fallback_directory)
            if manifest is not None:
                # A historical manifest is authoritative; never attribute
                # today's host bytes to a previous run.
                host_version = manifest.input_version(host_path)
            else:
                try:
                    host_version = PotentialFileVersion.capture(
                        host_path, require_digest=True,
                    )
                except OSError as exc:
                    host_version_error = exc

    try:
        if potential is not None and manifest is not None:
            result.require_current_file(potential)
    except OSError as exc:
        atoms, potential_error = None, exc
    else:
        if getattr(result, "is_embedded", False) and potential is not None:
            # The result's cluster potential loader resolves its own native
            # host POTFIL; it must not be treated as a periodic potential.
            try:
                atoms, potential_error = result.potential.atoms, None
            except Exception as exc:  # noqa: BLE001 - corrupted native file
                atoms, potential_error = None, exc
        else:
            atoms, potential_error = _load_potential(
                potential, embedding_host=embedding_host
            )
        if atoms is not None and manifest is not None:
            try:
                result.require_current_file(potential)
            except OSError as exc:
                atoms, potential_error = None, exc
    if atoms is not None and host_version_error is not None:
        atoms, potential_error = None, host_version_error
    if atoms is not None and host_version is not None and not host_version.is_current():
        atoms, potential_error = None, PotentialVersionChanged(
            f"Host potential changed while the embedded result was loaded: {host_version.path}"
        )
    source_versions = (
        (host_version,) if atoms is not None and host_version is not None else ()
    )
    input_parameters, input_parameters_error = _load_input_parameters(result)
    directory = str(output.parent.resolve()) if output is not None else None
    return LoadedResult(
        result=result,
        output_path=output,
        potential_path=potential,
        atoms=atoms,
        potential_error=potential_error,
        directory=directory,
        input_parameters=input_parameters,
        input_parameters_error=input_parameters_error,
        persistent_ref=persistent_ref,
        output_potential_version=(
            result_file_version(result, potential)
            if potential is not None and manifest is not None else None
        ),
        source_versions=source_versions,
    )


def load_companion_scf_result(loaded: LoadedResult) -> LoadedResult | None:
    """Try to find the SCF output that produced a non-SCF result's potential.

    Same-directory proximity alone is not enough: the SCF output must reference
    exactly the potential used by the selected result. An absent, unreadable or
    unrelated output is never an error for the selected result.
    """
    if loaded.output_path is None or loaded.potential_path is None:
        return None
    if str(getattr(loaded.result, "task_name", "")).casefold() == "scf":
        return None

    directory = loaded.output_path.parent
    target_potential = loaded.potential_path.resolve()
    try:
        candidates = sorted(
            (path for path in directory.iterdir()
             if path != loaded.output_path and path.is_file()
             and path.suffix.lower() in {".out", ".log", ".txt"}),
            key=lambda path: ("scf" not in path.stem.casefold(), path.name.casefold()),
        )
    except OSError:
        return None

    for path in candidates:
        try:
            result = TaskResult.from_file(path)
            if str(getattr(result, "task_name", "")).casefold() != "scf":
                continue
            candidate = load_result(
                result, fallback_directory=directory, output_fallback=path
            )
            if candidate.potential_path == target_potential:
                return candidate
        except Exception:  # noqa: BLE001 - optional, possibly corrupt output
            continue
    return None


def _load_input_parameters(result: Any) -> tuple[Any | None, Exception | None]:
    try:
        return getattr(result, "input_parameters", None), None
    except Exception as exc:  # noqa: BLE001 - parser failures are data
        return None, exc


def _registered_path(result: Any, key: str) -> Path | None:
    files = getattr(result, "files", None)
    if files is None or key not in files:
        return None
    value = result.path_to(key)
    return Path(value) if value else None


def _resolve_path(
    path: str | Path | None,
    result: Any,
    fallback_directory: str | Path | None,
) -> Path | None:
    if not path:
        return None
    resolved = Path(path)
    if not resolved.is_absolute():
        base = getattr(result, "directory", None) or fallback_directory
        if base:
            resolved = Path(base) / resolved
    return resolved.resolve()


def _result_files(
    result: Any,
    fallback_directory: str | Path | None,
) -> tuple[Path | None, Path | None]:
    output = _registered_path(result, "output")
    if output is None:
        output = getattr(result, "output_file", None)
    output = _resolve_path(output, result, fallback_directory)

    # For embedded tasks (including DOS), the potential that defines the
    # calculation structure is POTFIL_CLU, not the periodic host POTFIL. The
    # latter may be registered as FILES["potential"], but restoring it as a
    # result state would silently turn the cluster into a bulk structure.
    embedded = getattr(result, "is_embedded", False)
    potential = None
    if embedded:
        try:
            potential = getattr(result, "potential_filename", None)
        except (AttributeError, KeyError, ValueError):
            pass
        if potential is None:
            potential = _registered_path(result, "converged")
        # Never fall back to the host's FILES["potential"] for an embedded
        # result: without CLUPOT the result has no reusable cluster state.
    else:
        potential = _registered_path(result, "converged")
        if potential is None:
            # The FILES entry named "potential" is the *input* POTFIL for SCF.
            # ScfResult.potential_filename, in contrast, points to the newly
            # produced POTFIL (_new). Never adopt the input as SCF output.
            try:
                is_scf = str(getattr(result, "task_name", "")).casefold() == "scf"
            except (AttributeError, KeyError, ValueError):
                is_scf = False
            if is_scf:
                try:
                    potential = getattr(result, "potential_filename", None)
                except (AttributeError, KeyError, ValueError):
                    potential = None
        if potential is None:
            potential = _registered_path(result, "potential")
        if potential is None:
            try:
                potential = getattr(result, "potential_filename", None)
            except (AttributeError, KeyError, ValueError):
                potential = None
    potential = _resolve_path(potential, result, fallback_directory)
    return output, potential


def _load_potential(
    potential: Path | None,
    *,
    embedding_host=None,
) -> tuple[Any | None, Exception | None]:
    if potential is None:
        return None, None
    if not potential.exists():
        return None, FileNotFoundError(
            f"Referenced potential file does not exist: {potential}"
        )
    if not potential.is_file():
        return None, IsADirectoryError(
            f"Referenced potential is not a file: {potential}"
        )
    try:
        if embedding_host is not None:
            return load_potential_atoms(potential, embedding_host=embedding_host), None
        return load_potential_atoms(potential), None
    except Exception as exc:  # noqa: BLE001 - parser failures are data
        return None, exc
