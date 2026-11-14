"""XAS guided setup pages."""
from .schema import GroupSpec, PageSpec, TaskDialogSpec, field, main_energy_mesh_field, mirror
from .shared import (
    CONVERGENCE_COLOR,
    ENERGY_COLOR,
    GEOMETRY_COLOR,
    GRID,
    QUICK_COLOR,
    SPECIAL_COLOR,
    _output_page,
    nktab,
    nl,
)


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    xas_it = field("TASK", "IT", "Atomic type:", "integer", minimum=1, maximum=999)
    xas_cl = field("TASK", "CL", "Core level:", "text")
    xas_emax = field("ENERGY", "EMAX", "Maximum energy:", "energy")
    xas_ne = main_energy_mesh_field("NE", "Energy points:", "integer", minimum=1, maximum=10000)
    xas = TaskDialogSpec("XAS Calculation Setup", (
        PageSpec("quick", "Quick setup", (GroupSpec("Common XAS settings", (
            mirror(xas_it), mirror(xas_cl), mirror(xas_emax), mirror(xas_ne),
        )),), QUICK_COLOR, quick=True),
        PageSpec("edge", "Absorption edge", (GroupSpec("Absorbing atom and edge", (xas_it, xas_cl)),), SPECIAL_COLOR),
        PageSpec("orientation", "Light orientation", (GroupSpec("Electric-field orientation", (
            field("TASK", "FRAMETET", "Polar angle (deg):", "real", minimum=-360., maximum=360., step=1.),
            field("TASK", "FRAMEPHI", "Azimuth (deg):", "real", minimum=-360., maximum=360., step=1.),
        )),), GEOMETRY_COLOR),
        PageSpec("energy", "Energy mesh", (GroupSpec("Energy contour", (
            xas_emax, xas_ne,
            GRID,
            field("ENERGY", "ImE", "Broadening:", "energy", minimum=0.),
        )),), ENERGY_COLOR),
        PageSpec("accuracy", "Numerical accuracy", (GroupSpec("Integration and basis", (nktab, nl)),), CONVERGENCE_COLOR),
        _output_page(),
    ))

    return xas
