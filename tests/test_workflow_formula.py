import numpy as np
from ase import Atoms

from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner


class _Workspace:
    def __init__(self, atoms):
        self.atoms = atoms

    def structure_kind(self):
        return "3d"

    def can_build_2d(self):
        return False

    def scf_status(self):
        return None

    def is_scf_converged(self):
        return False

    def empty_spheres_action(self):
        return None

    def structure_change_requires_scf_restart(self):
        return False


def test_workflow_subtitle_uses_site_aware_structure_formula():
    atoms = Atoms("CuAu", cell=(3.0, 3.0, 3.0), pbc=True)
    atoms.new_array("spacegroup_kinds", np.array([0, 1]))
    atoms.info["occupancy"] = {
        "0": {"Cu": 0.5, "Zn": 0.5},
        "1": {"Au": 1.0},
    }

    plan = WorkflowPlanner().for_workspace(_Workspace(atoms))

    assert plan.subtitle.startswith("Current structure: (Cu|Zn)Au  •  ")
