"""Availability diagnostics for viewers registered with ASE.

ASE's CLIViewer starts a helper process, so a missing external executable
can fail *after* ase.visualize.view() has returned. Inspect the registered
viewer before launching it, without maintaining a parallel viewer registry.
"""
from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
from shutil import which

from ase.visualize.viewers import VIEWERS


def viewer_unavailability(viewer_name: str) -> str | None:
    """Return a reason when an ASE viewer is unavailable, otherwise None.

    This checks the registered command or importable Python implementation.
    It cannot guarantee that an installed viewer will successfully start.
    """
    name = viewer_name.lower()
    viewer = VIEWERS.get(name)
    if viewer is None:
        return f"Viewer '{viewer_name}' is not registered with ASE."

    if name == "ase":
        return None

    argv = getattr(viewer, "argv", None)
    if argv:
        executable = str(argv[0])
        if which(executable) is None:
            return f"Executable '{executable}' was not found on PATH."
        return None

    # Some ASE viewer implementations import the actual optional dependency
    # only when invoked, so checking the wrapper module alone is insufficient.
    optional_modules = {"ngl": "nglview", "sage": "sage"}
    dependency = optional_modules.get(name)
    if dependency and find_spec(dependency) is None:
        return f"Python package '{dependency}' is not installed."

    module = getattr(viewer, "module_name", None)
    if module:
        try:
            import_module(module)
        except ImportError as exc:
            return f"Python module '{module}' cannot be imported: {exc}"
    return None
