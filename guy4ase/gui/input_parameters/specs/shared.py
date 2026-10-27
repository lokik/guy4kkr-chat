"""Shared fields, colors and page groups for task definitions."""
from dataclasses import replace

from .schema import (
    Choice,
    FieldPlacement,
    GroupSpec,
    PageSpec,
    PresentationContext,
    field,
    main_energy_mesh_field,
)

QUICK_COLOR = "#2878b8"
MODEL_COLOR = "#27836b"
CONVERGENCE_COLOR = "#6f8f32"
INITIAL_COLOR = "#7655a6"
ENERGY_COLOR = "#c27622"
OUTPUT_COLOR = "#a84e64"
GEOMETRY_COLOR = "#536f9e"
SPECIAL_COLOR = "#8a5b9f"
ADVANCED_COLOR = "#607d8b"


VXC = field("SCF", "VXC", "Exchange-correlation:", "keyword")
MODE = field(
    "MODE", "MODE", "Relativity and spin:", "keyword",
    choices=(Choice("Fully relativistic (default)", None),),
)
NONMAG = field("CONTROL", "NONMAG", "Non-magnetic calculation:", "boolean")
FULLPOT = field("SCF", "FULLPOT", "Full potential:", "boolean")
KRMT = field("CONTROL", "KRMT", "Muffin-tin radius scheme:", "keyword", descriptions=True,
             choices=(Choice("Automatic (not specified)", None),))
USEVMATT = field(
    "SCF", "USEVMATT", "Starting guess:", "choice",
    choices=(
        Choice("Atomic charge density (recommended)", False),
        Choice("Mattheiss potential", True),
    ),
)
NITER = field("SCF", "NITER", "Maximum iterations:", "integer", minimum=1, maximum=2000, step=10)
TOL = field("SCF", "TOL", "Convergence tolerance:", "real", minimum=1e-10, maximum=1.0,
            step=1e-6, decimals=10)
ALG = field("SCF", "ALG", "Mixing algorithm:", "keyword")
MIX = field("SCF", "MIX", "Mixing factor:", "real", minimum=.001, maximum=1., step=.01, decimals=4)
ISTBRY = field("SCF", "ISTBRY", "Start Broyden after:", "integer", minimum=1, maximum=100)
ITDEPT = field("SCF", "ITDEPT", "Broyden history length:", "integer", minimum=1, maximum=500)
BZINT = field("TAU", "BZINT", "BZ integration:", "keyword")
KKRMODE = field(
    "TAU", "KKRMODE", "KKR representation:", "keyword",
    choices=(Choice("Default", None),),
)
GRID = main_energy_mesh_field("GRID", "Energy grid (contour):", "keyword", descriptions=True)


def cluster_active(context: PresentationContext) -> bool:
    """Whether SPR-KKR uses a real-space cluster rather than a periodic BZ."""
    return bool(
        context.value("TAU", "CLUSTER")
        or context.value("TAU", "MOL")
        or context.value("TAU", "BZINT") == "CLUSTER"
    )


def cluster_extent_enabled(context: PresentationContext) -> bool:
    return cluster_active(context) or context.value("TAU", "KKRMODE") in {"TB", "IMPURITY"}


def cluster_extent_reason(_context: PresentationContext) -> str:
    return (
        'Choose TB or IMPURITY under "KKR representation", enable "Use cluster mode" '
        'or "Molecular calculation", or select CLUSTER under "BZ integration" on this page.'
    )


def cluster_centre_reason(_context: PresentationContext) -> str:
    return (
        'Enable "Use cluster mode" or "Molecular calculation", or select CLUSTER under '
        '"BZ integration" on this page. TB / IMPURITY alone does not enable these fields.'
    )


def cluster_note(context: PresentationContext) -> str:
    representation = context.value("TAU", "KKRMODE") or "STANDARD"
    bzint = context.value("TAU", "BZINT")
    if cluster_active(context):
        return "Cluster settings are active. Set the extent using shells or radius."
    if representation in {"TB", "IMPURITY"}:
        return (
            f"{representation}: shells and radius are active. Centre and angular cutoff are disabled. "
            + cluster_centre_reason(context)
        )
    return (
        f"Disabled: {representation} with BZ integration {bzint} does not use these cluster settings. "
        'Enable "Use cluster mode" or "Molecular calculation", or select CLUSTER under '
        '"BZ integration" above. Choose TB / IMPURITY under "KKR representation" '
        "to enable shells and radius only."
    )


def bz_integration_enabled(context: PresentationContext) -> bool:
    return not bool(context.value("TAU", "CLUSTER") or context.value("TAU", "MOL"))


def points_integration_enabled(context: PresentationContext) -> bool:
    return not cluster_active(context) and context.value("TAU", "BZINT") == "POINTS"


def weyl_integration_enabled(context: PresentationContext) -> bool:
    return not cluster_active(context) and context.value("TAU", "BZINT") == "WEYL"


def structure_constants_enabled(context: PresentationContext) -> bool:
    return not cluster_active(context) and (context.value("TAU", "KKRMODE") or "STANDARD") == "STANDARD"


def magnetic_enabled(context: PresentationContext) -> bool:
    return not bool(context.value("CONTROL", "NONMAG"))


def beyond_dft_enabled(context: PresentationContext) -> bool:
    return context.value("MODE", "OP") not in (None, "NONE")


def lda_u_enabled(context: PresentationContext) -> bool:
    return context.value("MODE", "OP") == "LDA+U"


def explicit_reference_energy_enabled(context: PresentationContext) -> bool:
    return lda_u_enabled(context) and str(context.value("MODE", "IEREF")) == "-1"


def magnetism_group() -> GroupSpec:
    return GroupSpec("Magnetism and symmetry", (
        NONMAG,
        field("CONTROL", "NOSYM", "Disable symmetry:", "boolean"),
    ), id="magnetism")


def orientation_group() -> GroupSpec:
    return GroupSpec("Magnetisation orientation", (
        field("MODE", "MDIR", "Direction vector [x, y, z]:", "literal", enabled_when=magnetic_enabled),
        field("MODE", "MALF", "Alpha angle:", "real", minimum=-360., maximum=360., step=1., nullable=True,
              enabled_when=magnetic_enabled),
        field("MODE", "MBET", "Beta angle:", "real", minimum=-360., maximum=360., step=1., nullable=True,
              enabled_when=magnetic_enabled),
        field("MODE", "MGAM", "Gamma angle:", "real", minimum=-360., maximum=360., step=1., nullable=True,
              enabled_when=magnetic_enabled),
    ), collapsed=True, id="orientation")


def beyond_dft_group() -> GroupSpec:
    return GroupSpec("Beyond DFT", (
        field("MODE", "OP", "Beyond-DFT method:", "keyword"),
        field("MODE", "LOPT", "Correlated orbitals:", "literal", enabled_when=beyond_dft_enabled),
        field("MODE", "IEREF", "Reference-energy method:", "keyword", descriptions=True,
              enabled_when=lda_u_enabled),
        field("MODE", "EREF", "Reference energy:", "real", minimum=-100., maximum=100., step=.01,
              enabled_when=explicit_reference_energy_enabled),
        field("MODE", "UMODE", "LDA+U formulation:", "keyword", enabled_when=lda_u_enabled),
        field("MODE", "UEFF", "U values:", "literal", enabled_when=lda_u_enabled),
        field("MODE", "JEFF", "J values:", "literal", enabled_when=lda_u_enabled),
    ), collapsed=True, id="beyond_dft")


def relativistic_scaling_group() -> GroupSpec:
    return GroupSpec("Relativistic scaling", (
        field("MODE", "C", "Speed-of-light scale:", editor="scaling"),
        field("MODE", "SOC", "Spin-orbit scale:", editor="scaling"),
    ), collapsed=True, id="scaling")


def cpa_group() -> GroupSpec:
    return GroupSpec("CPA convergence", (
        field("CPA", "NITER", "Maximum CPA iterations:", "integer", minimum=1, maximum=2000),
        field("CPA", "TOL", "CPA tolerance:", "real", minimum=1e-10, maximum=1., step=1e-5, decimals=10),
    ), collapsed=True, note="Relevant for substitutionally disordered systems.", id="cpa")


def kkr_groups(is_2d: bool) -> tuple[GroupSpec, ...]:
    kpoints = (
        field("TAU", "NKTAB2D", "2D-region k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
        field("TAU", "NKTAB3D", "3D-region k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
    ) if is_2d else (
        field("TAU", "NKTAB", "Special k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
    )
    return (
        GroupSpec("KKR representation and basis", (
            KKRMODE,
            field("SITES", "NL", "Angular-momentum cutoffs:", "literal"),
            field("TAU", "CLUSTER", "Use cluster mode:", "boolean"),
            field("TAU", "MOL", "Molecular calculation:", "boolean"),
        )),
        GroupSpec("Brillouin-zone integration", (replace(BZINT, enabled_when=bz_integration_enabled),)
                  + kpoints + (
            field("TAU", "NKMIN", "Minimum k-points:", "integer", minimum=1, maximum=1000000, step=50,
                  enabled_when=weyl_integration_enabled),
            field("TAU", "NKMAX", "Maximum k-points:", "integer", minimum=1, maximum=1000000, step=50,
                  enabled_when=weyl_integration_enabled),
            field("MODE", "LLOYD", "Use Lloyd formula:", "boolean"),
        ), id="bz_integration"),
        GroupSpec("Cluster extent and centre", (
            field("TAU", "NSHLCLU", "Cluster shells:", "integer", minimum=1, maximum=100, nullable=True,
                  enabled_when=cluster_extent_enabled, disabled_reason_when=cluster_extent_reason),
            field("TAU", "CLURAD", "Cluster radius:", "real", minimum=0., maximum=100., step=.1,
                  nullable=True, enabled_when=cluster_extent_enabled,
                  disabled_reason_when=cluster_extent_reason),
            field("TAU", "IQCNTR", "Central site:", "integer", minimum=1, maximum=999999, nullable=True,
                  enabled_when=cluster_active, disabled_reason_when=cluster_centre_reason),
            field("TAU", "ITCNTR", "Central atomic type:", "integer", minimum=1, maximum=999999, nullable=True,
                  enabled_when=cluster_active, disabled_reason_when=cluster_centre_reason),
            field("TAU", "NLOUT", "Cluster angular cutoff:", "integer", minimum=1, maximum=12,
                  enabled_when=cluster_active, disabled_reason_when=cluster_centre_reason),
        ), id="cluster_extent", note="Set the extent using shells or radius.", note_when=cluster_note),
        GroupSpec("Structure constants", (
            field("STRCONST", "ETA", "Ewald parameter:", "real", minimum=0., maximum=100., step=.01,
                  nullable=True, enabled_when=structure_constants_enabled),
            field("STRCONST", "RMAX", "Real-space convergence radius:", "real",
                  minimum=0., maximum=100., step=.1, nullable=True,
                  enabled_when=structure_constants_enabled),
            field("STRCONST", "GMAX", "Reciprocal-space convergence radius:", "real",
                  minimum=0., maximum=100., step=.1, nullable=True,
                  enabled_when=structure_constants_enabled),
        ), collapsed=True, id="structure_constants"),
    )


def single_site_mesh_enabled(context: PresentationContext) -> bool:
    return context.parameters.uses_separate_single_site_contour()


def single_site_mesh_reason(_context: PresentationContext) -> str:
    return "Enable a separate single-site contour first."


def _energy_grid_groups(ne: FieldPlacement) -> tuple[GroupSpec, ...]:
    return (
        GroupSpec("Single-site contribution", (
            field("ENERGY", "SPLITSS", "Separate single-site contour:", "boolean"),
            field("CONTROL", "SPLITSS", "Force separate contour (CONTROL):", "boolean"),
        ), note="Also required by CONTROL.FSOHFF. Disabled single-site settings are remembered until this dialog is closed. SPRKKR sets Im(E) to zero when SPLITSS is active."),
        GroupSpec("Energy grids", (
            replace(GRID, label="Main energy grid (contour):"),
            replace(
                GRID,
                index=1,
                label="Single-site energy grid (contour):",
                enabled_when=single_site_mesh_enabled,
                disabled_reason_when=single_site_mesh_reason,
                required_when=single_site_mesh_enabled,
                required_message="A separate single-site contour requires a grid value.",
            ),
            ne,
            field("ENERGY", "NE", "Single-site energy points:", "integer",
                  index=1, minimum=1, maximum=100000, nullable=True,
                  enabled_when=single_site_mesh_enabled,
                  disabled_reason_when=single_site_mesh_reason,
                  required_when=single_site_mesh_enabled,
                  required_message="A separate single-site contour requires an energy-point value."),
        ), layout="paired", id="energy_grids"),
    )


def _output_page(*, include_hff: bool = True, scf: bool = False) -> PageSpec:
    hyperfine_fields = (
        field("TASK", "HFF", "Calculate hyperfine field:", "boolean"),
        field("CONTROL", "NOHFF", "Disable hyperfine-field calculation:", "boolean"),
        field("CONTROL", "FSOHFF", "Relativistic HFF decomposition:", "boolean"),
    ) if include_hff else (
        field("CONTROL", "NOHFF", "Disable hyperfine-field calculation:", "boolean"),
        field("CONTROL", "FSOHFF", "Relativistic HFF decomposition:", "boolean"),
    )
    hyperfine_fields += () if scf else (
        field("CONTROL", "SPLITSS", "Force separate single-site contour:", "boolean"),
    )
    return PageSpec("output", "Results & files" if scf else "Output & diagnostics", (
        GroupSpec("Output", (
            field("CONTROL", "PRINT", "Print level:", "integer", minimum=0, maximum=5),
        ) + (() if scf else (field("CONTROL", "NOSYM", "Disable symmetry:", "boolean"),))),
        GroupSpec("Hyperfine field", hyperfine_fields, id="hff"),
    ) + ((GroupSpec("Potential file", (
        field("CONTROL", "POTFIL", "Input potential file:", "text"),
    ), collapsed=True, note="Leave the potential file empty to let the calculator supply it."),) if scf else ()), OUTPUT_COLOR)

nktab = field("TAU", "NKTAB", "Special k-points:", "integer", minimum=1, maximum=1000000, step=50)
nl = field("SITES", "NL", "Angular-momentum cutoffs (NL):", "literal")
