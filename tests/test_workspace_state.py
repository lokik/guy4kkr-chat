from types import SimpleNamespace

from ase import Atoms
from ase.build import bulk
from ase2sprkkr import SPRKKRAtoms
from ase2sprkkr.sprkkr.build import semiinfinite_system

from guy4ase.gui.application.workspace import (
    Generation,
    OptimisticLocked,
    StructureState,
    WorkspaceState,
)


def _scf_atoms(status=None, *, converged=False):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms.sprkkr_is_scf_converged = lambda: converged
    if status is not None:
        atoms._potential = SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status)
        )
    return atoms


def test_optimistic_locked_changes_only_for_current_generation():
    locked = OptimisticLocked("old")
    generation = locked.generation

    assert locked.change("new", generation)
    assert locked.value == "new"
    assert locked.generation == generation.next()

    assert not locked.change("stale", generation)
    assert locked.value == "new"
    assert locked.generation == generation.next()

    locked.force_change("forced")
    assert locked.value == "forced"
    assert locked.generation == Generation(2)


def test_workspace_owns_independently_revisioned_values():
    workspace = WorkspaceState(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory="run",
        active_project_id="project",
    )

    assert workspace.structure.value.atoms.get_chemical_symbols() == ["Fe"]
    assert workspace.context.directory.value == "run"
    assert workspace.context.active_project_id.value == "project"
    assert workspace.structure.generation == Generation()
    assert workspace.input_parameters.generation == Generation()
    assert workspace.context.directory.generation == Generation()
    assert workspace.context.active_project_id.generation == Generation()
    assert not hasattr(workspace, "generation")


def test_structure_kind_is_derived_from_structure_state_atoms():
    state = StructureState()
    assert state.structure_kind() is None

    state = StructureState(Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True))
    assert state.structure_kind() == "3d"

    state = StructureState(semiinfinite_system(bulk("Fe", "bcc", a=2.8), (0, 0)))
    assert state.structure_kind() == "2d"

    state = StructureState(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=(True, False, False))
    )
    assert state.structure_kind() == "unknown"


def test_scf_status_and_convergence_are_derived_separately():
    state = StructureState(_scf_atoms("ITR-L-BULK"))
    assert state.scf_status() == "ITR-L-BULK"
    assert not state.is_scf_converged()

    state = StructureState(_scf_atoms(" START ", converged=True))
    assert state.scf_status() == "START"
    assert state.is_scf_converged()

    state = StructureState(_scf_atoms(converged=True))
    assert state.scf_status() is None
    assert state.is_scf_converged()

    state = StructureState(Atoms("Fe"))
    assert state.scf_status() is None
    assert not state.is_scf_converged()


def test_pending_restart_reports_start_without_mutating_structure_potential():
    atoms = Atoms("Fe")
    state = StructureState(atoms=atoms, restarted=True)

    assert state.scf_status() == "START"
    assert not state.is_scf_converged()
    assert state.atoms is atoms
