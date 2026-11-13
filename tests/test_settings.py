from __future__ import annotations

from ase import Atoms

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.flows import visualization


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)

    settings.load()
    assert settings.viewer == "ase"

    settings.viewer = "vmd"
    assert settings.save()

    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.viewer == "vmd"


def test_corrupt_settings_keep_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    settings = ApplicationSettings(path)
    settings.load()

    assert settings.viewer == "ase"


def test_visualization_uses_configured_viewer(monkeypatch):
    class SpecializedAtoms(Atoms):
        pass

    atoms = SpecializedAtoms(
        "Fe",
        positions=[[1.0, 2.0, 3.0]],
        cell=[4.0, 5.0, 6.0],
        pbc=[True, False, True],
    )
    atoms.info["non_viewer_state"] = lambda: None

    class Controller:
        @property
        def atoms(self):
            return atoms

    opened = []
    monkeypatch.setattr(
        visualization,
        "ase_view",
        lambda value, *, viewer: opened.append((value, viewer)),
    )

    settings = ApplicationSettings()
    settings.viewer = "ngl"
    # This test checks handoff to the configured viewer, not availability.
    monkeypatch.setattr(visualization, "viewer_unavailability", lambda name: None)

    assert visualization.visualize_structure(
        Controller(),
        settings,
        parent=None,
    )
    assert len(opened) == 1
    snapshot, viewer = opened[0]
    assert viewer == "ngl"
    assert type(snapshot) is Atoms
    assert snapshot is not atoms
    assert snapshot.symbols == atoms.symbols
    assert (snapshot.positions == atoms.positions).all()
    assert (snapshot.cell == atoms.cell).all()
    assert (snapshot.pbc == atoms.pbc).all()
    assert snapshot.info == {}
