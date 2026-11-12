import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QDialog

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.dialogs import main_window as main_window_module
from guy4ase.gui.dialogs import workflow_window as workflow_module
from guy4ase.gui.dialogs.structures import build_2d as build_2d_module
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.main import GuiApplication


def test_build2d_selector_uses_explicit_recent_files(tmp_path, monkeypatch):
    recent_files = RecentFiles(tmp_path / "recent.json")
    parent = object()
    atoms = object()
    captured = {}

    class FakeDialog:
        def __init__(
            self,
            dialog_atoms,
            parent=None,
            *,
            recent_files,
            surface_mode=False,
        ):
            captured.update(
                atoms=dialog_atoms,
                parent=parent,
                recent_files=recent_files,
                surface_mode=surface_mode,
            )

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(build_2d_module, "Build2DStructureDialog", FakeDialog)

    assert build_2d_module.select_build_2d_structure(
        atoms,
        parent=parent,
        recent_files=recent_files,
        surface_mode=True,
    ) is None
    assert captured == {
        "atoms": atoms,
        "parent": parent,
        "recent_files": recent_files,
        "surface_mode": True,
    }


def test_build2d_flow_threads_recent_files_to_selector(tmp_path, monkeypatch):
    recent_files = RecentFiles(tmp_path / "recent.json")
    parent = object()
    atoms = object()
    captured = {}

    class Controller:
        structure_generation = object()

        def __init__(self):
            self.atoms = atoms

        def can_build_2d(self):
            return True

        def apply_structure_edit(self, edit, *, expected_structure_generation):
            assert expected_structure_generation is self.structure_generation
            self.atoms = edit(self.atoms)
            return object()

    controller = Controller()

    monkeypatch.setattr(
        structure_flows,
        "select_build_2d_structure",
        lambda candidate, parent=None, *, recent_files, surface_mode=False: (
            captured.update(
                candidate=candidate,
                parent=parent,
                recent_files=recent_files,
                surface_mode=surface_mode,
            )
            or candidate
        ),
    )
    monkeypatch.setattr(
        structure_flows,
        "document_change_applied",
        lambda change_parent, change: True,
    )

    assert structure_flows.build_2d_structure(
        controller,
        recent_files,
        parent,
        surface_mode=True,
    ) is atoms
    assert captured == {
        "candidate": atoms,
        "parent": parent,
        "recent_files": recent_files,
        "surface_mode": True,
    }


def test_windows_pass_recent_files_explicitly(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    expert = gui.create_main_window()
    workflow = gui.create_workflow_window()
    expert.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    calls = []

    def capture(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(main_window_module.structure_flows, "build_2d_structure", capture)
    monkeypatch.setattr(workflow_module.structure_flows, "build_2d_structure", capture)

    expert.build_2d_structure(surface_mode=True)
    workflow._build_2d(surface_mode=False)

    assert calls == [
        (
            (expert.controller, expert.recent_history, expert),
            {"surface_mode": True},
        ),
        (
            (workflow.controller, workflow.recent_history, workflow),
            {"surface_mode": False},
        ),
    ]

    expert.close()
    workflow.close()
