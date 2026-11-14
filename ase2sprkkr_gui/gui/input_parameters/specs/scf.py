"""SCF guided setup pages and their parameter-driven presentation rules."""
from dataclasses import replace

from .schema import (
    Choice,
    GroupSpec,
    PageSpec,
    PresentationContext,
    TaskDialogSpec,
    energy_bound,
    field,
    main_energy_mesh_field,
    mirror,
)
from .shared import (
    ALG,
    CONVERGENCE_COLOR,
    ENERGY_COLOR,
    FULLPOT,
    GEOMETRY_COLOR,
    INITIAL_COLOR,
    ISTBRY,
    ITDEPT,
    KRMT,
    MIX,
    MODE,
    MODEL_COLOR,
    NITER,
    QUICK_COLOR,
    TOL,
    USEVMATT,
    VXC,
    _energy_grid_groups,
    _output_page,
    beyond_dft_enabled,
    beyond_dft_group,
    cpa_group,
    kkr_groups,
    magnetic_enabled,
    magnetism_group,
    orientation_group,
    points_integration_enabled,
    relativistic_scaling_group,
)


def broyden_enabled(context: PresentationContext) -> bool:
    """Broyden history settings apply only to the BROYDEN2 mixer."""
    return context.value("SCF", "ALG") == "BROYDEN2"


def build_spec(is_2d: bool) -> TaskDialogSpec:
    kpoints = (
        field("TAU", "NKTAB2D", "2D-region k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
        field("TAU", "NKTAB3D", "3D-region k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
    ) if is_2d else (
        field("TAU", "NKTAB", "Special k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
    )
    ne = main_energy_mesh_field("NE", "Energy-mesh points:", "integer", minimum=1, maximum=100000)
    return TaskDialogSpec("SCF Calculation Setup", (
        PageSpec("quick", "Quick setup", (
            GroupSpec("Common SCF settings", (
                mirror(VXC), mirror(NITER), mirror(TOL), mirror(ne), mirror(kpoints[0]), mirror(USEVMATT),
            )),
        ), QUICK_COLOR, quick=True),
        PageSpec("physical", "Physical model", (
            GroupSpec("Exchange-correlation and relativity", (VXC, MODE)),
            magnetism_group(),
            orientation_group(),
            GroupSpec("Potential shape and atomic radii", (
                FULLPOT,
                field(
                    "CONTROL", "KRWS", "Wigner-Seitz radii:", "choice",
                    choices=(Choice("Read from potential", 0), Choice("Calculate by scaling RMT", 1)),
                ),
                KRMT,
            )),
            beyond_dft_group(),
            relativistic_scaling_group(),
        ), MODEL_COLOR),
        PageSpec("initial", "Initial state", (
            GroupSpec("Starting potential", (USEVMATT,)),
            GroupSpec("Initial charge density", (
                field("SCF", "QION", "Ionic charges by atomic type:", "literal"),
                field("SCF", "QIONSCL", "Ionic-charge scale:", "real",
                      minimum=0., maximum=10., step=.01, nullable=True),
            ), note="Charges are ordered by atomic type in the potential file, not by site. Leave empty to use defaults."),
            GroupSpec("Initial magnetisation density", (
                field("SCF", "MSPIN", "Spin moments by atomic type:", "literal", enabled_when=magnetic_enabled),
            ), note="One value per atomic type, in potential-file order. Leave empty to use defaults."),
        ), INITIAL_COLOR),
        PageSpec("convergence", "SCF convergence", (
            GroupSpec("Stopping criteria", (NITER, TOL)),
            GroupSpec("Potential mixing", (
                ALG, MIX,
                replace(ISTBRY, enabled_when=broyden_enabled),
                replace(ITDEPT, enabled_when=broyden_enabled),
                field("SCF", "MIXOP", "Orbital-potential mixing:", "real",
                      minimum=.001, maximum=1., step=.01, decimals=4, nullable=True,
                      enabled_when=beyond_dft_enabled),
            )),
            GroupSpec("Fermi energy", (
                field("SCF", "EFGUESS", "Initial Fermi-energy guess:", "energy",
                      minimum=-100., maximum=100., step=.01, nullable=True),
            )),
            cpa_group(),
        ), CONVERGENCE_COLOR),
        PageSpec("energy", "Energy grids", _energy_grid_groups(ne) + (
            GroupSpec("Energy range", (
                energy_bound("EMIN", "Minimum energy:"),
                field("ENERGY", "ImE", "Imaginary energy:", "energy", minimum=0.),
            )),
        ), ENERGY_COLOR),
        PageSpec("kkr", "KKR & integration", kkr_groups(is_2d), GEOMETRY_COLOR),
        _output_page(scf=True),
    ), intro=(
        "Configure the most useful task parameters. Quick setup mirrors a small selection from the detailed "
        "categories; all remaining parameters are available in Expert settings."
        + (" One SCF run for a 2D system converges the bulk regions and then the interaction zone."
           if is_2d else "")
    ))
