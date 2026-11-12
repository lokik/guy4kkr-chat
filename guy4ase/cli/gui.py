"""Launch the Guy4ASE graphical interface from ASE2SPRKKR's CLI."""

help = "Launch the Guy4ASE graphical user interface."
description = "Start the structure builder and SPR-KKR calculation GUI."


def parser(parser):
    """The GUI command needs no additional arguments."""


def run(args, global_args):
    """Start the existing GUI without passing CLI command arguments to Qt."""
    from guy4ase.main import main

    raise SystemExit(main(argv=[]))
