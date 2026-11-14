"""Recent-file persistence and display-path regressions."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ase2sprkkr_gui.gui.application.config import config_home
from ase2sprkkr_gui.gui.application.recent_files import RecentFiles, default_recent_files_path
from ase2sprkkr_gui.gui.recent_presentation import recent_path_label


def test_gui_config_paths_are_under_ase2sprkkr(tmp_path, monkeypatch):
    def config_dir(appname, appauthor):
        assert (appname, appauthor) == ("ase2sprkkr", "ase2sprkkr")
        return str(tmp_path / appname)

    monkeypatch.setattr(
        "ase2sprkkr_gui.gui.application.config.platformdirs.user_config_dir",
        config_dir,
    )
    assert config_home() == tmp_path / "ase2sprkkr" / "gui"
    assert default_recent_files_path() == config_home() / "recent_files.json"


def test_recent_files_store_canonical_absolute_paths(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    target = work / "Fe.cif"
    target.touch()
    history = RecentFiles(tmp_path / "recent.json")

    monkeypatch.chdir(work)
    history.remember("structure", "Fe.cif")
    history.remember("structure", target)

    assert history.paths("structure") == (str(target.resolve()),)
    data = json.loads(history.path.read_text(encoding="utf-8"))
    assert data["recent_files"]["structure"] == [str(target.resolve())]


def test_recent_files_snapshot_captures_paths_and_last_kind_together(tmp_path):
    structure = tmp_path / "Fe.cif"
    output = tmp_path / "SCF.out"
    structure.touch()
    output.touch()
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("structure", structure)

    snapshot = history.read_snapshot()
    history.remember("output", output)

    assert snapshot.paths("structure") == (str(structure.resolve()),)
    assert snapshot.paths("output") == ()
    assert snapshot.last_kind == "structure"
    current = history.read_snapshot()
    assert current.paths("output") == (str(output.resolve()),)
    assert current.last_kind == "output"


def test_recent_files_load_canonicalizes_legacy_entries(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    target = work / "Fe.cif"
    target.touch()
    path = tmp_path / "recent.json"
    path.write_text(
        json.dumps(
            {
                "recent_files": {
                    "structure": ["Fe.cif", str(target)],
                    "input": [],
                    "output": [],
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(work)
    history = RecentFiles(path)
    history.load()

    assert history.paths("structure") == (str(target.resolve()),)


def test_recent_files_resolve_symlink_duplicates(tmp_path):
    target = tmp_path / "Fe.cif"
    target.touch()
    alias = tmp_path / "alias.cif"
    try:
        alias.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    history = RecentFiles(tmp_path / "recent.json")
    history.remember("structure", alias)
    history.remember("structure", target)

    assert history.paths("structure") == (str(target.resolve()),)


def test_recent_file_save_failure_is_logged_but_model_changes(tmp_path, caplog):
    history = RecentFiles(tmp_path / "recent.json")
    history.path = tmp_path  # writing text to a directory fails
    target = tmp_path / "Fe.cif"
    target.touch()

    with caplog.at_level(logging.ERROR):
        history.remember("structure", target)

    assert history.paths("structure") == (str(target.resolve()),)
    assert "Failed to save recent files" in caplog.text


def test_recent_path_label_is_relative_only_below_base(tmp_path):
    base = tmp_path / "work"
    inside = base / "results" / "Fe.out"
    outside = tmp_path / "other" / "Cu.out"

    assert recent_path_label(inside, base) == str(Path("results") / "Fe.out")
    assert recent_path_label(outside, base) == str(outside.resolve())
    assert not recent_path_label(outside, base).startswith("..")


def test_recent_path_label_defaults_to_current_directory(tmp_path, monkeypatch):
    target = tmp_path / "results" / "Fe.out"
    monkeypatch.chdir(tmp_path)

    assert recent_path_label(target) == str(Path("results") / "Fe.out")
