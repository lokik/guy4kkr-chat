"""Reusable detached-structure workflows.

These helpers create or edit ``Atoms`` candidates without publishing anything to
``WorkspaceController``.  Workspace flows and nested structure dialogs can
therefore share the same file/database/editor boundaries.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase.io import read as ase_read
from ase.io.formats import ioformats
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ase2sprkkr_gui.gui.dialogs.structures.database import select_structure_prototype
from ase2sprkkr_gui.gui.dialogs.structures.element_assignment import select_site_elements
from ase2sprkkr_gui.gui.dialogs.structures.online_database import select_online_structure
from ase2sprkkr_gui.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from ase2sprkkr_gui.gui.misc.dialog_flow import chain_dialogs
from ase2sprkkr_gui.gui.misc.modal_task import run_modal_task


@dataclass(frozen=True)
class StructureCandidate:
    """A detached structure and optional file provenance."""

    atoms: Any
    source_path: Path | None = None


def structure_open_filter() -> str:
    """Return the ASE-backed file filter used for loading structures."""
    extensions = sorted(
        f"*.{extension}"
        for file_format in ioformats.values()
        for extension in (file_format.extensions or [])
    )
    return f"Structure Files ({' '.join(extensions)});;All Files (*)"


def choose_structure_file(
    parent: QWidget | None,
    *,
    title: str = "Load Structure File",
    chooser: Callable[..., tuple[str, str]] | None = None,
) -> Path | None:
    """Choose a structure file without loading or publishing it."""
    choose = chooser or QFileDialog.getOpenFileName
    file_path, _ = choose(parent, title, "", structure_open_filter())
    if not file_path:
        return None
    return Path(file_path).resolve()


def load_structure_candidate(
    file_path: str | Path,
    parent: QWidget | None,
    *,
    reader: Callable[[Path], Any] | None = None,
) -> StructureCandidate | None:
    """Load a detached structure and present reader failures at the UI boundary."""
    path = Path(file_path).resolve()
    read = reader or ase_read
    try:
        atoms = run_modal_task(
            parent,
            lambda: read(path),
            title="Loading Structure",
            label="Reading structure…",
        )
    except Exception as exc:  # noqa: BLE001 - ASE/backend readers vary
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load structure:\n{exc}",
        )
        return None
    return StructureCandidate(atoms=atoms, source_path=path)


def choose_structure_candidate(
    parent: QWidget | None,
    *,
    title: str = "Load Structure File",
    chooser: Callable[..., tuple[str, str]] | None = None,
    reader: Callable[[Path], Any] | None = None,
) -> StructureCandidate | None:
    """Choose and load a detached structure from a local file."""
    path = choose_structure_file(parent, title=title, chooser=chooser)
    if path is None:
        return None
    return load_structure_candidate(path, parent, reader=reader)


def create_structure_candidate(
    parent: QWidget | None,
    *,
    chain: Callable[..., Any] | None = None,
    spacegroup_selector: Callable[..., Any] | None = None,
    site_selector: Callable[..., Any] | None = None,
) -> StructureCandidate | None:
    """Create a detached periodic structure using the standard creation dialogs."""
    run_chain = chain or chain_dialogs
    select_group = spacegroup_selector or select_spacegroup
    select_sites = site_selector or select_site_elements
    atoms = run_chain(select_group, select_sites, parent=parent)
    return None if atoms is None else StructureCandidate(atoms)


def create_structure_from_database_candidate(
    parent: QWidget | None,
    *,
    chain: Callable[..., Any] | None = None,
    prototype_selector: Callable[..., Any] | None = None,
    spacegroup_selector: Callable[..., Any] | None = None,
    site_selector: Callable[..., Any] | None = None,
) -> StructureCandidate | None:
    """Create a detached structure from the prototype database workflow."""
    run_chain = chain or chain_dialogs
    select_prototype = prototype_selector or select_structure_prototype
    select_group = spacegroup_selector or select_spacegroup_from_prototype
    select_sites = site_selector or select_site_elements
    atoms = run_chain(
        select_prototype,
        select_group,
        select_sites,
        parent=parent,
    )
    return None if atoms is None else StructureCandidate(atoms)


def download_structure_candidate(
    parent: QWidget | None,
    *,
    selector: Callable[..., Any] | None = None,
) -> StructureCandidate | None:
    """Download a detached structure using the standard online database dialog."""
    select = selector or select_online_structure
    atoms = select(parent=parent)
    return None if atoms is None else StructureCandidate(atoms)
