"""The Ase2sprkkr CLI plug-in has the same contract as native commands."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import subprocess
import sys
from types import ModuleType

import pytest


def test_gui_command_is_discoverable():
    command_package = importlib.import_module("ase2sprkkr_gui.cli")
    names = {entry.name for entry in pkgutil.iter_modules(command_package.__path__)}
    assert "gui" in names

    command = importlib.import_module("ase2sprkkr_gui.cli.gui")
    assert command.help
    assert command.description
    command_parser = argparse.ArgumentParser()
    command.parser(command_parser)
    assert command_parser.parse_args([]) == argparse.Namespace(
        file=None, open_last=False, structure=None, input=None, output=None, job=None
    )


def test_importing_gui_command_does_not_load_qt():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import ase2sprkkr_gui.cli.gui; "
            "assert 'ase2sprkkr_gui.main' not in sys.modules; "
            "assert 'PyQt6' not in sys.modules",
        ],
        check=True,
    )


@pytest.mark.parametrize("exit_code", [0, 3])
def test_gui_command_invokes_main_with_clean_arguments(monkeypatch, exit_code):
    calls = []
    fake_main_module = ModuleType("ase2sprkkr_gui.main")

    def fake_main(*, argv):
        calls.append(argv)
        return exit_code

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "ase2sprkkr_gui.main", fake_main_module)
    command = importlib.import_module("ase2sprkkr_gui.cli.gui")

    with pytest.raises(SystemExit) as exc:
        command.run(argparse.Namespace(), {"debug": False, "profile": False})

    assert exc.value.code == exit_code
    assert calls == [[]]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["Fe.cif"], ["Fe.cif"]),
        (["result.out"], ["result.out"]),
        (["--open-last"], ["--open-last"]),
        (["--structure", "ambiguous.txt"], ["--structure", "ambiguous.txt"]),
        (["--input", "ambiguous.txt"], ["--input", "ambiguous.txt"]),
        (["--output", "ambiguous.txt"], ["--output", "ambiguous.txt"]),
        (["--job", "run-17"], ["--job", "run-17"]),
    ],
)
def test_gui_plugin_forwards_startup_options(monkeypatch, arguments, expected):
    command = importlib.import_module("ase2sprkkr_gui.cli.gui")
    command_parser = argparse.ArgumentParser()
    command.parser(command_parser)
    calls = []
    fake_main_module = ModuleType("ase2sprkkr_gui.main")
    fake_main_module.main = lambda *, argv: calls.append(argv) or 0
    monkeypatch.setitem(sys.modules, "ase2sprkkr_gui.main", fake_main_module)

    with pytest.raises(SystemExit) as exc:
        command.run(command_parser.parse_args(arguments), {})
    assert exc.value.code == 0
    assert calls == [expected]


@pytest.mark.parametrize(
    "arguments",
    [
        ["Fe.cif", "--open-last"],
        ["Fe.cif", "--output", "result.out"],
        ["Fe.cif", "--structure", "other.cif"],
        ["Fe.cif", "--job", "run-17"],
        ["--job", "run-17", "--open-last"],
    ],
)
def test_gui_plugin_rejects_multiple_startup_targets(arguments):
    command = importlib.import_module("ase2sprkkr_gui.cli.gui")
    command_parser = argparse.ArgumentParser()
    command.parser(command_parser)
    args = command_parser.parse_args(arguments)
    with pytest.raises(ValueError, match="not more than one"):
        command.startup_selection(args)
