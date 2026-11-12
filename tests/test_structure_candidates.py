from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
import pytest

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.dialogs.structures import build_2d as build_2d_dialog
from guy4ase.gui.flows import structure_candidates as candidate_flows
from guy4ase.gui.flows.structure_candidates import StructureCandidate


def test_structure_candidate_load_has_no_workspace_side_effects(tmp_path):
    path = tmp_path / "replacement.cif"
    loaded = Atoms("Fe")
    workspace_atoms = Atoms("Cu")
    workspace = WorkspaceState(
        atoms=workspace_atoms,
        potential_path="Cu.pot",
    )
    generation = workspace.structure.generation

    candidate = candidate_flows.load_structure_candidate(
        path,
        None,
        reader=lambda value: loaded if value == path.resolve() else None,
    )

    assert candidate == StructureCandidate(loaded, path.resolve())
    assert workspace.structure.value.atoms is workspace_atoms
    assert workspace.structure.value.potential_path == "Cu.pot"
    assert workspace.structure.generation == generation


def test_build_2d_replacement_uses_shared_structure_source(monkeypatch):
    loaded = Atoms("Fe")
    recent_files = object()
    assigned = []
    calls = []
    dialog = SimpleNamespace(
        _recent_files=recent_files,
        _set_right_atoms=assigned.append,
    )

    def select(*args, **kwargs):
        calls.append((args, kwargs))
        return StructureCandidate(loaded)

    monkeypatch.setattr(build_2d_dialog, "select_structure_source", select)

    build_2d_dialog.Build2DStructureDialog._on_choose_right(dialog)

    assert assigned == [loaded]
    assert calls == [
        (
            (dialog,),
            {
                "recent_files": recent_files,
                "title": "Choose Replacement Structure",
            },
        )
    ]


def _build_2d_match_dialog():
    statuses = []
    changed = []
    dialog = SimpleNamespace(
        _axis=SimpleNamespace(currentData=lambda: 2),
        _set_status=lambda message, **kwargs: statuses.append((message, kwargs)),
        _structures_changed=lambda: changed.append(True),
    )
    return dialog, statuses, changed


def test_build_2d_match_axis_handles_expected_value_error(monkeypatch):
    dialog, statuses, changed = _build_2d_match_dialog()
    pane = SimpleNamespace(atoms=object(), set_atoms=lambda atoms: None)
    other = SimpleNamespace(atoms=object())

    def fail_match(*_args, **_kwargs):
        raise ValueError("incompatible cell")

    monkeypatch.setattr(build_2d_dialog, "match_structure_axis_length", fail_match)

    build_2d_dialog.Build2DStructureDialog._match_axis(
        dialog, pane, other, "Match axis"
    )

    assert statuses == [("Match axis failed: incompatible cell", {"error": True})]
    assert changed == []


def test_build_2d_match_axis_does_not_hide_programming_errors(monkeypatch):
    dialog, _statuses, _changed = _build_2d_match_dialog()
    pane = SimpleNamespace(atoms=object(), set_atoms=lambda atoms: None)
    other = SimpleNamespace(atoms=object())

    def fail_match(*_args, **_kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(build_2d_dialog, "match_structure_axis_length", fail_match)

    with pytest.raises(RuntimeError, match="bug"):
        build_2d_dialog.Build2DStructureDialog._match_axis(
            dialog, pane, other, "Match axis"
        )


def test_build_2d_match_axis_does_not_hide_pane_errors(monkeypatch):
    dialog, _statuses, _changed = _build_2d_match_dialog()
    updated = object()
    pane = SimpleNamespace(
        atoms=object(),
        set_atoms=lambda atoms: (_ for _ in ()).throw(RuntimeError("pane bug")),
    )
    other = SimpleNamespace(atoms=object())
    monkeypatch.setattr(
        build_2d_dialog,
        "match_structure_axis_length",
        lambda *_args, **_kwargs: updated,
    )

    with pytest.raises(RuntimeError, match="pane bug"):
        build_2d_dialog.Build2DStructureDialog._match_axis(
            dialog, pane, other, "Match axis"
        )


def _copyable(value):
    return SimpleNamespace(copy=lambda: value)


def _build_2d_preview_dialog():
    statuses = []
    preview_errors = []
    ok_states = []
    dialog = SimpleNamespace(
        _result_ax=SimpleNamespace(clear=lambda: None),
        _semiinfinite_atoms=object(),
        _update_lattice_panels=lambda: None,
        _ok_button=SimpleNamespace(setEnabled=ok_states.append),
        _repeat_left=SimpleNamespace(value=lambda: 1.0),
        _repeat_right=SimpleNamespace(value=lambda: 1.0),
        _axis=SimpleNamespace(currentData=lambda: 2),
        left=SimpleNamespace(atoms=_copyable("left")),
        right=SimpleNamespace(atoms=_copyable("right")),
        _show_preview_error=preview_errors.append,
        _set_status=lambda message, **kwargs: statuses.append((message, kwargs)),
        _result_canvas=object(),
    )
    return dialog, statuses, preview_errors, ok_states


def test_build_2d_preview_handles_backend_value_error(monkeypatch):
    dialog, statuses, preview_errors, ok_states = _build_2d_preview_dialog()
    error = ValueError("incompatible cell")

    def fail_build(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(build_2d_dialog, "semiinfinite_system", fail_build)

    build_2d_dialog.Build2DStructureDialog._update_result_preview(dialog)

    assert preview_errors == [error]
    assert dialog._semiinfinite_atoms is None
    assert statuses == []
    assert ok_states == [False]


def test_build_2d_preview_does_not_hide_backend_programming_errors(monkeypatch):
    dialog, _statuses, _preview_errors, _ok_states = _build_2d_preview_dialog()

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("backend bug")

    monkeypatch.setattr(build_2d_dialog, "semiinfinite_system", fail_build)

    with pytest.raises(RuntimeError, match="backend bug"):
        build_2d_dialog.Build2DStructureDialog._update_result_preview(dialog)


def test_build_2d_preview_does_not_hide_plotting_errors(monkeypatch):
    dialog, _statuses, preview_errors, ok_states = _build_2d_preview_dialog()
    semi = object()
    monkeypatch.setattr(
        build_2d_dialog,
        "semiinfinite_system",
        lambda *_args, **_kwargs: semi,
    )

    def fail_plot(*_args, **_kwargs):
        raise RuntimeError("plot bug")

    monkeypatch.setattr(
        build_2d_dialog,
        "plot_structure_axis_projection",
        fail_plot,
    )

    with pytest.raises(RuntimeError, match="plot bug"):
        build_2d_dialog.Build2DStructureDialog._update_result_preview(dialog)

    assert preview_errors == []
    assert dialog._semiinfinite_atoms is None
    assert ok_states == [False]
