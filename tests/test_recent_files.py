"""Recent-file persistence and display-path regressions."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ase2sprkkr_gui.gui.application.config import config_home
from ase2sprkkr_gui.gui.application.recent_files import (
    RecentFiles, default_recent_files_path, find_missing_recent_paths,
)
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

def test_recent_menu_labels_do_not_touch_filesystem(tmp_path, monkeypatch):
    from ase2sprkkr_gui.gui.recent_presentation import recent_menu_items

    path = tmp_path / "missing" / "calculation.inp"
    def unexpected(*_args, **_kwargs):
        raise AssertionError("menu labels must not probe the filesystem")

    monkeypatch.setattr(Path, "resolve", unexpected)
    monkeypatch.setattr(Path, "exists", unexpected)
    items = recent_menu_items((str(path),), base=tmp_path)
    assert len(items) == 1
    assert items[0].label == "missing/calculation.inp"
    assert items[0].tooltip == str(path)


def test_background_recent_scan_only_prunes_definitely_missing(tmp_path, monkeypatch):
    existing = tmp_path / "present.cif"
    existing.touch()
    missing = tmp_path / "missing.inp"
    inaccessible = tmp_path / "inaccessible.out"
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("structure", existing)
    history.remember("input", missing)
    history.remember("output", inaccessible)
    original_stat = Path.stat

    def stat_with_network_error(path, *args, **kwargs):
        if str(path) == str(inaccessible):
            raise PermissionError("mount inaccessible")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_network_error)
    snapshot = history.read_snapshot()
    assert find_missing_recent_paths(snapshot) == {
        "input": (str(missing),),
    }


def test_checked_recent_files_cleanup_is_atomic_and_snapshot_guarded(tmp_path):
    first = tmp_path / "missing-structure.cif"
    next_file = tmp_path / "later.cif"
    first_history = RecentFiles(tmp_path / "recent.json")
    first_history.remember("structure", first)
    stale_snapshot = first_history.read_snapshot()
    first_history.remember("structure", next_file)
    notifications = []
    first_history.changed.connect(lambda: notifications.append(True))

    # A slow scan must not remove items from a newer history.
    assert not first_history.remove_known_missing(
        stale_snapshot, {"structure": (str(first),)}
    )
    assert first_history.paths("structure") == (str(next_file), str(first))
    assert notifications == []

    current = first_history.read_snapshot()
    assert first_history.remove_known_missing(
        current, {"structure": (str(first),)}
    )
    assert first_history.paths("structure") == (str(next_file),)
    assert notifications == [True]
    assert not first_history.remove_known_missing(
        current, {"structure": (str(first),)}
    )
    assert notifications == [True]


def test_result_and_potential_history_are_atomic_and_keep_output_primary(tmp_path):
    output = tmp_path / "SCF.out"
    potential = tmp_path / "SCF.pot_new"
    output.touch()
    potential.touch()
    history = RecentFiles(tmp_path / "recent.json")
    changes = []
    history.changed.connect(lambda: changes.append(history.read_snapshot()))

    history.remember_result(output, potential_path=potential)

    assert history.paths("structure") == (str(potential.resolve()),)
    assert history.paths("output") == (str(output.resolve()),)
    assert history.last_kind == "output"
    assert len(changes) == 1
    assert changes[0] == history.read_snapshot()
    history.remember_result(output, potential_path=potential)
    assert len(changes) == 1

    reloaded = RecentFiles(history.path)
    reloaded.load()
    assert reloaded.read_snapshot() == history.read_snapshot()


def test_batch_related_potentials_preserve_recent_results_and_kind(tmp_path):
    old = tmp_path / "old.out"
    latest = tmp_path / "latest.out"
    a = tmp_path / "a.pot"
    b = tmp_path / "b.clu"
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("output", old)
    history.remember("output", latest)
    before = history.paths("output")
    changes = []
    history.changed.connect(lambda: changes.append(history.read_snapshot()))

    history.remember_many(
        (("structure", a), ("structure", b)),
        preserve_last_kind=True,
    )

    assert history.paths("output") == before
    assert history.paths("structure") == (str(b.resolve()), str(a.resolve()))
    assert history.last_kind == "output"
    assert len(changes) == 1
