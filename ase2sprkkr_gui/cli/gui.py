"""Launch the Ase2sprkkr graphical interface from ASE2SPRKKR's CLI."""

help = "Launch the Ase2sprkkr graphical user interface."
description = "Start the structure builder and SPR-KKR calculation GUI."


def parser(parser):
    """Add startup-file options shared by both GUI entry points."""
    parser.add_argument(
        "file", nargs="?", metavar="FILE",
        help="Open a structure, SPR-KKR input/output, or directory of outputs.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--open-last", action="store_true",
        help="Open the most recent existing structure (not the last output).",
    )
    group.add_argument(
        "--structure", metavar="FILE",
        help="Open FILE as a structure, including a SPR-KKR potential.",
    )
    group.add_argument(
        "--input", metavar="FILE",
        help="Open FILE as SPR-KKR input parameters.",
    )
    group.add_argument(
        "--output", metavar="PATH",
        help="Open a SPR-KKR result file or import an output directory.",
    )
    group.add_argument(
        "--job", metavar="ID",
        help="Follow an unfinished persistent job or open its completed result.",
    )


def startup_selection(args):
    """Return the requested kind and path, or (None, None) for a blank GUI."""
    choices = [
        (kind, value)
        for kind, value in (
            ("auto", getattr(args, "file", None)),
            ("structure", getattr(args, "structure", None)),
            ("input", getattr(args, "input", None)),
            ("output", getattr(args, "output", None)),
            ("job", getattr(args, "job", None)),
        )
        if value is not None
    ]
    if getattr(args, "open_last", False):
        choices.append(("last", None))
    if len(choices) > 1:
        raise ValueError(
            "Specify a FILE, --open-last, --structure, --input, --output, "
            "or --job, "
            "but not more than one."
        )
    return choices[0] if choices else (None, None)


def run(args, global_args):
    """Forward the GUI's startup request, without leaking parent CLI flags."""
    from ase2sprkkr_gui.main import main

    try:
        kind, path = startup_selection(args)
    except ValueError as exc:
        raise SystemExit(f"ase2sprkkr gui: {exc}") from exc
    if kind == "last":
        argv = ["--open-last"]
    elif kind in {"structure", "input", "output", "job"}:
        argv = [f"--{kind}", str(path)]
    elif kind == "auto":
        argv = [str(path)]
    else:
        argv = []
    raise SystemExit(main(argv=argv))
