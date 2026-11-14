"""Atomic edits for the unified BSF task; ENERGY.NE remains the mode source."""
from ase2sprkkr.common.configuration_transaction import ConfigurationTransaction
from ase2sprkkr.input_parameters.definitions.bsf import EK, KK, KK_TASK_ITEMS, bsf_mode
from ase2sprkkr_gui.gui.input_parameters.keyword_choices import keyword_items


def set_energy_points(parameters, points, *, atoms=None):
    """Set NE[0], atomically replacing incompatible settings if EK/KK changes.

    NE > 1 selects an E-k path; NE == 1 selects a fixed-energy k-k plane.
    A mode transition seeds new geometry and energy settings, but preserves
    the single-site mesh count. The caller owns undo/history for this mutation.
    """
    old_mode = bsf_mode(parameters)
    new_mode = EK if points > 1 else KK
    ne = list(parameters.ENERGY.NE())
    ne[0] = points
    if old_mode == new_mode:
        parameters.ENERGY.NE.set(ne)
        return

    energy = {"NE": ne}
    if new_mode == KK:
        # Like XBand, use the end of the E-k range as the fixed energy.
        relative = parameters.ENERGY.EMAXEV()
        energy.update(EMIN=parameters.ENERGY.EMAX() if relative is None else None,
                      EMINEV=relative, EMAX=None, EMAXEV=None)
        task = {"KA": [[0., 0., 0.]], "K1": [1., 0., 0.], "K2": [0., 1., 0.],
                "NK1": 60, "NK2": 60}
        incompatible = ("NK", "KPATH", "KE")
    else:
        # XBand's E-k starting range; all replaced settings remain in Undo.
        energy.update(EMIN=-.2, EMAX=1., EMINEV=None, EMAXEV=None)
        task = {"KPATH": 1}
        incompatible = KK_TASK_ITEMS

    with ConfigurationTransaction(parameters) as transaction:
        # KA changes between a list of segments and one unnumbered origin.
        # Clear its old repeated storage before changing the mode.
        for name in ("KA",) + incompatible:
            parameters.TASK[name].stage_clear(transaction)
        parameters.set({"ENERGY": energy, "TASK": task})
        if new_mode == EK:
            option = parameters.TASK['KPATH']
            available = [value for value, _ in keyword_items(option, atoms=atoms) if value is not None]
            if option() not in available:
                select_path(parameters, available[0] if available else None)


def select_path(parameters, value):
    """Select a predefined path, or seed missing custom endpoints for None."""
    updates = {"KPATH": value}
    if value is None:
        if parameters.TASK["KA"]() is None:
            updates["KA"] = [[0., 0., 0.]]
        if parameters.TASK["KE"]() is None:
            updates["KE"] = [[1., 1., 1.]]
    parameters.TASK.set(updates)
