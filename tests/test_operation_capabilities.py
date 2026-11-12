import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.main import GuiApplication


def test_controller_exposes_structure_operation_capabilities(monkeypatch):
    controller = WorkspaceController(WorkspaceState())
    assert not controller.can_build_2d()

    controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    assert controller.can_build_2d()

    controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=(True, True, False))
    )
    assert not controller.can_build_2d()

    monkeypatch.setattr(controller, "is_scf_converged", lambda: False)
    monkeypatch.setattr(controller, "scf_status", lambda: None)
    assert not controller.structure_change_requires_scf_restart()

    monkeypatch.setattr(controller, "scf_status", lambda: "START")
    assert not controller.structure_change_requires_scf_restart()

    monkeypatch.setattr(controller, "scf_status", lambda: "ITR")
    assert controller.structure_change_requires_scf_restart()

    monkeypatch.setattr(controller, "scf_status", lambda: "CUSTOM-STAGE")
    assert controller.structure_change_requires_scf_restart()

    monkeypatch.setattr(controller, "is_scf_converged", lambda: True)
    assert controller.structure_change_requires_scf_restart()


def test_restarted_workspace_does_not_require_another_scf_reset(monkeypatch):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), restarted=True)
    )
    monkeypatch.setattr(controller, "is_scf_converged", lambda: True)
    monkeypatch.setattr(controller, "scf_status", lambda: "ITR")

    assert not controller.structure_change_requires_scf_restart()


def test_build2d_flow_rejects_non_3d_structure(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms(
                "Fe",
                cell=(2.8, 2.8, 2.8),
                pbc=(True, True, False),
            )
        )
    )
    recent_files = RecentFiles(tmp_path / "recent.json")
    selected = []
    messages = []

    monkeypatch.setattr(
        structure_flows,
        "select_build_2d_structure",
        lambda *args, **kwargs: selected.append((args, kwargs)),
    )
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "information",
        lambda *args: messages.append(args),
    )

    assert structure_flows.build_2d_structure(
        controller,
        recent_files,
        None,
    ) is None
    assert selected == []
    assert messages
    assert "3D periodic bulk" in messages[0][2]


def test_expert_and_guided_apply_different_empty_sphere_policy(
    tmp_path, monkeypatch
):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    expert = gui.create_main_window()
    workflow = gui.create_workflow_window()
    controller = gui.controller
    controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    monkeypatch.setattr(controller, "scf_status", lambda: "CUSTOM-STAGE")
    monkeypatch.setattr(controller, "is_scf_converged", lambda: False)

    expert._refresh_action_availability()
    workflow._refresh()
    application.processEvents()

    assert controller.structure_change_requires_scf_restart()
    assert expert.empty_spheres_action.isVisible()
    assert not any(
        "Empty Spheres" in button.text()
        for button in workflow._actions.findChildren(QPushButton)
    )

    expert.close()
    workflow.close()


def test_expert_build2d_action_uses_shared_capability(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    expert = gui.create_main_window()

    gui.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    assert expert.build_2d_structure_action.isEnabled()

    gui.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=(True, True, False))
    )
    application.processEvents()
    assert not expert.build_2d_structure_action.isEnabled()

    expert.close()


def test_empty_sphere_warning_does_not_preemptively_reset_scf(monkeypatch):
    _application = QApplication.instance() or QApplication([])
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    monkeypatch.setattr(
        controller, "structure_change_requires_scf_restart", lambda: True
    )
    generation = controller.structure_generation

    monkeypatch.setattr(
        structure_flows,
        "select_empty_spheres_parameters",
        lambda *, initial, parent: {},
    )
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "information",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        structure_flows,
        "add_empty_spheres",
        lambda atoms, **kwargs: atoms,
    )

    assert structure_flows.update_empty_spheres(controller, None)
    assert not controller.restarted
    assert controller.structure_generation == generation.next()


def test_empty_sphere_warning_can_cancel_before_search(monkeypatch):
    _application = QApplication.instance() or QApplication([])
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    monkeypatch.setattr(
        controller, "structure_change_requires_scf_restart", lambda: True
    )
    searched = []

    monkeypatch.setattr(
        structure_flows,
        "select_empty_spheres_parameters",
        lambda *, initial, parent: {},
    )
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )
    monkeypatch.setattr(
        structure_flows,
        "add_empty_spheres",
        lambda *args, **kwargs: searched.append((args, kwargs)),
    )

    assert not structure_flows.update_empty_spheres(controller, None)
    assert searched == []
