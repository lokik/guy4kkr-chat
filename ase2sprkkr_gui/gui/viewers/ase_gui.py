"""ASE Tk GUI subprocess with first-window readiness notification.

Tk is initialized on the *main thread of its own process*.  Running Tk on a
Python thread alongside Qt can crash the entire application in native GUI
libraries.  Unlike ASE's regular subprocess launcher, this entry point reports
when the top-level Tk window is mapped, not just when the process starts.

The structure is a plain ASE Atoms snapshot, transferred through stdin; there
is no temporary directory or intermediate trajectory file.
"""
from __future__ import annotations

import os
import pickle
import subprocess
import sys
from threading import Thread
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ase import Atoms

_READY = "ASE2SPRKKR_GUI_ASE_GUI_READY"
_ERROR = "ASE2SPRKKR_GUI_ASE_GUI_ERROR:"


def launch_ase_gui(atoms: Atoms) -> None:
    """Start an independent viewer and return after its first Tk window maps.

    This runs in the Qt modal task's worker thread.  The ASE/Tk GUI itself runs
    in the subprocess's main thread and survives the parent Qt application.
    Only a plain in-process Atoms snapshot is pickled (no external input).
    """
    payload = pickle.dumps(atoms, protocol=pickle.HIGHEST_PROTOCOL)
    process = subprocess.Popen(
        [sys.executable, "-m", __name__, "--child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        with process.stdin:
            process.stdin.write(payload)
    except OSError as exc:
        # The child may have crashed while reading the structure.
        status = process.wait()
        process.stdout.close()
        raise RuntimeError(
            f"ASE viewer failed to read its structure (exit status {status})"
        ) from exc

    messages: list[str] = []
    with process.stdout:
        for raw_line in process.stdout:
            message = raw_line.decode("utf-8", errors="replace").strip()
            if message == _READY:
                # Reap the child when it eventually closes, without tying its
                # lifetime to the Qt dialog or the Qt application.
                Thread(target=process.wait, name="ase-viewer-reaper",
                       daemon=True).start()
                return
            if message.startswith(_ERROR):
                process.wait()
                raise RuntimeError(message[len(_ERROR):])
            if message:
                messages.append(message)
                if len(messages) > 3:
                    messages.pop(0)

    status = process.wait()
    details = ": " + "; ".join(messages) if messages else ""
    raise RuntimeError(
        f"ASE viewer exited before showing a window (exit status {status}){details}"
    )


def _notify_when_mapped(window, ready: Callable[[], None]) -> None:
    """Notify once for the top-level window's own Tk map event."""
    sent = False

    def announce() -> None:
        nonlocal sent
        if not sent:
            sent = True
            ready()

    def on_map(event) -> None:
        if event.widget is window:
            announce()

    window.bind("<Map>", on_map, add="+")
    if window.winfo_ismapped():
        announce()


def _child_main() -> int:
    """Read an Atoms snapshot, run the ASE GUI and report first mapping."""
    try:
        from ase.gui.gui import GUI

        # The parent created this pickle from a plain Atoms snapshot; it is
        # not accepting arbitrary pickle data from a network or user file.
        atoms = pickle.load(sys.stdin.buffer)
        gui = GUI(images=[atoms])

        def report_ready() -> None:
            print(_READY, flush=True)
            # After the handshake, viewer stdout must not retain/write to the
            # pipe that the parent closes once the dialog is dismissed.
            os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

        _notify_when_mapped(gui.window.win, report_ready)
        gui.run()
    except Exception as exc:  # noqa: BLE001 - report viewer-startup failures
        print(f"{_ERROR}{type(exc).__name__}: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--child"]:
        raise SystemExit("The ASE GUI helper is only used as a child process.")
    raise SystemExit(_child_main())
