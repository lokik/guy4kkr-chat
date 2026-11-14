from __future__ import annotations

from pathlib import Path

import pytest

from ase2sprkkr_gui.gui.presentation import empty_spheres_action_title
from ase2sprkkr_gui.gui.recent_presentation import RecentLaunch, recent_launch_presentation
from ase2sprkkr_gui.gui.workspace_semantics import EmptySpheresAction


class RecentSnapshot:
    def __init__(self, *, structures=(), outputs=(), last_kind=None):
        self._paths = {
            "structure": tuple(structures),
            "input": (),
            "output": tuple(outputs),
        }
        self.last_kind = last_kind

    def paths(self, kind):
        return self._paths[kind]


def _primary(snapshot: RecentSnapshot) -> RecentLaunch | None:
    return recent_launch_presentation(snapshot).primary


def test_recent_launch_is_none_without_launchable_files():
    assert _primary(RecentSnapshot()) is None


def test_recent_launch_uses_last_kind_when_available():
    launch = _primary(
        RecentSnapshot(
            structures=("structure.cif",),
            outputs=("calculation.out",),
            last_kind="structure",
        )
    )

    assert launch == RecentLaunch("structure", "structure.cif")
    assert launch.title == "Continue: structure.cif"


def test_recent_launch_falls_back_to_output():
    assert _primary(
        RecentSnapshot(
            structures=("structure.cif",),
            outputs=("calculation.out",),
            last_kind=None,
        )
    ) == RecentLaunch("output", "calculation.out")


def test_recent_launch_falls_back_when_last_kind_is_empty():
    assert _primary(
        RecentSnapshot(structures=("structure.cif",), last_kind="output")
    ) == RecentLaunch("structure", "structure.cif")


def test_recent_launch_rejects_input_history_kind():
    with pytest.raises(ValueError, match="structure.*output"):
        RecentLaunch("input", "input.inp")  # type: ignore[arg-type]


def test_recent_launch_presentation_owns_grouping_labels_and_empty_state(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    work.mkdir()
    structure = work / "structures" / "Fe.cif"
    structure.parent.mkdir()
    structure.touch()
    output = tmp_path / "outside" / "SCF.out"
    output.parent.mkdir()
    output.touch()
    monkeypatch.chdir(work)

    presentation = recent_launch_presentation(
        RecentSnapshot(
            structures=(str(structure.resolve()),),
            outputs=(str(output.resolve()),),
            last_kind="output",
        )
    )

    assert presentation.primary == RecentLaunch("output", str(output.resolve()))
    assert tuple(group.title for group in presentation.groups) == (
        "Structures",
        "Outputs",
    )
    assert presentation.groups[0].items[0].label == str(Path("structures") / "Fe.cif")
    assert presentation.groups[0].items[0].tooltip == str(structure.resolve())
    assert presentation.groups[1].items[0].label == str(output.resolve())
    assert all(group.empty_text == "(No recent files)" for group in presentation.groups)


def test_empty_sphere_action_titles_are_shared_presentation_policy():
    assert empty_spheres_action_title(EmptySpheresAction.ADD) == "Add Empty Spheres"
    assert (
        empty_spheres_action_title(EmptySpheresAction.RECALCULATE)
        == "Recalculate Empty Spheres"
    )
