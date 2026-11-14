"""Visualization progress shows until ASE subprocess signals window readiness."""
from __future__ import annotations

import os
from threading import Event, get_ident
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from ase2sprkkr_gui.gui.flows import visualization
from ase2sprkkr_gui.gui.misc.modal_task import _ModalTaskDialog


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ase_visualization_waits_for_window_readiness(monkeypatch):
    _application()
    parent = QWidget()
    atoms = Atoms("Fe", positions=[(1, 2, 3)], cell=(4, 4, 4), pbc=True)
    controller = SimpleNamespace(atoms=atoms)
    settings = SimpleNamespace(viewer="ase")
    ready = Event()
    calls = []
    dialog_visible = []

    def launch(snapshot):
        calls.append((get_ident(), snapshot))
        assert ready.wait(timeout=3)

    def inspect_dialog():
        dialog_visible.append(any(
            dialog.isVisible() for dialog in parent.findChildren(_ModalTaskDialog)
        ))
        ready.set()

    monkeypatch.setattr(visualization, "viewer_unavailability", lambda name: None)
    monkeypatch.setattr(visualization, "launch_ase_gui", launch)
    QTimer.singleShot(0, inspect_dialog)
    try:
        assert visualization.visualize_structure(controller, settings, parent)
        assert dialog_visible == [True]
        assert len(calls) == 1
        thread_id, snapshot = calls[0]
        assert thread_id != get_ident()
        assert type(snapshot) is Atoms
        assert snapshot is not atoms
        assert snapshot.get_chemical_symbols() == atoms.get_chemical_symbols()
        assert (snapshot.positions == atoms.positions).all()
        assert (snapshot.cell.array == atoms.cell.array).all()
        assert (snapshot.pbc == atoms.pbc).all()
        assert all(not dialog.isVisible()
                   for dialog in parent.findChildren(_ModalTaskDialog))
    finally:
        ready.set()
        parent.close()


def test_ase_viewer_always_uses_isolated_child(monkeypatch):
    atoms = Atoms("Fe")
    launched = []
    monkeypatch.setattr(visualization, "launch_ase_gui", lambda value: launched.append(value))
    monkeypatch.setattr(visualization, "ase_view", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("unexpected ASE launcher")))
    visualization._open_viewer(atoms, "ase")
    assert launched == [atoms]


def test_other_viewers_keep_ase_dispatch(monkeypatch):
    atoms = Atoms("Fe")
    calls = []
    monkeypatch.setattr(visualization, "ase_view", lambda value, *, viewer: calls.append((value, viewer)))
    monkeypatch.setattr(visualization, "launch_ase_gui", lambda _atoms: (_ for _ in ()).throw(AssertionError("unexpected Tk child")))
    visualization._open_viewer(atoms, "vmd")
    assert calls == [(atoms, "vmd")]


def test_ase_startup_error_is_shown(monkeypatch):
    _application()
    parent = QWidget()
    controller = SimpleNamespace(atoms=Atoms("Fe"))
    settings = SimpleNamespace(viewer="ase")
    messages = []
    monkeypatch.setattr(visualization, "viewer_unavailability", lambda name: None)
    monkeypatch.setattr(visualization, "launch_ase_gui",
                        lambda atoms: (_ for _ in ()).throw(RuntimeError("child crashed")))
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda _parent, title, message: messages.append((title, message)))
    try:
        assert not visualization.visualize_structure(controller, settings, parent)
        assert len(messages) == 1
        assert "child crashed" in messages[0][1]
    finally:
        parent.close()


def test_unavailable_external_viewer_can_fallback_to_ase(monkeypatch):
    _application()
    parent = QWidget()
    controller = SimpleNamespace(atoms=Atoms("Fe"))
    settings = SimpleNamespace(viewer="vmd")
    launched = []
    monkeypatch.setattr(visualization, "viewer_unavailability",
                        lambda name: "Not installed" if name == "vmd" else None)
    monkeypatch.setattr(visualization, "launch_ase_gui", lambda atoms: launched.append(atoms))
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *_args: QMessageBox.StandardButton.Yes)
    try:
        assert visualization.visualize_structure(controller, settings, parent)
        assert len(launched) == 1
    finally:
        parent.close()
