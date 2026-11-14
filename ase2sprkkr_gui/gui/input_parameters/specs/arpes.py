"""ARPES guided setup pages."""
from .schema import (
    Choice,
    GroupSpec,
    PageSpec,
    TaskDialogSpec,
    energy_bound,
    field,
    main_energy_mesh_field,
    mirror,
)
from .shared import (
    ADVANCED_COLOR,
    CONVERGENCE_COLOR,
    ENERGY_COLOR,
    GEOMETRY_COLOR,
    MODEL_COLOR,
    QUICK_COLOR,
    SPECIAL_COLOR,
    _output_page,
    nktab,
    nl,
)


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    ephot = field("SPEC_PH", "EPHOT", "Photon energy (eV):", "real", minimum=0., maximum=100000., step=1.)
    pol = field("SPEC_PH", "POL_P", "Light polarization:", "choice", choices=tuple(
        Choice(value, value) for value in ("P", "S", "C+", "C-")
    ))
    arpes_emin = energy_bound("EMIN", "Minimum energy:")
    arpes_emax = energy_bound("EMAX", "Maximum energy:")
    arpes_ne = main_energy_mesh_field("NE", "Energy points:", "integer", minimum=1, maximum=10000)
    miller = field("TASK", "MILLER_HKL", "Surface Miller indices [h, k, l]:", "literal")
    arpes = TaskDialogSpec("ARPES Calculation Setup", (
        PageSpec("quick", "Quick setup", (GroupSpec("Common ARPES settings", (
            mirror(ephot), mirror(pol), mirror(arpes_emin), mirror(arpes_emax), mirror(arpes_ne), mirror(miller),
        )),), QUICK_COLOR, quick=True),
        PageSpec("photon", "Photon", (GroupSpec("Incoming photon", (
            ephot,
            field("SPEC_PH", "THETA", "Incidence theta (deg):", "real", minimum=-360., maximum=360., step=1.),
            field("SPEC_PH", "PHI", "Incidence phi (deg):", "real", minimum=-360., maximum=360., step=1.),
            pol,
        )),), SPECIAL_COLOR),
        PageSpec("detector", "Electron detector", (GroupSpec("Angular scan", (
            field("SPEC_EL", "THETA", "Theta scan [start, end] (deg):", "literal"),
            field("SPEC_EL", "NT", "Theta samples:", "integer", minimum=1, maximum=100000),
            field("SPEC_EL", "PHI", "Phi scan [start, end] (deg):", "literal"),
            field("SPEC_EL", "NP", "Phi samples:", "integer", minimum=1, maximum=100000),
            field("SPEC_EL", "SPOL", "Spin-polarization mode:", "integer", minimum=0, maximum=10),
        )),), GEOMETRY_COLOR),
        PageSpec("energy", "Energy mesh", (GroupSpec("Energy range and broadening", (
            arpes_emin, arpes_emax, arpes_ne,
            field("ENERGY", "EWORK_EV", "Work function (eV):", "real", minimum=0., maximum=100., step=.1),
            field("ENERGY", "IMV_INI_EV", "Initial-state broadening (eV):", "real", minimum=0., maximum=100., step=.01),
            field("ENERGY", "IMV_FIN_EV", "Final-state broadening (eV):", "real", minimum=0., maximum=100., step=.1),
        )),), ENERGY_COLOR),
        PageSpec("surface", "Surface geometry", (GroupSpec("Surface", (
            miller,
            field("TASK", "IQ_AT_SURF", "Surface site:", "integer", minimum=1, maximum=999999),
            field("SPEC_STR", "N_LAYDBL", "Principal layers [left, right]:", "literal"),
            field("SPEC_STR", "N_LAYER", "Surface layers:", "integer", minimum=1, maximum=10000),
        )),), MODEL_COLOR),
        PageSpec("momentum", "Momentum map", (GroupSpec("Optional momentum map", tuple(
            field("SPEC_EL", name, label, "literal") for name, label in (
                ("KA", "Map origin [kx, ky]:"), ("K1", "First map vector [kx, ky]:"),
                ("K2", "Second map vector [kx, ky]:"), ("NK1", "Points along first vector:"),
                ("NK2", "Points along second vector:"), ("PSPIN", "Spin projection [x, y, z]:"),
            )
        )),), ADVANCED_COLOR),
        PageSpec("accuracy", "Numerical accuracy", (GroupSpec("Integration and basis", (nktab, nl)),), CONVERGENCE_COLOR),
        _output_page(include_hff=False),
    ))

    return arpes
