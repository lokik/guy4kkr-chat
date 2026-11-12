"""Interpret calculation results and result files without changing a workspace."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase2sprkkr import Potential, TaskResult
from ase2sprkkr.potentials.potentials import PotentialFileChanged

from guy4ase.gui.application.potential_version import PotentialFileVersion


class PotentialVersionChanged(RuntimeError):
    """The potential file no longer matches the version approved by the user."""


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


def load_potential_atoms(file_path: str | Path) -> Any:
    """Load one stable POT file and return the atoms owned by that potential."""
    path = Path(file_path).resolve()
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


def load_potential_version(version: PotentialFileVersion) -> Any:
    """Load exactly ``version`` of a POTFIL, rejecting pre/read/post races."""
    require_potential_version_current(version)
    try:
        atoms = load_potential_atoms(version.path)
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
) -> LoadedResult:
    """Resolve result files for an already constructed calculation result."""
    output, potential = _result_files(result, fallback_directory)
    if output is None and output_fallback is not None:
        output = Path(output_fallback).resolve()
    atoms, potential_error = _load_potential(potential)
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
    )


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

    potential = _registered_path(result, "converged")
    if potential is None:
        potential = _registered_path(result, "potential")
    if potential is None:
        try:
            potential = getattr(result, "potential_filename", None)
        except ValueError:
            potential = None
    potential = _resolve_path(potential, result, fallback_directory)
    return output, potential


def _load_potential(
    potential: Path | None,
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
        return load_potential_atoms(potential), None
    except Exception as exc:  # noqa: BLE001 - parser failures are data
        return None, exc
