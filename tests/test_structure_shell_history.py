"""History for the Create by Python Shell, including optional CPython sharing."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.application.shell_history import (
    PythonReplHistory, ShellHistory, default_shell_history_path,
    python_repl_history_path,
)
from ase2sprkkr_gui.gui.dialogs.structures.shell import StructureShellDialog


def _app():
    return QApplication.instance() or QApplication([])


def _enter(dialog, source):
    dialog.console.insert_input_text(source)
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Return)
    for _ in range(10):
        _app().processEvents()


def _settings(tmp_path, shared=True):
    settings = ApplicationSettings(tmp_path / "settings.json")
    settings.share_python_shell_history = shared
    return settings


def _dialog(tmp_path, *, shared=True):
    history = ShellHistory(tmp_path / "own.json")
    repl = PythonReplHistory(tmp_path / "python_history")
    return StructureShellDialog(
        settings=_settings(tmp_path, shared=shared),
        history=history, python_history=repl,
    ), history, repl


def test_history_path_uses_platformdirs(monkeypatch, tmp_path):
    from ase2sprkkr_gui.gui.application import shell_history

    monkeypatch.setattr(
        shell_history.platformdirs, "user_state_dir",
        lambda name, appauthor: str(tmp_path / name / appauthor),
    )
    assert default_shell_history_path() == (
        tmp_path / "ase2sprkkr_gui" / "ase2sprkkr" / "python_shell_history.json"
    )


def test_regular_python_path_respects_version_and_environment(
    monkeypatch, tmp_path
):
    override = tmp_path / "custom_history"
    monkeypatch.setenv("PYTHON_HISTORY", str(override))
    path = python_repl_history_path()
    if sys.version_info >= (3, 13) and not sys.flags.ignore_environment:
        assert path == override
    else:
        assert path == __import__("pathlib").Path.home() / ".python_history"


def test_own_history_round_trip_multiline_and_invalid_content(tmp_path):
    store = ShellHistory(tmp_path / "shell_history.json")
    commands = ["x = 1", "if True:\n    x = 2", "print(x)"]
    assert store.load() == []
    store.save(commands)
    assert store.load() == commands

    store.path.write_text("{oops", encoding="utf-8")
    assert store.load() == []
    store.path.write_text('["ok", 2]', encoding="utf-8")
    assert store.load() == []


def test_python_history_import_and_append_without_overwriting(tmp_path):
    store = PythonReplHistory(tmp_path / "python_history")
    store.path.write_text("python_only = 10\n", encoding="utf-8")
    store.append(["guy_only = 20", "if True:\n    answer = 42"])
    assert store.path.read_bytes().startswith(b"python_only = 10\n")
    assert store.load() == [
        "python_only = 10",
        "guy_only = 20",
        "if True:\n    answer = 42",
    ]


def test_python_history_legacy_editline_import_and_append(tmp_path):
    store = PythonReplHistory(tmp_path / "python_history")
    store.path.write_bytes(b"_HiStOrY_V2_\nold = 1\n")
    assert store.load() == ["old = 1"]
    store.append(["if True:\n    answer = 42"])
    assert store.path.read_bytes().startswith(b"_HiStOrY_V2_\n")
    assert store.load() == ["old = 1", "if True:\n    answer = 42"]


def test_persistent_commands_are_restored_without_execution(tmp_path):
    _app()
    first, history, repl = _dialog(tmp_path)
    _enter(first, "x = 42")
    assert history.load() == ["x = 42"]
    assert repl.load() == ["x = 42"]
    first.reject()

    second, _, _ = _dialog(tmp_path)
    assert "x" not in second.console.interpreter.locals
    QTest.keyClick(second.console.edit, Qt.Key.Key_Up)
    assert second.console.input_buffer() == "x = 42"
    assert "x" not in second.console.interpreter.locals
    second.reject()


def test_last_use_command_is_saved_after_dialog_acceptance(tmp_path):
    _app()
    dialog, history, repl = _dialog(tmp_path)
    _enter(dialog, "atoms = Atoms('Fe')")
    _enter(dialog, "use(atoms)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert isinstance(dialog.candidate, Atoms)
    expected = ["atoms = Atoms('Fe')", "use(atoms)"]
    assert history.load() == expected
    assert repl.load() == expected


def test_history_is_saved_on_cancel_and_exceptions(tmp_path):
    _app()
    dialog, history, repl = _dialog(tmp_path)
    _enter(dialog, "raise ValueError('bad')")
    assert history.load() == ["raise ValueError('bad')"]
    dialog.reject()
    assert history.load() == repl.load()


def test_sharing_disabled_still_restores_and_saves_ase2sprkkr_gui_history(tmp_path):
    _app()
    history = ShellHistory(tmp_path / "own.json")
    repl = PythonReplHistory(tmp_path / "python_history")
    history.save(["own = 12"])
    repl.append(["python_only = 24"])
    original_python = repl.path.read_bytes()

    dialog = StructureShellDialog(
        settings=_settings(tmp_path, shared=False),
        history=history, python_history=repl,
    )
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Up)
    assert dialog.console.input_buffer() == "own = 12"
    assert "own" not in dialog.console.interpreter.locals
    # Clear the recalled, unexecuted input before running a new command.
    dialog.console.clear_input_buffer()
    _enter(dialog, "new = 99")
    dialog.reject()
    assert history.load() == ["own = 12", "new = 99"]
    assert repl.path.read_bytes() == original_python


def test_shared_python_commands_load_but_are_not_copied_to_private_store(tmp_path):
    _app()
    own = ShellHistory(tmp_path / "own.json")
    repl = PythonReplHistory(tmp_path / "python_history")
    own.save(["own_only = 1"])
    repl.append(["python_only = 2"])

    dialog = StructureShellDialog(
        settings=_settings(tmp_path), history=own, python_history=repl
    )
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Up)
    assert dialog.console.input_buffer() == "python_only = 2"
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Up)
    assert dialog.console.input_buffer() == "own_only = 1"
    assert "python_only" not in dialog.console.interpreter.locals
    dialog.reject()
    assert own.load() == ["own_only = 1"]


def test_multiline_shell_input_is_shared_as_one_command(tmp_path):
    _app()
    dialog, own, repl = _dialog(tmp_path)
    block = "if True:\n    x = 5\nprint(x)"
    _enter(dialog, block)
    assert own.load() == [block]
    assert repl.load() == [block]
    dialog.reject()


def test_history_share_setting_defaults_true_and_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)
    assert settings.share_python_shell_history is True
    settings.share_python_shell_history = False
    assert settings.save()
    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.share_python_shell_history is False
    assert json.loads(path.read_text())["share_python_shell_history"] is False
