"""JXC guided setup pages."""
from .schema import Choice, GroupSpec, PageSpec, TaskDialogSpec, field, main_energy_mesh_field, mirror
from .shared import (
    CONVERGENCE_COLOR,
    QUICK_COLOR,
    SPECIAL_COLOR,
    _output_page,
    nktab,
    nl,
)


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    jxc_radius = field("TASK", "CLURAD", "Interaction cluster radius:", "real", minimum=0., maximum=100., step=.1)
    dmi = field("TASK", "DMI", "Dzyaloshinskii-Moriya interaction:", "boolean")
    jxc_ne = main_energy_mesh_field("NE", "Energy points:", "integer", minimum=1, maximum=10000)
    jxc = TaskDialogSpec("JXC Calculation Setup", (
        PageSpec("quick", "Quick setup", (GroupSpec("Common JXC settings", (
            mirror(jxc_radius), mirror(dmi), mirror(jxc_ne),
        )),), QUICK_COLOR, quick=True),
        PageSpec("exchange", "Exchange interactions", (GroupSpec("Interaction range", (jxc_radius, dmi)),), SPECIAL_COLOR),
        PageSpec("accuracy", "Energy & accuracy", (GroupSpec("Integration and basis", (
            jxc_ne, nktab, nl,
            field("MODE", "LLOYD", "Use Lloyd formula:", "boolean"),
            field("MODE", "MODE", "Relativity and spin mode:", "choice", choices=tuple(
                Choice(value, value) for value in ("SP-SREL", "SP-REL", "SREL", "NREL")
            )),
        )),), CONVERGENCE_COLOR),
        _output_page(),
    ))
    return jxc
