"""DOS guided setup pages."""
from .schema import GroupSpec, PageSpec, TaskDialogSpec, energy_bound, field, main_energy_mesh_field, mirror
from .shared import (
    CONVERGENCE_COLOR,
    ENERGY_COLOR,
    QUICK_COLOR,
    _output_page,
    nktab,
    nl,
)


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    emin_dos = energy_bound("EMIN", "Minimum energy:")
    emax_dos = energy_bound("EMAX", "Maximum energy:")
    ne_dos = main_energy_mesh_field("NE", "Energy points:", "integer", minimum=1, maximum=10000)
    dos = TaskDialogSpec("DOS Calculation Setup", (
        PageSpec("quick", "Quick setup", (GroupSpec("Common DOS settings", (
            mirror(emin_dos), mirror(emax_dos), mirror(ne_dos), mirror(nktab),
        )),), QUICK_COLOR, quick=True),
        PageSpec("energy", "Energy mesh", (GroupSpec("Energy range", (
            emin_dos, emax_dos, ne_dos,
            field("ENERGY", "ImE", "Imaginary broadening:", "energy", minimum=0.),
        )),), ENERGY_COLOR),
        PageSpec("accuracy", "Numerical accuracy", (GroupSpec("Integration and basis", (nktab, nl)),), CONVERGENCE_COLOR),
        _output_page(),
    ))

    return dos
