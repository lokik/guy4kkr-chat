"""Launch the Ase2sprkkr graphical interface from ASE2SPRKKR's CLI."""

help = "Launch the Ase2sprkkr graphical user interface."
description = "Start the structure builder and SPR-KKR calculation GUI."


def parser(parser):
    """The GUI command needs no additional arguments."""


def run(args, global_args):
    """Start the existing GUI without passing CLI command arguments to Qt."""
    from ase2sprkkr_gui.main import main

    raise SystemExit(main(argv=[]))
