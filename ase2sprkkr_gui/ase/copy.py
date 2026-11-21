"""Copies for geometry and occupation edits."""

from ase2sprkkr import SPRKKRAtoms


def copy_for_edit(atoms):
    """Detach editable structure containers while sharing SPR-KKR values.

    Editors replacing geometry or occupations can retain radial arrays. An
    editor writing into radial arrays must use an independent copy instead.
    Plain ASE Atoms do not accept the SPRKKRAtoms ``shallow`` argument.
    """
    return atoms.copy(shallow=True) if isinstance(atoms, SPRKKRAtoms) else atoms.copy()
