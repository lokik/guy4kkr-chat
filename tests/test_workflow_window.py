import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from ase import Atoms
from types import SimpleNamespace
from PyQt6.QtCore import Qt, QPoint, QSize
from PyQt6.QtWidgets import QApplication, QAbstractButton, QFrame, QLabel, QMessageBox, QSizePolicy, QToolButton, QWidget


from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.dialogs import workflow_window as workflow_module
from ase2sprkkr_gui.gui.widgets.centered_icon_buttons import (
    CenteredIconPushButton, CenteredIconToolButton,
)
from ase2sprkkr_gui.gui.workflow.model import (
    Build2D,
    Build2DKind,
    BuildEmbedding,
    ExplainEmbedding,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    EditStructure,
    Load,
    LoadKind,
    LoadHostPotential,
    AttachHostPotential,
    CreateHostPotential,
    RunTask,
    ReconvergeScf,
    CustomTask,
    SaveStructure,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
)
from ase2sprkkr_gui.main import GuiApplication


def _workflow(tmp_path, *, workspace=None):
    gui = GuiApplication(
        workspace=workspace,
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    return gui, gui.create_workflow_window()


def _commands(window):
    return tuple(
        action.command
        for group in window.workflow_plan.groups
        for action in group.actions
    )


def test_results_load_button_imports_output_in_guided(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    gui, guided = _workflow(tmp_path)
    imports = []
    monkeypatch.setattr(
        workflow_module.file_flows, "choose_and_load_output",
        lambda controller, history, parent: imports.append((controller, history, parent)),
    )
    assert guided.result_actions_widget.load_result_button.isEnabled()
    guided.result_actions_widget.load_result_button.click()
    assert imports == [(gui.controller, gui.recent_files, guided)]
    guided.close()

def test_result_import_directory_is_wired_in_guided(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    gui, guided = _workflow(tmp_path)
    imports = []
    monkeypatch.setattr(
        workflow_module.file_flows,
        "choose_and_load_output_directory",
        lambda controller, history, parent: imports.append((controller, history, parent)),
    )

    assert guided.result_actions_widget.import_directory_button.isEnabled()
    guided.result_actions_widget.import_directory_button.click()
    assert imports == [(gui.controller, gui.recent_files, guided)]
    guided.close()


def test_navigation_shortcuts_are_exposed_in_tooltips(tmp_path):
    _application = QApplication.instance() or QApplication([])
    _gui, guided = _workflow(tmp_path)
    assert guided._settings_button.shortcut().toString() == "Ctrl+,"
    assert guided._close_button.shortcut().toString() == "Ctrl+Q"
    assert "Ctrl+," in guided._settings_button.toolTip()
    assert "Ctrl+Q" in guided._close_button.toolTip()
    guided.close()


def test_workflow_uses_one_workspace_without_expert_shell(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    workspace = WorkspaceState()
    gui, window = _workflow(tmp_path, workspace=workspace)

    assert not hasattr(gui, "create_main_window")
    gui.controller.replace_structure(Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True))
    application.processEvents()

    assert workspace.structure.value.atoms is gui.controller.atoms
    assert RunTask("scf") in _commands(window)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    window.close()

def test_action_columns_classify_embedded_and_restart_workflows():
    from ase2sprkkr_gui.gui.widgets.workflow_actions import _action_column
    from ase2sprkkr_gui.gui.workflow.model import (
        ActionIcon, AvailableAction, ConvergeHostScf,
    )

    def column(command):
        return _action_column(
            AvailableAction(command, "test", "", "neutral", ActionIcon.OPEN)
        )

    assert column(RunTask("dos")) == "calculate"
    assert column(ReconvergeScf()) == "calculate"
    assert column(UpdateEmptySpheres()) == "calculate"
    assert column(ConvergeHostScf()) == "calculate"
    assert column(ConvergeHostScf(restart_scf=True)) == "calculate"
    assert column(UseForNewCalculation()) == "calculate"
    assert column(EditStructure()) == "structure"
    assert column(Load(LoadKind.STRUCTURE)) == "structure"
    assert column(CreateStructure(CreateStructureKind.THREE_D)) == "structure"
    assert column(LoadHostPotential()) == "structure"
    assert column(AttachHostPotential()) == "structure"
    assert column(CreateHostPotential()) == "structure"
    assert column(BuildEmbedding()) == "structure"
    assert column(StartOver()) == "structure"
    assert column(CustomTask()) == "calculate"


def test_structure_and_calculation_columns_track_workspace_state(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)

    def names(widget):
        return {
            button.accessibleName()
            for button in widget.findChildren(QAbstractButton)
        }

    assert window._structure_title.text() == "Start with..."
    assert window._subtitle.isHidden()
    assert window.findChild(QLabel, "workflowCalculateTitle").text() == "Calculate"
    assert "Create a 3D Structure" in names(window._structure_actions)
    assert "Load a Structure" in names(window._structure_actions)
    assert not window._actions.has_actions
    assert window._calculate_notice.text() == (
        "First, create a structure or load an existing structure or potential."
    )
    assert window._custom_button.text() == "Custom Input File"
    assert not window._repeat_button.isEnabled()

    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()

    assert window._structure_title.text() == "Structure"
    assert not window._structure_overview.isHidden()
    assert "Edit Structure" in names(window._structure_actions)
    assert "Save Structure" in names(window._structure_actions)
    assert window._actions.has_actions
    assert window._custom_button.text() == "Custom Calculation"
    assert "Visualize Structure" not in names(window._structure_actions)
    assert "Start Over" not in names(window._structure_actions)
    assert "Edit Structure" not in names(window._actions)
    assert "Visualize Structure" not in names(window._actions)
    assert all("SCF" not in name for name in names(window._structure_actions))

    window.controller.reset()
    application.processEvents()
    assert window._structure_title.text() == "Start with..."
    assert not window._actions.has_actions
    assert window._custom_button.text() == "Custom Input File"
    window.close()


def test_column_headings_align_and_columns_remain_equal_on_resize(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.showNormal()
    window.resize(1920, 850)
    application.processEvents()

    structure = window.findChild(QWidget, "workflowStructureColumn")
    calculate = window.findChild(QWidget, "workflowCalculateColumn")
    results = window.findChild(QWidget, "workflowResultsColumn")
    columns = (structure, calculate, results)
    assert all(column is not None for column in columns)

    headings = (
        window._structure_title,
        window.findChild(QLabel, "workflowCalculateTitle"),
        window.findChild(QLabel, "workflowResultsTitle"),
    )
    assert len({heading.font().pointSizeF() for heading in headings}) == 1
    assert len({heading.mapTo(window, QPoint(0, 0)).y() for heading in headings}) == 1

    assert not window._actions.has_actions
    assert window._calculate_notice.isVisible()
    assert window._calculate_notice.text() == "First, create or load the structure."
    assert window._calculate_notice.alignment() & Qt.AlignmentFlag.AlignHCenter

    row = window._columns_layout
    assert row.count() == 3
    assert [row.itemAt(i).widget() for i in range(3)] == list(columns)
    assert [row.stretch(i) for i in range(3)] == [1, 1, 1]
    assert row.spacing() == 8  # Preserve gaps between the content columns.
    root_layout = window.centralWidget().layout()
    assert root_layout.itemAt(0).layout() is row
    assert root_layout.itemAt(0).widget() is None
    for column in columns[:2]:
        header = column.layout().itemAt(0).widget()
        body = column.layout().itemAt(1).widget()
        assert header._button_row.spacing() == 2
        assert column.layout().contentsMargins().right() == 0
        assert body.layout().contentsMargins().right() == 24

    def equal_thirds():
        widths = [column.width() for column in columns]
        assert max(widths) - min(widths) <= 1
        return widths

    full_widths = equal_thirds()
    assert min(full_widths) >= 3 * 200 + 2 * 2
    assert all(bar._mode == "short" for bar in window._header_bars)
    assert window._calculate_navigation.layout().contentsMargins().right() == 24
    window.resize(1360, 800)
    application.processEvents()
    narrow_widths = equal_thirds()
    assert all(narrow < full for narrow, full in zip(narrow_widths, full_widths))
    assert all(bar._mode == "icon" for bar in window._header_bars)
    window.close()


def test_recent_potential_load_rebuilds_workflow_once(tmp_path, monkeypatch):
    """Changing a recent position must not rebuild the loaded structure twice."""
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    old_path = tmp_path / "old.pot"
    other_path = tmp_path / "other.pot"
    old_path.touch()
    other_path.touch()
    gui.recent_files.remember("structure", old_path)
    gui.recent_files.remember("structure", other_path)

    atoms = Atoms("Fe", cell=(3, 3, 3), pbc=True)
    monkeypatch.setattr(
        workflow_module.file_flows.Potential, "is_cluster_file",
        staticmethod(lambda _path: False),
    )

    def load_candidate(_path, _parent, *, reader, on_loaded):
        candidate = SimpleNamespace(atoms=atoms)
        on_loaded(candidate)
        return candidate

    monkeypatch.setattr(
        workflow_module.file_flows, "load_structure_candidate", load_candidate,
    )

    rendered = []
    for widget in (window._structure_actions, window._actions):
        original = widget.set_plan

        def count(plan, *, original=original):
            rendered.append(plan)
            original(plan)

        monkeypatch.setattr(widget, "set_plan", count)

    window._continue_recent("structure", str(old_path))
    assert gui.controller.atoms is atoms
    assert gui.recent_files.paths("structure")[0] == str(old_path)
    assert len(rendered) == 2  # One refresh, two action columns.

    window.close()



def test_hostless_recent_cluster_refreshes_only_once(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    rendered = []
    original = window._structure_actions.set_plan

    def count(plan):
        rendered.append(plan)
        original(plan)

    monkeypatch.setattr(window._structure_actions, "set_plan", count)
    path = tmp_path / "without-host.clu.pot"
    gui.controller.load_unresolved_cluster(object(), path)
    assert len(rendered) == 1
    assert gui.controller.unresolved_cluster_path == path.resolve()

    # This read-only plan has no recent-file menu to update.
    gui.recent_files.remember("structure", path)
    assert len(rendered) == 1
    window.close()



def test_result_only_notification_does_not_rebuild_workflow(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    calls = []
    original = window._structure_actions.set_plan

    def record(plan):
        calls.append(plan)
        original(plan)

    monkeypatch.setattr(window._structure_actions, "set_plan", record)
    gui.controller.resultChanged.emit(object())
    assert calls == []
    window.close()


def test_recent_history_still_refreshes_empty_workspace(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    rendered = []
    original = window._structure_actions.set_plan

    def count(plan):
        rendered.append(plan)
        original(plan)

    monkeypatch.setattr(window._structure_actions, "set_plan", count)
    gui.recent_files.remember("structure", tmp_path / "earlier.xyz")
    assert len(rendered) == 1
    window.close()


def test_workspace_signals_refresh_semantic_plan(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)

    assert CreateStructure(CreateStructureKind.THREE_D) in _commands(window)

    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    assert RunTask("scf") in _commands(window)
    assert CreateStructure(CreateStructureKind.THREE_D) not in _commands(window)

    window.controller.reset()
    application.processEvents()
    assert CreateStructure(CreateStructureKind.THREE_D) in _commands(window)
    window.close()


def test_python_bulk_keeps_embedding_action_reachable_in_small_window(tmp_path, monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QPushButton, QScrollArea

    from ase2sprkkr_gui.gui.application.shell_history import PythonReplHistory, ShellHistory
    from ase2sprkkr_gui.gui.dialogs.structures import shell

    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard
    )
    _gui, window = _workflow(tmp_path)

    def select_from_python(parent, **kwargs):
        dialog = shell.StructureShellDialog(
            parent, **kwargs,
            history=ShellHistory(tmp_path / "shell.json"),
            python_history=PythonReplHistory(tmp_path / "python_history"),
        )
        QTimer.singleShot(0, lambda: dialog.console.process_input(
            "use(bulk('Fe', 'bcc', a=2.87, cubic=True))"
        ))
        assert dialog.exec() == dialog.DialogCode.Accepted
        return dialog.candidate

    monkeypatch.setattr(shell, "select_shell_structure", select_from_python)
    try:
        window.show()
        window.execute_workflow_command(CreateStructure(CreateStructureKind.SHELL))
        application.processEvents()
        assert window.controller.structure_kind() == "3d"
        assert BuildEmbedding() in _commands(window)

        window.resize(1120, 600)
        application.processEvents()
        assert window.height() == 600
        scroll = window.findChild(QScrollArea, "workflowStructureActionsScrollArea")
        assert scroll is not None
        buttons = window._structure_actions.findChildren(QPushButton)
        embedding = next(b for b in buttons if b.accessibleName() == "Build Embedded Cluster")
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.ensureWidgetVisible(embedding, 0, 0)
        application.processEvents()
        top_left = embedding.mapTo(scroll.viewport(), embedding.rect().topLeft())
        assert scroll.viewport().rect().contains(top_left)
        assert scroll.viewport().rect().contains(
            embedding.mapTo(scroll.viewport(), embedding.rect().bottomRight())
        )
        # Scrolling must preserve complete cards and their spacing inside a group.
        siblings = embedding.parentWidget().findChildren(QPushButton)
        for above, below in zip(siblings, siblings[1:]):
            assert above.geometry().bottom() < below.geometry().top()
    finally:
        window.close()


def test_typed_commands_are_dispatched_without_title_interpretation(
    tmp_path, monkeypatch
):
    _application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    events = []

    monkeypatch.setattr(
        window,
        "_prepare_task",
        lambda task: events.append(("task", task)),
    )
    monkeypatch.setattr(window, "_update_empty_spheres", lambda: events.append("spheres"))
    monkeypatch.setattr(window, "_create_3d", lambda: events.append("create-3d"))
    monkeypatch.setattr(window, "_create_shell", lambda: events.append("create-shell"))
    monkeypatch.setattr(
        window, "_create_from_database", lambda: events.append("prototype")
    )
    monkeypatch.setattr(window, "_create_surface", lambda: events.append("surface"))
    monkeypatch.setattr(
        window, "_create_transition", lambda: events.append("transition")
    )
    monkeypatch.setattr(
        window,
        "_build_2d",
        lambda _checked=False, *, surface_mode=False: events.append(
            ("build-2d", surface_mode)
        ),
    )
    monkeypatch.setattr(
        workflow_module.structure_flows, "build_embedding_structure",
        lambda *args: events.append("build-embedding"),
    )
    monkeypatch.setattr(window, "_download_structure", lambda: events.append("download"))
    monkeypatch.setattr(window, "_load_structure", lambda: events.append("load-structure"))
    monkeypatch.setattr(window, "_load_output", lambda: events.append("load-output"))
    monkeypatch.setattr(
        window,
        "_continue_recent",
        lambda kind, path: events.append(("recent", kind, path)),
    )
    monkeypatch.setattr(window, "_visualize_structure", lambda: events.append("view"))
    monkeypatch.setattr(
        workflow_module.structure_flows, "edit_structure",
        lambda *_args, **_kwargs: events.append("edit"),
    )
    monkeypatch.setattr(window, "_save_structure", lambda: events.append("save"))
    monkeypatch.setattr(
        workflow_module.file_flows, "load_host_potential",
        lambda *_args: events.append("load-host"),
    )
    monkeypatch.setattr(
        workflow_module.file_flows, "attach_host_potential",
        lambda *_args: events.append("attach-host"),
    )
    monkeypatch.setattr(
        workflow_module.file_flows, "create_host_potential",
        lambda *_args: events.append("create-host"),
    )
    monkeypatch.setattr(
        window, "_use_for_new_calculation", lambda: events.append("new-calculation")
    )
    monkeypatch.setattr(window, "_start_over", lambda: events.append("reset"))

    commands = (
        RunTask("scf"),
        UpdateEmptySpheres(),
        CreateStructure(CreateStructureKind.THREE_D),
        CreateStructure(CreateStructureKind.PROTOTYPE),
        CreateStructure(CreateStructureKind.SHELL),
        CreateStructure(CreateStructureKind.SURFACE),
        CreateStructure(CreateStructureKind.TWO_D),
        Build2D(Build2DKind.SURFACE),
        Build2D(Build2DKind.STRUCTURE),
        BuildEmbedding(),
        Load(LoadKind.ONLINE_STRUCTURE),
        Load(LoadKind.STRUCTURE),
        Load(LoadKind.OUTPUT),
        ContinueRecent("output", "/tmp/result.out"),
        VisualizeStructure(),
        EditStructure(),
        SaveStructure(),
        LoadHostPotential(),
        AttachHostPotential(),
        CreateHostPotential(),
        UseForNewCalculation(),
        StartOver(),
    )
    for command in commands:
        window.execute_workflow_command(command)

    assert events == [
        ("task", "scf"),
        "spheres",
        "create-3d",
        "prototype",
        "create-shell",
        "surface",
        "transition",
        ("build-2d", True),
        ("build-2d", False),
        "build-embedding",
        "download",
        "load-structure",
        "load-output",
        ("recent", "output", "/tmp/result.out"),
        "view",
        "edit",
        "save",
        "load-host",
        "attach-host",
        "create-host",
        "new-calculation",
        "reset",
    ]
    window.close()


def test_cancelled_first_stage_preserves_existing_structure(tmp_path, monkeypatch):
    _gui, window = _workflow(tmp_path)
    existing = Atoms("Cu", cell=(2.8, 2.8, 2.8), pbc=True)
    window.controller.replace_structure(existing)
    calls = []
    monkeypatch.setattr(
        workflow_module.structure_flows, "create_structure_candidate",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        workflow_module.structure_flows, "select_build_2d_structure",
        lambda *args, **kwargs: calls.append(True),
    )

    window._create_surface()

    assert calls == []
    assert window.controller.atoms is existing
    window.close()


def test_new_2d_flow_only_publishes_final_structure(tmp_path, monkeypatch):
    from ase2sprkkr_gui.gui.flows.structure_candidates import StructureCandidate

    _gui, window = _workflow(tmp_path)
    bulk = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    layer = Atoms("Ni", cell=(3, 3, 9), pbc=(True, True, False))
    original_generation = window.controller.structure_generation
    original_atoms = window.controller.atoms
    monkeypatch.setattr(
        workflow_module.structure_flows, "create_structure_candidate",
        lambda *args, **kwargs: StructureCandidate(bulk),
    )

    def select(candidate, **kwargs):
        assert candidate is not bulk
        assert window.controller.atoms is original_atoms
        assert window.controller.structure_generation == original_generation
        assert kwargs["surface_mode"] is True
        return layer

    monkeypatch.setattr(
        workflow_module.structure_flows, "select_build_2d_structure", select,
    )
    window._create_surface()

    assert window.controller.atoms is layer
    assert window.controller.structure_generation == original_generation.next()
    window.close()


import pytest


@pytest.mark.parametrize("keep_bulk", [False, True])
def test_cancel_new_2d_prompts_to_keep_or_discard_3d(tmp_path, monkeypatch, keep_bulk):
    from PyQt6.QtWidgets import QMessageBox
    from ase2sprkkr_gui.gui.flows.structure_candidates import StructureCandidate

    _gui, window = _workflow(tmp_path)
    original = Atoms("Cu", cell=(2.8, 2.8, 2.8), pbc=True)
    window.controller.replace_structure(original)
    original_generation = window.controller.structure_generation
    bulk = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    prompts = []
    monkeypatch.setattr(
        workflow_module.structure_flows, "create_structure_candidate",
        lambda *args, **kwargs: StructureCandidate(bulk),
    )
    monkeypatch.setattr(
        workflow_module.structure_flows, "select_build_2d_structure",
        lambda *args, **kwargs: None,
    )

    def ask(*args, **kwargs):
        prompts.append(args)
        assert window.controller.atoms is original
        return QMessageBox.StandardButton.Yes if keep_bulk else QMessageBox.StandardButton.No

    monkeypatch.setattr(workflow_module.structure_flows.QMessageBox, "question", ask)
    window._create_transition()

    assert len(prompts) == 1
    assert window.controller.atoms is (bulk if keep_bulk else original)
    assert window.controller.structure_generation == (
        original_generation.next() if keep_bulk else original_generation
    )
    window.close()


def test_workflow_has_fixed_header_actions_and_results_utility_footer(
    tmp_path, monkeypatch
):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    root = window.centralWidget().layout()
    assert root.count() == 1
    assert root.itemAt(0).layout() is window._columns_layout
    assert window._columns_layout.count() == 3
    assert window.findChild(QFrame, "workflowNavigation") is None
    structure = window.findChild(QWidget, "workflowStructureColumn")
    calculate = window.findChild(QWidget, "workflowCalculateColumn")
    results = window.findChild(QWidget, "workflowResultsColumn")
    navs = (
        window.findChild(QWidget, "workflowStructureNavigation"),
        window.findChild(QWidget, "workflowCalculationNavigation"),
        window.findChild(QWidget, "workflowResultsNavigation"),
    )
    assert [nav.parentWidget() for nav in navs] == [
        structure, calculate, results,
    ]
    footer = window.findChild(QFrame, "workflowResultsFooter")
    assert footer is window._results_footer
    assert footer.parentWidget() is results
    assert results.layout().itemAt(results.layout().count() - 1).widget() is footer
    assert structure.layout().indexOf(navs[0]) < structure.layout().indexOf(window._structure_title.parentWidget())
    title = window.findChild(QLabel, "workflowCalculateTitle")
    assert calculate.layout().indexOf(navs[1]) < calculate.layout().indexOf(title.parentWidget())
    results_title = window.findChild(QLabel, "workflowResultsTitle")
    assert results.layout().indexOf(navs[2]) < results.layout().indexOf(results_title)
    for heading in (window._structure_title, title, results_title):
        assert heading.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert not structure.isAncestorOf(footer)
    assert not calculate.isAncestorOf(footer)
    assert [len(nav.findChildren(QToolButton)) for nav in navs] == [2, 3, 1]
    assert [btn.text() for btn in footer.findChildren(QToolButton)] == [
        "Project Browser", "Settings", "Close",
    ]
    assert footer.frameShape() == QFrame.Shape.NoFrame
    # The footer is retained, but its horizontal ruler is removed.
    assert window.findChild(QWidget, "workflowResultsFooterSeparator") is None
    assert footer.layout().itemAt(0).spacerItem() is not None
    assert all(
        btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        and btn.iconSize().width() == 26
        and btn.iconSize().height() == 26
        and btn.height() == 68
        for btn in footer.findChildren(QToolButton)
    )
    assert window._result_actions_widget.load_result_button.parentWidget() is navs[2]
    assert all(
        nav.layout().itemAt(1 if nav is navs[1] else 0).layout() is nav._button_row
        for nav in navs
    )
    assert navs[1].layout().itemAt(0).spacerItem() is not None
    assert navs[1].layout().itemAt(2).spacerItem() is not None
    assert all(
        nav.layout().itemAt(1).spacerItem() is not None
        for nav in (navs[0], navs[2])
    )
    assert all(
        nav._button_row.itemAt(i).widget() is button
        for nav in navs
        for i, button in enumerate(nav._buttons)
    )
    assert window._result_actions_widget.import_directory_button.parentWidget() is navs[2]
    assert all(
        isinstance(button, CenteredIconToolButton)
        for button in (
            window._recent_structures_button,
            window._repeat_button,
            window._recent_results_button,
            window._project_browser_button,
            window._settings_button,
            window._close_button,
        )
    )
    assert all(
        isinstance(button, CenteredIconPushButton)
        for button in (
            window._result_actions_widget.load_result_button,
            window._result_actions_widget.import_directory_button,
        )
    )
    assert [navs[2]._button_row.itemAt(i).widget() for i in range(3)] == [
        window._recent_results_button,
        window._result_actions_widget.load_result_button,
        window._result_actions_widget.import_directory_button,
    ]
    assert window._result_actions_widget._import_controls_layout.count() == 0
    assert all(
        bar.height() == 93
        for bar in navs
    )
    assert all(button.height() == 68 for bar in navs for button in bar._buttons)
    assert all(
        button.property("twoLineUnderIcon") is True
        for bar in navs for button in bar._buttons
    )
    assert all(
        button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        for bar in navs for button in bar._buttons
        if isinstance(button, QToolButton)
    )
    assert all(
        button.iconSize() == QSize(26, 26)
        for bar in navs for button in bar._buttons
    )
    # Fixed actions and Results utilities share the neutral card treatment.
    assert all(
        "border-left: 3px solid" in btn.styleSheet()
        and "background-color:" in btn.styleSheet()
        for bar in navs for btn in bar._buttons
    )
    assert all(
        "border-left: 3px solid" in btn.styleSheet()
        and "background-color:" in btn.styleSheet()
        for btn in footer.findChildren(QToolButton)
    )
    assert all(
        btn.icon().isNull() is False
        for btn in (
            window._recent_structures_button,
            window._repeat_button,
            window._recent_results_button,
            window._project_browser_button,
            window._settings_button,
            window._close_button,
        )
    )
    assert window._start_over_button.isHidden()
    assert not window._start_over_button.isEnabled()
    assert not window._recent_structures_button.isEnabled()
    assert not window._recent_results_button.isEnabled()
    assert not window._repeat_button.isEnabled()

    actions = []
    monkeypatch.setattr(
        workflow_module.custom_flow, "choose_custom_input",
        lambda *_args, **_kwargs: actions.append("load"),
    )
    monkeypatch.setattr(
        workflow_module.custom_flow, "choose_custom_task",
        lambda *_args, **_kwargs: actions.append("custom"),
    )
    monkeypatch.setattr(
        workflow_module, "edit_settings",
        lambda settings, parent: actions.append(("settings", settings, parent)),
    )
    window.projectBrowserRequested.connect(lambda: actions.append("projects"))
    window._project_browser_button.click()
    window._load_input_button.click()
    window._custom_button.click()
    window._settings_button.click()
    assert actions == [
        "projects", "load", "custom", ("settings", gui.settings, window),
    ]
    assert gui._project_browser is not None
    assert gui._project_browser.isVisible()
    window.show()
    application.processEvents()
    window._close_button.click()
    application.processEvents()
    assert not window.isVisible()
    assert gui._project_browser is None or not gui._project_browser.isVisible()


def test_dynamic_cards_are_not_wrapped_in_extra_panels(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    assert window.findChild(QFrame, "workflowStructureCardsSurface") is None
    assert window.findChild(QFrame, "workflowCalculateCardsSurface") is None
    assert window._result_actions.frameShape() == QFrame.Shape.NoFrame

    gui.controller.replace_structure(Atoms("Fe", cell=(3, 3, 3), pbc=True))
    application.processEvents()
    assert window._actions.has_actions
    window.close()


def test_header_actions_and_results_footer_remain_visible_on_resize(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.showNormal()
    window.resize(1650, 820)
    application.processEvents()

    structure = window.findChild(QWidget, "workflowStructureColumn")
    calculate = window.findChild(QWidget, "workflowCalculateColumn")
    results = window.findChild(QWidget, "workflowResultsColumn")
    controls = (
        (structure, window._recent_structures_button),
        (calculate, window._repeat_button),
        (calculate, window._load_input_button),
        (calculate, window._custom_button),
        (results, window._recent_results_button),
        (results, window._result_actions_widget.load_result_button),
        (results, window._result_actions_widget.import_directory_button),
        (results, window._project_browser_button),
        (results, window._settings_button),
        (results, window._close_button),
    )

    def visible_and_within_columns():
        for column, button in controls:
            assert button.isVisible()
            right = button.mapTo(
                column, QPoint(button.width() - 1, 0)
            ).x()
            assert right < column.width()
            assert button.mapTo(column, QPoint(0, 0)).x() >= 0
        footer = window._results_footer
        assert footer.y() >= window._result_actions.y()
        assert footer.y() + footer.height() <= results.height()

    visible_and_within_columns()
    utility_buttons = window._results_footer.findChildren(QToolButton)
    assert max(b.width() for b in utility_buttons) - min(
        b.width() for b in utility_buttons
    ) <= 1
    window.resize(1920, 820)
    application.processEvents()
    visible_and_within_columns()
    assert all(bar._mode == "full" for bar in window._header_bars)
    window.resize(1100, 750)
    application.processEvents()
    assert window.width() < 1350  # Must not be pinned by header labels.
    visible_and_within_columns()
    assert all(bar._mode == "icon" for bar in window._header_bars)
    window.close()


def test_header_and_results_footer_keep_spacing_without_rulers(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.showNormal()
    window.resize(1600, 850)
    application.processEvents()
    headers = (
        window.findChild(QWidget, "workflowStructureNavigation"),
        window.findChild(QWidget, "workflowCalculationNavigation"),
        window.findChild(QWidget, "workflowResultsNavigation"),
    )
    for header in headers:
        assert header.minimumSizeHint().width() == 0
        assert header.minimumWidth() == 0
        assert header.height() == 93
        for button in header._buttons:
            if not button.isHidden():
                button_top = button.mapTo(header, QPoint(0, 0)).y()
                button_bottom = button_top + button.height()
                # The 68-pixel buttons are centered in the original 93-pixel header.
                expected_margin = (header.height() - button.height()) / 2
                assert abs(button_top - expected_margin) <= 1
                assert abs(header.height() - button_bottom - expected_margin) <= 1

    footer = window._results_footer
    assert footer.frameShape() == QFrame.Shape.NoFrame
    assert footer.styleSheet() == ""
    assert window.centralWidget().layout().contentsMargins().top() == 0
    assert window.centralWidget().layout().contentsMargins().bottom() == 0
    # Removing the visible lines must not alter the original 93-px headers
    # or the utility footer's 68-px controls and 12-px vertical spacing.
    assert window.findChild(QWidget, "workflowResultsFooterSeparator") is None
    assert footer.layout().itemAt(0).spacerItem() is not None
    assert footer.layout().itemAt(0).spacerItem().sizeHint().height() == 1
    assert footer.layout().contentsMargins().bottom() == 12
    assert footer.layout().spacing() == 12
    for button in footer.findChildren(QToolButton):
        assert button.height() == 68
        assert abs(
            footer.height() - button.mapTo(
                footer, QPoint(0, button.height())
            ).y() - 12
        ) <= 1
    window.close()


def test_header_buttons_keep_order_without_overlap_or_trailing_spacer(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.showNormal()

    def check_positions():
        for header in window._header_bars:
            buttons = [button for button in header._buttons if button.isVisible()]
            assert header._button_row.count() == len(header._buttons)
            middle = header is window._calculate_navigation
            assert header.layout().itemAt(1 if middle else 0).layout() is header._button_row
            assert header.layout().itemAt(2 if middle else 1).spacerItem() is not None
            assert buttons
            if middle:
                assert header.layout().itemAt(0).spacerItem() is not None
                # Keep the toolbar centered on the padded Calculate body.
                left = buttons[0].mapTo(header, QPoint(0, 0)).x()
                right = buttons[-1].mapTo(header, QPoint(buttons[-1].width(), 0)).x()
                expected_center = (header.width() - 24) / 2
                assert abs((left + right) / 2 - expected_center) <= 2
                assert left >= 0 and right <= header.width() - 24
            else:
                assert abs(buttons[0].mapTo(header, QPoint(0, 0)).x()) <= 1
            for left, right in zip(buttons, buttons[1:]):
                assert right.mapTo(header, QPoint(0, 0)).x() >= (
                    left.mapTo(header, QPoint(0, 0)).x()
                    + left.width() + header._button_row.spacing() - 1
                )

    window.resize(2140, 900)
    application.processEvents()
    check_positions()
    # All three headers must remain ordered in the smaller icon-only layout.
    window.resize(1100, 850)
    application.processEvents()
    check_positions()
    assert all(bar._mode == "icon" for bar in window._header_bars)
    # In particular, Results buttons must not jump to the far right.
    results = window._header_bars[2]
    assert window._result_actions_widget.load_result_button.x() >= 0
    assert window._result_actions_widget.import_directory_button.x() >= 0
    window.close()


def test_header_buttons_have_common_width_and_collapse_together(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.showNormal()
    window.resize(2140, 900)
    application.processEvents()

    columns = (
        window.findChild(QWidget, "workflowStructureNavigation"),
        window.findChild(QWidget, "workflowCalculationNavigation"),
        window.findChild(QWidget, "workflowResultsNavigation"),
    )
    for bar in columns:
        assert bar._mode == "full"
        for button in bar._buttons:
            if not button.isHidden():
                assert button.width() == bar.FULL_WIDTH
                assert button.height() == bar.BUTTON_HEIGHT
                assert abs(
                    button.mapTo(bar, QPoint(0, 0)).y()
                    - (bar.height() - button.height()) // 2
                ) <= 2
    assert not window._result_actions_widget.load_result_button.text() == ""
    assert all(bar._mode == "full" for bar in columns)
    assert all(
        [button.width() for button in bar._buttons if not button.isHidden()]
        == [168] * sum(not b.isHidden() for b in bar._buttons)
        for bar in columns
    )

    # Between the full and icon-only modes, shorter labels are used.
    window.resize(1600, 850)
    application.processEvents()
    assert all(bar._mode == "short" for bar in columns)
    assert all(
        button.width() == bar.SHORT_WIDTH
        for bar in columns for button in bar._buttons
        if not button.isHidden()
    )
    assert window._recent_results_button.text().startswith("Recent")
    assert window._result_actions_widget.load_result_button.text() == "Load Result"
    assert window._result_actions_widget.import_directory_button.text() == "Import Directory"
    assert window._load_input_button.text() == "Load Input"
    assert window._custom_button.text() == "Custom Input"

    # Intermediate widths keep readable text instead of switching to icons.
    window.resize(1360, 850)
    application.processEvents()
    assert all(bar._mode == "short" for bar in columns)
    window.resize(1100, 850)
    application.processEvents()
    results = columns[2]
    assert results._mode == "icon"
    assert all(bar._mode == "icon" for bar in columns)
    assert [b.width() for b in results._buttons] == [90, 68, 68]
    assert [b.width() for b in columns[1]._buttons] == [90, 68, 68]
    assert window._recent_structures_button.width() == 90
    assert all(b.width() == b.height() for b in results._buttons[1:])
    assert all(b.height() == 68 for b in results._buttons)
    assert "width: 22px" in window._recent_results_button.styleSheet()
    assert window._recent_results_button.toolButtonStyle() == (
        Qt.ToolButtonStyle.ToolButtonIconOnly
    )
    assert window._result_actions_widget.load_result_button.text() == ""
    assert window._result_actions_widget.import_directory_button.text() == ""
    assert window._result_actions_widget.load_result_button.toolTip().startswith(
        "Load Result File\\n"
    )
    assert window._recent_results_button.menu() is not None
    # Exercise custom painters both with labels and with menu arrows.
    for button in (
        window._recent_results_button,
        window._repeat_button,
        window._result_actions_widget.load_result_button,
        window._result_actions_widget.import_directory_button,
        window._settings_button,
    ):
        assert not button.grab().isNull()
    assert window._recent_results_button.width() == (
        results.COMPACT_SIZE + results.MENU_EXTRA_WIDTH
    )

    # Widening the window restores all 168-pixel buttons.
    window.resize(2140, 900)
    application.processEvents()
    assert results._mode == "full"
    assert window._result_actions_widget.load_result_button.text() == "Load Result File"
    assert window._result_actions_widget.import_directory_button.text() == (
        "Import All From Directory"
    )
    assert [b.width() for b in results._buttons] == [168, 168, 168]
    for button in results._buttons:
        assert not button.grab().isNull()
    assert all(bar._mode == "full" for bar in columns)
    window.close()


def test_footer_recent_shortcuts_and_menus_react_to_history(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    paths = {
        "structure": [tmp_path / "older.pot", tmp_path / "newer.pot"],
        "input": [tmp_path / "older.inp", tmp_path / "newer.inp"],
        "output": [tmp_path / "older.out", tmp_path / "newer.out"],
    }
    for kind, entries in paths.items():
        for entry in entries:
            entry.write_text("test")
            gui.recent_files.remember(kind, entry)
    window.showNormal()
    window.resize(2140, 900)
    application.processEvents()
    events = []
    monkeypatch.setattr(
        window, "_continue_recent",
        lambda kind, path: events.append((kind, path)),
    )
    monkeypatch.setattr(
        window, "execute_workflow_command",
        lambda command: events.append(command),
    )
    for kind, button in (
        ("structure", window._recent_structures_button),
        ("input", window._repeat_button),
        ("output", window._recent_results_button),
    ):
        assert button.isEnabled()
        assert button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
        assert button.text().split("\n", 1)[0] == {
            "structure": "Recent Structures",
            "input": "Repeat Calculation",
            "output": "Recent Results",
        }[kind]
        assert "\n" in button.text()
        assert paths[kind][1].name in button.text()
        assert "…/" not in button.text()
        assert str(tmp_path) not in button.text()
        assert str(paths[kind][1]) in button.toolTip()
        assert "width: 28px" in button.styleSheet()
        button.click()
        button.menu().actions()[1].trigger()

    assert events[:2] == [
        ("structure", str(paths["structure"][1])),
        ("structure", str(paths["structure"][0])),
    ]
    from ase2sprkkr_gui.gui.workflow.model import (
        LoadAllRecentResults, RepeatRecentInput,
    )
    assert events[2:4] == [
        RepeatRecentInput(str(paths["input"][1])),
        RepeatRecentInput(str(paths["input"][0])),
    ]
    assert events[4:6] == [
        ("output", str(paths["output"][1])),
        ("output", str(paths["output"][0])),
    ]
    output_menu = window._recent_results_button.menu()
    assert output_menu.actions()[-2].isSeparator()
    assert output_menu.actions()[-1].text() == "Load all results"
    output_menu.actions()[-1].trigger()
    assert events[-1] == LoadAllRecentResults()

    window.showNormal()
    window.resize(1600, 800)
    application.processEvents()
    assert window._recent_results_button.toolTip().startswith(
        "Recent Results\\n"
    )
    assert window._repeat_button.toolTip().find(str(paths["input"][1])) > 0

    gui.controller.replace_structure(Atoms("Fe", cell=(3, 3, 3), pbc=True))
    application.processEvents()
    assert window._start_over_button.isEnabled()
    assert not window._start_over_button.isHidden()
    assert window._custom_button.accessibleName() == "Custom Calculation"
    assert window._custom_button.text() == "Custom Calculation"
    gui.controller.reset()
    window.close()


def test_external_structure_viewer_lives_under_preview_fit(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    assert not hasattr(window._structure_actions, "external_viewer_button")
    gui.controller.replace_structure(Atoms("Fe", cell=(3, 3, 3), pbc=True))
    application.processEvents()
    preview = window._structure_overview.preview
    controls = preview.layout().itemAt(1).layout()
    fit_index = next(
        i for i in range(controls.count())
        if controls.itemAt(i).widget() is preview.fit_button
    )
    assert controls.itemAt(fit_index + 1).widget() is (
        window._structure_overview.external_viewer_button
    )
    viewer = window._structure_overview.external_viewer_button
    assert viewer.text() == "Viewer"
    assert viewer.toolTip() == "External viewer"
    assert viewer.height() == 68
    assert window._structure_overview.frameShape() == QFrame.Shape.NoFrame
    calls = []
    monkeypatch.setattr(
        workflow_module.visualization_flow, "visualize_structure",
        lambda *args: calls.append(args),
    )
    window._structure_overview.external_viewer_button.click()
    assert calls == [(gui.controller, gui.settings, window)]
    gui.controller.reset()
    window.close()


def test_main_window_close_also_closes_project_browser(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    window.show()
    gui.show_project_browser()
    assert gui._project_browser is not None
    assert gui._project_browser.isVisible()

    # Window-manager close uses the same application shutdown route.
    window.close()
    application.processEvents()

    assert not window.isVisible()
    assert gui._project_browser is None or not gui._project_browser.isVisible()


def test_cancelled_exit_keeps_workflow_and_browser_open(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    gui, window = _workflow(tmp_path)
    window.show()
    gui.show_project_browser()
    monkeypatch.setattr(gui, "_confirm_unsaved_work", lambda: False)

    window._close_button.click()
    application.processEvents()

    assert window.isVisible()
    assert gui._project_browser is not None
    assert gui._project_browser.isVisible()

    # A cancelled shutdown does not poison a subsequent accepted exit.
    monkeypatch.setattr(gui, "_confirm_unsaved_work", lambda: True)
    window.close()
    application.processEvents()
    assert not window.isVisible()
    assert gui._project_browser is None or not gui._project_browser.isVisible()




def test_guided_save_structure_writes_normal_atoms_without_running(tmp_path, monkeypatch):
    from ase2sprkkr_gui.gui.flows import files as file_flows
    from ase2sprkkr_gui.gui.workflow.model import WorkflowSection

    _application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    structure = Atoms("Fe", cell=[2.87] * 3, pbc=True)
    window.controller.replace_structure(structure)
    expected = tmp_path / "bulk.xyz"
    monkeypatch.setattr(
        file_flows.QFileDialog, "getSaveFileName",
        lambda *_args: (str(expected), "XYZ (*.xyz)"),
    )
    commands = tuple(
        action.command
        for action in window.workflow_plan.group(WorkflowSection.VIEW).actions
    )
    assert commands == (VisualizeStructure(), SaveStructure())
    window.execute_workflow_command(SaveStructure())
    assert expected.is_file()
    assert not window.controller.has_unsaved_structure
    assert window.controller.atoms is structure
    window.close()


def test_save_embedded_cluster_from_shutdown_keeps_host_and_writes_both_files(
    tmp_path, monkeypatch,
):
    from ase2sprkkr_gui.ase.embedding import EmbeddingDraft
    from ase2sprkkr_gui.gui.flows import files as file_flows

    application = QApplication.instance() or QApplication([])
    gui, workflow = _workflow(tmp_path)
    periodic_host = Atoms("Fe", cell=[2.87] * 3, pbc=True)
    draft = EmbeddingDraft(periodic_host)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    gui.controller.replace_structure(cluster)
    assert gui.controller.has_unsaved_structure
    assert gui.controller.atoms.embedding_host is periodic_host

    destination = tmp_path / "embedded.clu"
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Save,
    )
    monkeypatch.setattr(
        file_flows.QFileDialog, "getSaveFileName",
        lambda *_args: (str(destination), "SPR-KKR cluster potential (*.clu *.pot)"),
    )

    assert gui._confirm_unsaved_work()
    assert destination.is_file()
    assert (tmp_path / "embedded.host.pot").is_file()
    assert not gui.controller.has_unsaved_structure
    assert gui.controller.atoms.embedding_host is periodic_host
    workflow.close()


def test_guided_structure_sidebar_tracks_current_structure(tmp_path):
    """Structure facts stay separate from actions and results."""
    from ase.build import bulk
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.show()
    application.processEvents()

    assert window._columns_layout.count() == 3
    assert window._structure_overview.isHidden()

    atoms = bulk("Fe", "bcc", a=2.87, cubic=True)
    window.controller.replace_structure(atoms)
    application.processEvents()

    inspector = window._structure_overview
    assert not inspector.isHidden()
    assert "Type: Bulk (3D)" in inspector.details.text()
    assert "Elements: Fe" in inspector.details.text()
    assert "Periodicity: x, y, z (3D)" in inspector.details.text()
    assert "Cell (Å)" in inspector.details.text()
    assert inspector.preview_source.count() == 1
    assert not window._subtitle.isVisible()

    window.controller.reset()
    application.processEvents()
    assert inspector.isHidden()
    assert window._subtitle.isVisible()
    window.close()

def test_action_cards_are_equal_height_across_both_guided_columns(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.show()
    application.processEvents()

    def card_heights():
        cards = (
            window._structure_actions.findChildren(QAbstractButton)
            + window._actions.findChildren(QAbstractButton)
        )
        assert cards
        return {card.height() for card in cards}

    assert len(card_heights()) == 1
    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    assert len(card_heights()) == 1

    window.showNormal()
    window.resize(1400, 800)
    application.processEvents()
    assert len(card_heights()) == 1
    window.close()


def test_introductory_cluster_action_appears_without_structure_and_can_be_hidden(
    tmp_path, monkeypatch,
):
    gui, window = _workflow(tmp_path)
    assert ExplainEmbedding() in _commands(window)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args: QMessageBox.StandardButton.No,
    )

    window.execute_workflow_command(ExplainEmbedding())

    assert gui.settings.show_embedded_cluster_hint is False
    assert ExplainEmbedding() not in _commands(window)
    saved = gui.settings.__class__(gui.settings.path)
    saved.load()
    assert saved.show_embedded_cluster_hint is False
    window.close()
