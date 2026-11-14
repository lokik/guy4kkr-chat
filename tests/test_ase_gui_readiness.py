"""ASE viewer readiness is delivered by an isolated child, never a Tk thread."""
from __future__ import annotations

from io import BytesIO
import pickle
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from ase import Atoms

from ase2sprkkr_gui.gui.viewers import ase_gui


class FakeWindow:
    def __init__(self, *, mapped=False):
        self.mapped = mapped
        self.callback = None

    def bind(self, name, callback, *, add):
        assert name == "<Map>" and add == "+"
        self.callback = callback

    def winfo_ismapped(self):
        return self.mapped

    def emit_map(self, widget):
        self.callback(SimpleNamespace(widget=widget))


def test_top_level_mapping_reports_ready_once():
    window = FakeWindow()
    notifications = []
    ase_gui._notify_when_mapped(window, lambda: notifications.append(True))
    window.emit_map(object())
    assert notifications == []
    window.emit_map(window)
    window.emit_map(window)
    assert notifications == [True]


def test_already_mapped_window_reports_ready():
    window = FakeWindow(mapped=True)
    notifications = []
    ase_gui._notify_when_mapped(window, lambda: notifications.append(True))
    assert notifications == [True]


class CapturedStdin(BytesIO):
    def close(self):
        self.payload = self.getvalue()
        super().close()


def test_launch_uses_stdin_and_waits_for_child_mapping(monkeypatch):
    started = Event()
    signal = Event()
    finished = Event()
    received = []

    class FakePopen:
        def __init__(self, argv, *, stdin, stdout):
            assert argv[1:] == ["-m", ase_gui.__name__, "--child"]
            assert stdin is ase_gui.subprocess.PIPE
            assert stdout is ase_gui.subprocess.PIPE
            self.stdin = CapturedStdin()
            self.stdout = BytesIO((ase_gui._READY + "\n").encode())
            self.waited = Event()
            started.set()

        def wait(self):
            self.waited.set()
            return 0

    instances = []
    def create_process(*args, **kwargs):
        process = FakePopen(*args, **kwargs)
        instances.append(process)
        return process

    monkeypatch.setattr(ase_gui.subprocess, "Popen", create_process)
    ase_gui.launch_ase_gui(Atoms("Fe"))
    assert started.is_set()
    assert len(instances) == 1
    assert isinstance(pickle.loads(instances[0].stdin.payload), Atoms)
    assert pickle.loads(instances[0].stdin.payload).get_chemical_symbols() == ["Fe"]


def test_launch_reports_startup_error(monkeypatch):
    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdin = CapturedStdin()
            self.stdout = BytesIO((ase_gui._ERROR + "TclError: no display\n").encode())
        def wait(self):
            return 1

    monkeypatch.setattr(ase_gui.subprocess, "Popen", FakePopen)
    with pytest.raises(RuntimeError, match="TclError: no display"):
        ase_gui.launch_ase_gui(Atoms("Fe"))


def test_launch_reports_child_crash_before_map(monkeypatch):
    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdin = CapturedStdin()
            self.stdout = BytesIO()
        def wait(self):
            return -11

    monkeypatch.setattr(ase_gui.subprocess, "Popen", FakePopen)
    with pytest.raises(RuntimeError, match="exit status -11"):
        ase_gui.launch_ase_gui(Atoms("Fe"))
