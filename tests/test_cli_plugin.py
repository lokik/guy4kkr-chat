"""The Guy4ASE CLI plug-in has the same contract as native commands."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import subprocess
import sys
from types import ModuleType

import pytest


def test_gui_command_is_discoverable():
    command_package = importlib.import_module("guy4ase.cli")
    names = {entry.name for entry in pkgutil.iter_modules(command_package.__path__)}
    assert "gui" in names

    command = importlib.import_module("guy4ase.cli.gui")
    assert command.help
    assert command.description
    command_parser = argparse.ArgumentParser()
    command.parser(command_parser)
    assert command_parser.parse_args([]) == argparse.Namespace()


def test_importing_gui_command_does_not_load_qt():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import guy4ase.cli.gui; "
            "assert 'guy4ase.main' not in sys.modules; "
            "assert 'PyQt6' not in sys.modules",
        ],
        check=True,
    )


@pytest.mark.parametrize("exit_code", [0, 3])
def test_gui_command_invokes_main_with_clean_arguments(monkeypatch, exit_code):
    calls = []
    fake_main_module = ModuleType("guy4ase.main")

    def fake_main(*, argv):
        calls.append(argv)
        return exit_code

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "guy4ase.main", fake_main_module)
    command = importlib.import_module("guy4ase.cli.gui")

    with pytest.raises(SystemExit) as exc:
        command.run(argparse.Namespace(), {"debug": False, "profile": False})

    assert exc.value.code == exit_code
    assert calls == [[]]
