import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from ase import Atoms

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.tooltips import parameter_tooltip


def _dialog(task):
    parameter_task = "bsfek" if task == "bsf" else task
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    return GuidedInputParametersDialog(
        task,
        InputParameters.create(parameter_task),
        atoms=atoms,
    )


def test_scf_fields_show_real_name_and_ase2sprkkr_help():
    dialog = _dialog("scf")

    for view in dialog.form.field_views:
        editor = view.editor
        parameter_name = ".".join(editor.path)
        assert parameter_name in editor.toolTip()
        assert parameter_name in view.label.toolTip()

    niter = dialog.editors_for(("SCF", "NITER"))[0]
    assert "SPR-KKR parameter: SCF.NITER" in niter.toolTip()
    assert "Maximal number of iterations of the SCF cycle" in niter.toolTip()

    dialog.close()


def test_all_task_fields_show_real_parameter_name_on_editor_and_label():
    for task in ("dos", "xas", "arpes", "bsf", "jxc"):
        dialog = _dialog(task)
        for view in dialog.form.field_views:
            editor = view.editor
            parameter_name = ".".join(editor.path)
            assert parameter_name in editor.toolTip()
            assert parameter_name in view.label.toolTip()
        dialog.close()


def test_generic_help_is_not_mistaken_for_parameter_documentation():
    params = InputParameters.create("dos")

    tooltip = parameter_tooltip(
        params.ENERGY.ImE,
        "ENERGY",
        "ImE",
        "Imaginary broadening (Ry):",
    )

    assert tooltip == "SPR-KKR parameter: ENERGY.ImE"


def test_bsf_path_controls_share_kpath_tooltip():
    dialog = _dialog("bsf")

    for editor in dialog.editors_for(("TASK", "KPATH")):
        assert "TASK.KPATH" in editor.control.path_combo.toolTip()
        assert "Predefined path in k-space" in editor.control.path_combo.toolTip()
        assert "TASK.KPATH" in editor.control.path_summary.toolTip()

    dialog.close()
