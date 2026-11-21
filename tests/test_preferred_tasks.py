"""Preferred tasks: persistence, fallback policy, editor and optional task icons."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.dialogs.task_chooser import (
    TaskChoice, TaskChooserDialog, order_choices,
)
from ase2sprkkr_gui.gui.input_parameters import task_preferences as prefs
from ase2sprkkr_gui.gui.misc import resources
from ase2sprkkr_gui.gui.misc.icons import task_icon
from ase2sprkkr_gui.gui.widgets.settings.preferred_tasks import PreferredTasksPage


def test_settings_do_not_persist_default_preferred_tasks(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)
    expected = prefs.default_preferred_task_names()
    assert "SCF" not in expected
    assert settings.effective_preferred_tasks() == expected
    assert settings.save()
    stored = json.loads(path.read_text())
    assert "preferred_tasks" not in stored
    assert "preferred_supported_tasks" not in stored

    settings.preferred_tasks = ("DOS", "SCF")
    settings.preferred_supported_snapshot = expected
    assert settings.save()
    stored = json.loads(path.read_text())
    assert stored["preferred_tasks"] == ["DOS"]
    assert stored["preferred_supported_tasks"] == list(expected)

    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.effective_preferred_tasks() == ("DOS",)
    loaded.preferred_tasks = None
    loaded.preferred_supported_snapshot = None
    assert loaded.save()
    assert "preferred_tasks" not in json.loads(path.read_text())


def test_scf_is_not_an_optional_preference(
    monkeypatch,
):
    monkeypatch.setattr(
        prefs, "supported_task_names", lambda: ("DOS", "SCF", "XAS"),
    )
    monkeypatch.setattr(
        prefs, "all_task_names", lambda: ("DOS", "SCF", "XAS", "ARPES"),
    )
    assert prefs.effective_preferred(None) == ("DOS", "XAS")
    assert prefs.effective_preferred(
        ("DOS", "SCF", "ARPES"), ("DOS", "SCF"),
    ) == ("DOS", "ARPES")


@pytest.mark.parametrize(
    ("preferred", "supported", "ordinary", "experimental", "expected"),
    (
        (("B", "A"), ("A",), ("A", "B"), ("A", "B", "C"), ("B", "A")),
        ((), ("B", "A"), ("B", "A", "C"), ("A", "B", "C"), ("A", "B")),
        ((), (), ("C", "A"), ("A", "B", "C"), ("A", "C")),
        ((), (), (), ("Z", "A"), ("A", "Z")),
    ),
)
def test_task_fallback_priority(
    monkeypatch, preferred, supported, ordinary, experimental, expected,
):
    names = set((*preferred, *supported, *ordinary, *experimental))
    registry = {
        name: SimpleNamespace(experimental=name not in ordinary)
        for name in names
    }
    monkeypatch.setattr(prefs.InputParameters, "task_registry", registry)
    monkeypatch.setattr(prefs, "supported_task_names", lambda: supported)
    monkeypatch.setattr(prefs, "applicable_task_names", lambda _kind: experimental)
    # Preferred action order must never be alphabetized. Fallbacks must.
    assert prefs.displayed_tasks("3d", preferred) == expected


def test_fallback_above_eight_suppresses_tasks_but_not_custom_action(monkeypatch):
    names = tuple(f"T{i:02d}" for i in range(9))
    monkeypatch.setattr(
        prefs.InputParameters, "task_registry",
        {name: SimpleNamespace(experimental=False) for name in names},
    )
    monkeypatch.setattr(prefs, "supported_task_names", lambda: names)
    monkeypatch.setattr(prefs, "applicable_task_names", lambda _kind: names)
    assert prefs.displayed_tasks("3d", ()) == ()
    assert prefs.displayed_tasks("3d", names) == names


def test_task_ordering_prioritizes_possible_preferred_supported_and_nonexperimental():
    rows = [
        TaskChoice("D", True, "Yes", "", preferred=False, supported=False),
        TaskChoice("B", False, "Yes", "", preferred=True, supported=False),
        TaskChoice("C", False, "Yes", "", preferred=False, supported=True),
        TaskChoice("A", True, "No", "", preferred=True, supported=True),
        TaskChoice("E", False, "Yes", "", preferred=True, supported=True),
    ]
    assert [row.name for row in order_choices(rows)] == ["E", "B", "C", "D", "A"]
    assert [row.name for row in order_choices(rows, has_structure=False)] == [
        "E", "A", "B", "C", "D",
    ]


def test_preferred_editor_omits_scf_and_restore_removes_saved_override(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)
    settings.preferred_tasks = ("DOS",)
    settings.preferred_supported_snapshot = prefs.default_preferred_task_names()
    assert settings.save()

    page = PreferredTasksPage(settings)
    defaults = prefs.default_preferred_task_names()
    assert page.selection() == ("DOS",)
    assert "SCF" not in page.selection()
    assert "SCF" not in {
        page.available.item(row, 1).text()
        for row in range(page.available.rowCount())
    }
    assert page.preference_override() == ("DOS",)

    page.restore_button.click()
    assert page.selection() == defaults
    assert page.preference_override() is None
    settings.preferred_tasks = page.preference_override()
    settings.preferred_supported_snapshot = (
        defaults if settings.preferred_tasks is not None else None
    )
    assert settings.save()
    stored = json.loads(path.read_text())
    assert "preferred_tasks" not in stored
    assert "preferred_supported_tasks" not in stored
    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.newly_supported_tasks() == ()
    page.close()


def test_named_task_icons_are_optional_and_reject_path_traversal(
    tmp_path, monkeypatch,
):
    assets = tmp_path / "assets"
    directory = assets / "task-icons"
    directory.mkdir(parents=True)
    (directory / "scf.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
        '<circle cx="12" cy="12" r="9"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setattr(resources, "_ASSETS", assets)
    assert not task_icon("SCF").isNull()
    assert task_icon("DOES_NOT_EXIST").isNull()
    assert resources.task_icon_path("../../anything") is None


@pytest.mark.parametrize(("answer", "open_settings"), (
    (QMessageBox.StandardButton.Yes, False),
    (QMessageBox.StandardButton.No, True),
))
def test_newly_supported_tasks_are_confirmed_once_on_open(
    tmp_path, monkeypatch, answer, open_settings,
):
    from ase2sprkkr_gui.main import GuiApplication
    settings_path = tmp_path / "prefs.json"
    initial = ApplicationSettings(settings_path)
    initial.preferred_tasks = ("DOS",)
    initial.preferred_supported_snapshot = ("DOS",)
    assert initial.save()

    monkeypatch.setattr(prefs, "supported_task_names",
                        lambda: ("DOS", "SCF", "XAS"))
    gui = GuiApplication(
        settings_path=settings_path,
        recent_files_path=tmp_path / "recent.json",
    )
    window = gui.create_workflow_window()
    monkeypatch.setattr(gui, "_show_window", lambda *_: None)

    messages = []
    opened = []
    monkeypatch.setattr(
        window, "_open_settings",
        lambda *, preferred_tasks=False: opened.append(preferred_tasks),
    )

    def answer_message(message):
        messages.append((message.text(), message.checkBox().isChecked()))
        message.checkBox().setChecked(open_settings)
        return answer

    monkeypatch.setattr(QMessageBox, "exec", answer_message)
    gui.show_workflow_window()

    assert len(messages) == 1
    assert "XAS" in messages[0][0]
    assert "SCF" not in messages[0][0]
    assert messages[0][1] is False
    assert opened == ([True] if open_settings else [])
    saved = ApplicationSettings(settings_path)
    saved.load()
    assert saved.preferred_supported_snapshot == ("DOS", "XAS")
    assert saved.preferred_tasks == (
        ("DOS", "XAS") if answer == QMessageBox.StandardButton.Yes
        else ("DOS",)
    )
    assert saved.newly_supported_tasks() == ()
    gui.show_workflow_window()
    assert len(messages) == 1
    window.close()


def test_new_supported_tasks_do_not_prompt_with_default_preferences(
    tmp_path, monkeypatch,
):
    from ase2sprkkr_gui.main import GuiApplication

    gui = GuiApplication(
        settings_path=tmp_path / "prefs.json",
        recent_files_path=tmp_path / "recent.json",
    )
    monkeypatch.setattr(gui, "_show_window", lambda *_: None)
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda *_: pytest.fail("No customized preference list exists"),
    )
    gui.show_workflow_window()
    gui.create_workflow_window().close()


def test_lowercase_task_icon_name_is_required(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    directory = assets / "task-icons"
    directory.mkdir(parents=True)
    (directory / "SCF.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"/>'
    )
    monkeypatch.setattr(resources, "_ASSETS", assets)
    assert resources.task_icon_path("SCF") is None
    (directory / "scf.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"/>'
    )
    assert resources.task_icon_path("SCF") == directory / "scf.svg"


def test_bsf_is_one_supported_and_selectable_gui_task():
    from ase2sprkkr_gui.gui.dialogs.task_chooser import task_choices

    assert prefs.supported_task_names().count("BSF") == 1
    assert "BSFEK" not in prefs.supported_task_names()
    assert "BSFKK" not in prefs.supported_task_names()
    assert prefs.all_task_names().count("BSF") == 1
    assert "BSFEK" not in prefs.all_task_names()
    assert "BSFKK" not in prefs.all_task_names()

    choices = task_choices()
    assert tuple(row.name for row in choices).count("BSF") == 1
    assert "BSFEK" not in {row.name for row in choices}
    assert "BSFKK" not in {row.name for row in choices}
    assert next(row for row in choices if row.name == "BSF").supported
    assert prefs.native_task_name("BSF") == "BSFEK"
    assert prefs.native_task_names("BSF") == ("BSFEK", "BSFKK")


def test_legacy_bsf_variant_preferences_collapse_to_one_bsf_without_new_task_popup(
    tmp_path,
):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "preferred_tasks": ["DOS", "BSFEK", "BSFKK", "SCF"],
        "preferred_supported_tasks": ["SCF", "BSFEK", "BSFKK", "DOS", "XAS", "ARPES", "JXC"],
    }))
    settings = ApplicationSettings(path)
    settings.load()
    assert settings.effective_preferred_tasks() == ("DOS", "BSF")
    assert settings.newly_supported_tasks() == ()
    assert settings.save()
    saved = json.loads(path.read_text())
    assert saved["preferred_tasks"] == ["DOS", "BSF"]
    assert "SCF" not in saved["preferred_supported_tasks"]
    assert "BSFEK" not in saved["preferred_supported_tasks"]
    assert "BSFKK" not in saved["preferred_supported_tasks"]
    assert "BSF" in saved["preferred_supported_tasks"]


def test_bsf_uses_one_lowercase_icon_for_both_native_modes(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    directory = assets / "task-icons"
    directory.mkdir(parents=True)
    icon_path = directory / "bsf.svg"
    icon_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
        '<rect x="2" y="2" width="20" height="20"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setattr(resources, "_ASSETS", assets)
    assert all(
        resources.task_icon_path(prefs.task_ui_name(name)) == icon_path
        for name in ("BSF", "BSFEK", "BSFKK")
    )
    assert all(
        not task_icon(name).isNull()
        for name in ("BSF", "BSFEK", "BSFKK")
    )
    assert resources.task_icon_path("BSFEK") is None


def test_preferred_task_editor_shows_only_one_bsf(tmp_path):
    page = PreferredTasksPage(ApplicationSettings(tmp_path / "settings.json"))
    assert page.selection().count("BSF") == 1
    assert "BSFEK" not in page.selection()
    assert "BSFKK" not in page.selection()
    row_names = [
        page.available.item(i, 1).text()
        for i in range(page.available.rowCount())
    ]
    assert row_names.count("BSF") == 1
    assert "BSFEK" not in row_names
    assert "BSFKK" not in row_names
    page.close()



def test_task_icons_use_separate_unlabelled_columns_on_both_task_lists(
    tmp_path, monkeypatch,
):
    assets = tmp_path / "assets"
    icon_directory = assets / "task-icons"
    icon_directory.mkdir(parents=True)
    (icon_directory / "dos.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
        '<circle cx="12" cy="12" r="8"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setattr(resources, "_ASSETS", assets)

    chooser = TaskChooserDialog()
    assert chooser.table.horizontalHeaderItem(0).text() == ""
    assert chooser.table.columnWidth(0) == 30
    assert chooser.table.verticalHeader().defaultSectionSize() == 30
    assert chooser.table.iconSize().width() == 24
    assert chooser.table.iconSize().height() == 24
    assert chooser.table.horizontalHeaderItem(1).text() == "Name"
    assert chooser._fields[:2] == ["icon", "name"]
    names = [
        chooser.table.item(row, 1).text()
        for row in range(chooser.table.rowCount())
    ]
    assert "SCF" in names
    row = names.index("DOS")
    assert chooser.table.item(row, 0).text() == ""
    assert not chooser.table.item(row, 0).icon().isNull()
    assert chooser.table.item(row, 1).icon().isNull()
    chooser._sort_by_column(0)
    assert chooser._primary is None
    chooser.close()

    page = PreferredTasksPage(ApplicationSettings(tmp_path / "settings.json"))
    assert page.available.horizontalHeaderItem(0).text() == ""
    assert page.available.columnWidth(0) == 30
    assert page.available.verticalHeader().defaultSectionSize() == 30
    assert page.available.iconSize().width() == 24
    assert page.available.iconSize().height() == 24
    assert page.available.horizontalHeaderItem(1).text() == "Name"
    available_names = [
        page.available.item(row, 1).text()
        for row in range(page.available.rowCount())
    ]
    assert "SCF" not in available_names
    row = available_names.index("DOS")
    assert page.available.item(row, 0).text() == ""
    assert not page.available.item(row, 0).icon().isNull()
    assert page.available.item(row, 1).icon().isNull()

    assert page.preferred.horizontalHeader().isHidden()
    assert page.preferred.columnWidth(0) == 30
    assert page.preferred.verticalHeader().defaultSectionSize() == 30
    assert page.preferred.iconSize().width() == 24
    assert page.preferred.iconSize().height() == 24
    right_names = [
        page.preferred.item(row, 1).text()
        for row in range(page.preferred.rowCount())
    ]
    row = right_names.index("DOS")
    assert page.preferred.item(row, 0).text() == ""
    assert not page.preferred.item(row, 0).icon().isNull()
    assert page.preferred.item(row, 1).icon().isNull()
    page.preferred.setCurrentCell(row, 1)
    page.remove_button.click()
    assert "DOS" not in page.selection()
    page.close()


def test_scf_alone_is_not_treated_as_a_new_preferred_task(tmp_path, monkeypatch):
    path = tmp_path / "prefs.json"
    settings = ApplicationSettings(path)
    settings.preferred_tasks = ("DOS",)
    settings.preferred_supported_snapshot = ("DOS",)
    assert settings.save()
    monkeypatch.setattr(
        prefs, "supported_task_names", lambda: ("DOS", "SCF"),
    )
    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.newly_supported_tasks() == ()
