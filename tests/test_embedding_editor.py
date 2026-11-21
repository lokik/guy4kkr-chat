"""Embedded-cluster editor behavior against the matching ASE2SPRKKR backend."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import pytest
from ase import Atoms
from matplotlib.backend_bases import MouseEvent

# The GUI is released independently of the still-unreleased embedding API.
pytest.importorskip("ase2sprkkr.sprkkr.embedding_geometry")

from ase2sprkkr.sprkkr.embedding_geometry import HostSite

from ase2sprkkr_gui.ase.embedding import (
    EmbeddingDraft,
    GUI_CLUSTER_CENTER,
    cell_ring_offsets,
    cluster_center,
    reset_cluster_center,
    set_cluster_center,
    embedding_source,
    occupation_label,
    parse_occupation,
)
from ase2sprkkr_gui.gui.application.structure_snapshot import StructureSnapshot
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs.structures.embedding import BuildEmbeddingDialog
from ase2sprkkr_gui.gui.flows import structures as structure_flows
from ase2sprkkr_gui.physics.lattice import detect_structure_kind


def host():
    return Atoms("Cu", cell=[2., 2., 2.], positions=[[0, 0, 0]], pbc=True)


def click_preview(preview, position, *, drag=(0, 0)):
    """Deliver real Matplotlib mouse events at a projected Cartesian position."""
    preview.canvas.draw()
    point, _ = preview.project([position])
    x, y = preview.axes.transData.transform(point[0])
    events = [("button_press_event", 0, 0)]
    if drag != (0, 0):
        events.append(("motion_notify_event", *drag))
    events.append(("button_release_event", *drag))
    for name, dx, dy in events:
        event = MouseEvent(name, preview.canvas, x + dx, y + dy, button=1)
        preview.canvas.callbacks.process(name, event)


def click_cell(dialog, cell):
    view = dialog.cells
    view.canvas.draw()
    index = view._cells.index(cell)
    point = view._polygons[index].mean(axis=0)
    x, y = view.axes.transData.transform(point)
    for name in ("button_press_event", "button_release_event"):
        view.canvas.callbacks.process(name, MouseEvent(name, view.canvas, x, y, button=1))


def test_occupation_input_is_exact_and_not_silently_renormalized():
    assert parse_occupation("Fe") == {"Fe": 1.0}
    assert parse_occupation("Fe:0.7, Ni:0.3") == {"Fe": 0.7, "Ni": 0.3}
    assert parse_occupation("Vc") == {"X": 1.0}
    assert occupation_label({"Ni": .3, "Fe": .7}) == "Ni:0.3, Fe:0.7"
    for value in ("Fe:0.2", "Cu:-0.1", "Yy", "Fe:0.5, Fe:0.5", ""):
        with pytest.raises(ValueError):
            parse_occupation(value)


def test_draft_creates_explicit_cluster_without_mutating_host():
    parent = host()
    source = parent.copy()
    center = HostSite(0, (0, 0, 0))
    draft = EmbeddingDraft(parent)
    assert draft.center == center
    assert draft.entries == {}
    draft.include([center])
    draft.set_occupation([center], {"Fe": 1.0})
    draft.set_displacement([center], [0.01, -0.02, 0.03])
    result = draft.to_atoms()
    assert result.embedding_host is parent
    assert detect_structure_kind(result) == "0d"
    assert result.sites[0].embedding.cell_index == (0, 0, 0)
    assert result.sites[0].occupation.to_dict(True) == {"Fe": 1.0}
    np.testing.assert_allclose(result.sites[0].embedding.displacement, [0.01, -0.02, 0.03])
    assert len(result) == 1
    assert np.array_equal(parent.positions, source.positions)
    assert parent.get_chemical_symbols() == ["Cu"]


def test_loaded_cluster_centre_uses_geometry_not_first_native_site():
    from ase2sprkkr import SPRKKRAtoms

    parent = host()
    cluster = SPRKKRAtoms.from_embedding(parent, [
        (0, (-2, 0, 0), "Cu"),
        (0, (0, 0, 0), "Cu"),
        (0, (1, 0, 0), "Cu"),
    ])
    assert EmbeddingDraft(parent, cluster).center == HostSite(0, (0, 0, 0))
    assert GUI_CLUSTER_CENTER not in cluster.info  # Merely opening is read-only.
    reset_cluster_center(cluster)
    assert cluster.info[GUI_CLUSTER_CENTER] == (0, 0, 0, 0, 0, 0)


def test_explicit_centre_survives_apply_copy_and_reopening_without_rebuild():
    from ase2sprkkr import SPRKKRAtoms

    parent = host()
    original = SPRKKRAtoms.from_embedding(parent, [
        (0, (-2, 0, 0), "Cu"),
        (0, (0, 0, 0), "Cu"),
        (0, (1, 0, 0), "Cu"),
    ])
    draft = EmbeddingDraft(parent, original)
    selected = HostSite(0, (1, 0, 0))
    draft.set_center(selected)
    assert not draft.is_unchanged()
    assert not draft.would_discard_radial_data()
    result = draft.to_atoms()
    assert result is not original
    assert GUI_CLUSTER_CENTER not in original.info
    assert result.info[GUI_CLUSTER_CENTER] == (0, 1, 0, 0, 0, 0)
    reopened = EmbeddingDraft(parent, result.copy())
    assert reopened.center == selected
    assert reopened.is_unchanged()
    assert result.embedding_host is parent


def test_replacement_cluster_never_inherits_previous_centre():
    from ase2sprkkr import SPRKKRAtoms

    parent = host()
    original = SPRKKRAtoms.from_embedding(parent, [
        (0, (-2, 0, 0), "Cu"),
        (0, (0, 0, 0), "Cu"),
        (0, (1, 0, 0), "Cu"),
    ])
    set_cluster_center(original, HostSite(0, (1, 0, 0)))
    replacement = SPRKKRAtoms.from_embedding(parent, [
        (0, (-2, 0, 0), "Cu"), (0, (0, 0, 0), "Cu"),
    ])
    assert GUI_CLUSTER_CENTER not in replacement.info
    assert EmbeddingDraft(parent, replacement).center == HostSite(0, (-2, 0, 0))
    # Copying the original is not replacing it; its metadata remains attached.
    assert EmbeddingDraft(parent, original.copy()).center == HostSite(0, (1, 0, 0))


def test_symmetry_preview_can_modify_real_host_sites():
    parent = host()
    draft = EmbeddingDraft(parent)
    site = HostSite(0, (1, 0, 0))
    orbit = draft.targets([site], symmetric=True)
    assert len(orbit) == 6
    draft.set_occupation(orbit, {"Fe": 1.0})
    assert len(draft.entries) == 6
    result = draft.to_atoms()
    assert len(result) == 6
    assert all(s.occupation.to_dict(True) == {"Fe": 1.0} for s in result.sites)
    assert parent.get_chemical_symbols() == ["Cu"]


def test_radius_shells_and_edit_again_preserve_host_reference():
    parent = host()
    draft = EmbeddingDraft(parent)
    assert draft.add_shells(1) == 7
    assert draft.add_radius(2.01) == 0
    centre = HostSite(0, (0, 0, 0))
    draft.set_occupation([centre], {"Fe": 1.0})
    result = draft.to_atoms()
    original = result.copy()
    assert embedding_source(result)[0] is parent
    again = EmbeddingDraft(parent, result)
    assert len(again.entries) == 7
    again.exclude([HostSite(0, (1, 0, 0))])
    edited = again.to_atoms()
    assert len(edited) == 6
    assert edited.embedding_host is parent
    assert len(result) == len(original) == 7


def test_displacement_symmetry_rejects_noninvariant_direction_without_partial_edit():
    draft = EmbeddingDraft(host())
    with pytest.raises(ValueError, match="conflicts"):
        draft.set_displacement([draft.center], [0.1, 0, 0], symmetric=True)
    assert not draft.entries


def test_snapshot_restores_embedded_occupations_positions_and_host_reference():
    parent = host()
    draft = EmbeddingDraft(parent)
    site = HostSite(0, (1, 0, 0))
    draft.set_occupation([site], {"Fe": 0.75, "Ni": 0.25})
    draft.set_displacement([site], [0, 0, 0.1])
    original = draft.to_atoms()
    snapshot = StructureSnapshot.capture(original)
    restored = snapshot.to_atoms()
    assert restored is not original
    assert restored.embedding_host is parent
    assert restored.sites[0].occupation.to_dict(True) == {"Fe": .75, "Ni": .25}
    assert restored.sites[0].embedding.cell_index == (1, 0, 0)
    np.testing.assert_allclose(restored.positions, original.positions)
    assert detect_structure_kind(restored) == "0d"


def test_snapshot_retains_gui_cluster_centre():
    parent = host()
    draft = EmbeddingDraft(parent)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    selected = HostSite(0, (1, 0, 0))
    set_cluster_center(cluster, selected)
    recovered = StructureSnapshot.capture(cluster).to_atoms()
    assert recovered.info[GUI_CLUSTER_CENTER] == (0, 1, 0, 0, 0, 0)
    assert EmbeddingDraft(parent, recovered).center == selected


def test_dialog_builds_cluster_and_is_cancel_safe():
    parent = host()
    dialog = BuildEmbeddingDialog(parent)
    dialog.occupation.set_occupation({"Fe": 1.0})
    dialog._assign_occupation()
    assert len(dialog.draft.entries) == 1
    dialog._accept()
    assert dialog.result_atoms is not None
    assert dialog.result_atoms.sites[0].occupation.to_dict(True) == {"Fe": 1.0}
    assert parent.get_chemical_symbols() == ["Cu"]


def test_flow_cancellation_leaves_workspace_unmodified(monkeypatch):
    parent = host()
    controller = WorkspaceController(WorkspaceState(atoms=parent))
    revision = controller.structure_generation
    monkeypatch.setattr(
        "ase2sprkkr_gui.gui.dialogs.structures.embedding.select_build_embedding_structure",
        lambda candidate, _parent: None,
    )
    assert structure_flows.build_embedding_structure(controller, None) is None
    assert controller.atoms is parent
    assert controller.structure_generation == revision


def test_flow_acceptance_creates_cluster_with_native_host(
    monkeypatch,
):
    parent = host()
    controller = WorkspaceController(WorkspaceState(atoms=parent, input_parameters=object()))
    def accept_cluster(candidate, _parent):
        native_host, existing = embedding_source(candidate)
        generated = EmbeddingDraft(native_host, existing)
        generated.set_occupation([generated.center], {"Fe": 1.0})
        return generated.to_atoms()

    monkeypatch.setattr(
        "ase2sprkkr_gui.gui.dialogs.structures.embedding.select_build_embedding_structure",
        accept_cluster,
    )
    result = structure_flows.build_embedding_structure(controller, None)
    assert result is controller.atoms
    assert result.embedding_host.atoms is not parent
    np.testing.assert_allclose(result.embedding_host.atoms.positions, parent.positions)
    assert controller.structure_kind() == "0d"
    assert controller.can_run_embedding()
    assert controller.can_calculate()


def test_uncomputed_embedded_structure_saves_cluster_and_generated_host(monkeypatch, tmp_path):
    from ase2sprkkr_gui.gui.flows import files as file_flows

    draft = EmbeddingDraft(host())
    draft.include([draft.center])
    cluster = draft.to_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    path = tmp_path / "cluster.clu"
    monkeypatch.setattr(
        file_flows.QFileDialog, "getSaveFileName",
        lambda *_args: (str(path), "SPR-KKR cluster potential (*.clu *.pot)"),
    )

    class Recent:
        def remember(self, kind, location):
            assert kind == "structure"
            assert location == path

    assert file_flows.save_structure(controller, Recent(), None)
    assert path.is_file()
    assert (tmp_path / "cluster.host.pot").is_file()
    assert controller.atoms is cluster
    assert cluster.embedding_host is draft.host
    assert not controller.has_unsaved_structure



def test_embedded_structure_missing_host_cannot_silently_export_as_ase(
    monkeypatch, tmp_path,
):
    from ase2sprkkr_gui.gui.flows import files as file_flows

    draft = EmbeddingDraft(host())
    draft.include([draft.center])
    cluster = draft.to_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    # Simulate a corrupted in-memory reference after a valid structure was
    # registered; the result-store snapshot deliberately rejects such input.
    cluster.info.pop("sprkkr_embedding_host")
    messages = []
    monkeypatch.setattr(
        file_flows.QMessageBox, "warning",
        lambda *_args: messages.append(_args),
    )
    monkeypatch.setattr(
        file_flows.QFileDialog, "getSaveFileName",
        lambda *_args: pytest.fail("No save dialog for an invalid embedded host"),
    )
    monkeypatch.setattr(
        file_flows, "ase_write",
        lambda *_args, **_kwargs: pytest.fail("Embedding metadata was lost"),
    )

    assert not file_flows.save_structure(controller, None, None)
    assert messages and "Host of embedded structure is missing" in messages[0][2]
    assert not hasattr(file_flows, "save_orphan_cluster")
    assert not (tmp_path / "cluster.xyz").exists()


def test_native_structure_save_uses_cluster_potential_writer(monkeypatch, tmp_path):
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

    from ase2sprkkr_gui.gui.flows import files as file_flows

    class HostPotential:
        LATTICE = object()

        def __init__(self):
            self.atoms = host()

        def save_to_file(self, filename):
            filename.write_text("HOST POT", encoding="utf-8")

    host_potential = HostPotential()
    from ase2sprkkr import Potential
    monkeypatch.setattr(Potential, "from_atoms", lambda _source: host_potential)
    cluster = SPRKKRAtoms.from_embedding(
        host_potential, [(0, (0, 0, 0), "Fe")]
    )
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    output = tmp_path / "cluster.clu"
    monkeypatch.setattr(
        file_flows.QFileDialog, "getSaveFileName",
        lambda *args: (str(output), "SPR-KKR cluster potential (*.clu *.pot)"),
    )

    class Writer:
        def save_to_file(self, filename):
            assert filename.name == output.name
            filename.write_text("CLUPOT", encoding="utf-8")

    def make_writer(atoms):
        assert atoms is cluster
        assert atoms.embedding_host is host_potential
        return Writer()

    monkeypatch.setattr(ClusterPotential, "from_atoms", staticmethod(make_writer))

    class Recent:
        def remember(self, kind, path):
            assert kind == "structure"
            assert path == output

    assert file_flows.save_structure(controller, Recent(), None) is True
    assert output.read_text() == "CLUPOT"
    assert (tmp_path / "cluster.host.pot").read_text() == "HOST POT"
    assert not controller.has_unsaved_structure


def test_saved_cluster_automatically_loads_companion_host(monkeypatch, tmp_path):
    from ase2sprkkr_gui.gui.flows import files as file_flows

    cluster_path = tmp_path / "impurity.clu"
    host_path = tmp_path / "impurity.host.pot"
    cluster_path.write_text("CLUPOT")
    host_path.write_text("HOST")
    controller = WorkspaceController(WorkspaceState(atoms=host()))
    chosen = []

    class HostPotential:
        pass

    class ClusterReader:
        @classmethod
        def from_file(cls, path, host=None):
            assert path == cluster_path
            assert isinstance(host, HostPotential)
            return cls()

        @property
        def atoms(self):
            return host()

        def host_geometry_warning(self):
            return None

    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    monkeypatch.setattr(Potential, "from_file",
                        lambda path: chosen.append(path) or HostPotential())
    monkeypatch.setattr(ClusterPotential, "from_file", ClusterReader.from_file)
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda _parent, operation, **_kw: operation())
    class Recent:
        def remember(self, kind, path):
            assert kind == "structure"
            assert path == cluster_path
    assert file_flows.load_embedded_cluster(controller, Recent(), cluster_path, None)
    assert chosen == [str(host_path.resolve())]


def test_hostless_clupot_loads_read_only_without_save_prompt(monkeypatch, tmp_path):
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from ase2sprkkr_gui.gui.flows import files as file_flows
    from ase2sprkkr_gui.gui.workflow.model import (
        AttachHostPotential, CreateHostPotential, LoadHostPotential, WorkflowSection,
    )
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    path = tmp_path / "unpaired.clu"
    path.write_text("native CLUPOT", encoding="utf-8")
    controller = WorkspaceController(WorkspaceState())
    original = object()
    calls = []
    monkeypatch.setattr(
        ClusterPotential, "from_file",
        lambda path, *, host=None: (
            calls.append((path, host)) or original
        ),
    )
    monkeypatch.setattr(
        file_flows, "run_modal_task",
        lambda _parent, action, **_kw: action(),
    )
    monkeypatch.setattr(
        file_flows.QMessageBox, "information", lambda *_args: None,
    )

    class Recent:
        def remember(self, kind, name):
            assert kind == "structure"
            assert name == path

    assert file_flows.load_embedded_cluster(controller, Recent(), path, None)
    assert calls == [(path, None)]
    assert controller.atoms is None
    assert controller.unresolved_cluster is original
    assert controller.unresolved_cluster_path == path
    assert not controller.has_unsaved_structure
    plan = WorkflowPlanner().for_workspace(controller)
    assert tuple(a.command for a in plan.group(WorkflowSection.CREATE).actions) == (
        AttachHostPotential(), LoadHostPotential(), CreateHostPotential(),
    )
    assert "read-only" in plan.subtitle.lower()


def test_attaching_host_to_read_only_clupot_enables_editing(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from ase2sprkkr_gui.gui.flows import files as file_flows

    cluster_path = tmp_path / "orphan.clu"
    cluster_path.write_text("CLUPOT")
    host_path = tmp_path / "host.pot"
    host_path.write_text("HOST")
    controller = WorkspaceController(WorkspaceState())
    host_potential = Potential.from_atoms(host())
    draft = EmbeddingDraft(host_potential)
    draft.include([draft.center])
    embedded = draft.to_atoms()
    seen = []

    def parse(path, *, host=None):
        seen.append((path, host))
        if host is None:
            return SimpleNamespace()
        return SimpleNamespace(
            atoms=embedded, host_geometry_warning=lambda: None,
        )

    monkeypatch.setattr(ClusterPotential, "from_file", parse)
    monkeypatch.setattr(Potential, "from_file", lambda *_args: host_potential)
    monkeypatch.setattr(
        file_flows, "run_modal_task",
        lambda _parent, work, **_kw: work(),
    )
    monkeypatch.setattr(
        file_flows.QMessageBox, "information", lambda *_args: None,
    )
    monkeypatch.setattr(
        file_flows.QFileDialog, "getOpenFileName",
        lambda *_args: (str(host_path), ""),
    )
    class Recent:
        def remember(self, *_args):
            pass

    recent = Recent()
    assert file_flows.load_embedded_cluster(
        controller, recent, cluster_path, None,
    )
    assert controller.unresolved_cluster is not None
    assert file_flows.attach_host_potential(controller, recent, None)
    assert controller.unresolved_cluster is None
    assert controller.unresolved_cluster_path is None
    assert controller.atoms is embedded
    assert controller.atoms.embedding_host is host_potential
    assert not controller.has_unsaved_structure
    assert seen == [(cluster_path, None), (cluster_path, host_potential)]


def test_read_only_clupot_does_not_prompt_to_save_on_quit(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from ase2sprkkr_gui.gui.flows import files as file_flows
    from ase2sprkkr_gui.main import GuiApplication

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recents.json")
    path = tmp_path / "read_only.clu"
    path.write_text("CLUPOT")
    monkeypatch.setattr(
        ClusterPotential, "from_file",
        lambda *_a, **_kw: SimpleNamespace(),
    )
    monkeypatch.setattr(
        file_flows, "run_modal_task",
        lambda _parent, work, **_kw: work(),
    )
    monkeypatch.setattr(file_flows.QMessageBox, "information", lambda *_a: None)
    monkeypatch.setattr(
        file_flows.QMessageBox, "question",
        lambda *_a: pytest.fail("Read-only CLUPOT must not be saved on exit"),
    )
    assert file_flows.load_embedded_cluster(
        gui.controller, gui.recent_files, path, None,
    )
    assert gui.request_exit()


def test_cancelling_host_attachment_preserves_read_only_clupot(
    monkeypatch, tmp_path,
):
    from types import SimpleNamespace
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from ase2sprkkr_gui.gui.flows import files as file_flows

    path = tmp_path / "incomplete.clu"
    path.write_text("CLUPOT")
    controller = WorkspaceController(WorkspaceState())
    monkeypatch.setattr(
        ClusterPotential, "from_file",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda _parent, task, **_kwargs: task())
    monkeypatch.setattr(file_flows.QMessageBox, "information", lambda *_a: None)
    monkeypatch.setattr(
        file_flows.QFileDialog, "getOpenFileName",
        lambda *_args: ("", ""),
    )

    class Recent:
        def remember(self, *_args):
            pass

    recent = Recent()
    assert file_flows.load_embedded_cluster(controller, recent, path, None)
    potential = controller.unresolved_cluster
    assert not file_flows.attach_host_potential(controller, recent, None)
    assert controller.unresolved_cluster is potential
    assert controller.atoms is None
    assert not controller.has_unsaved_structure
    controller.reset()
    assert controller.unresolved_cluster is None
    assert controller.unresolved_cluster_path is None


def test_creating_host_for_unresolved_clupot_uses_explicit_structure(
    monkeypatch, tmp_path,
):
    from types import SimpleNamespace
    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from ase2sprkkr_gui.gui.flows import files as file_flows
    from ase2sprkkr_gui.gui.flows import structure_candidates

    path = tmp_path / "unpaired.clu"
    path.write_text("CLUPOT")
    controller = WorkspaceController(WorkspaceState())
    periodic = host()
    host_pot = Potential.from_atoms(periodic)
    draft = EmbeddingDraft(host_pot)
    draft.include([draft.center])
    cluster_atoms = draft.to_atoms()
    calls = []

    def read_cluster(filename, *, host=None):
        if host is None:
            return SimpleNamespace()
        calls.append(("read", filename, host))
        return SimpleNamespace(
            atoms=cluster_atoms,
            host_geometry_warning=lambda: None,
        )

    monkeypatch.setattr(ClusterPotential, "from_file", read_cluster)
    monkeypatch.setattr(Potential, "from_atoms",
                        lambda _atoms: calls.append(("create", _atoms)) or host_pot)
    monkeypatch.setattr(
        structure_candidates, "create_structure_candidate",
        lambda *_args, **_kwargs: SimpleNamespace(atoms=periodic),
    )
    # The file flow imports this function directly.
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda _parent, task, **_kwargs: task())
    monkeypatch.setattr(file_flows.QMessageBox, "information", lambda *_a: None)
    class Recent:
        def remember(self, *_a):
            pass
    recent = Recent()

    assert file_flows.load_embedded_cluster(controller, recent, path, None)
    assert file_flows.create_host_potential(controller, recent, None)
    assert calls == [
        ("create", periodic),
        ("read", path, host_pot),
    ]
    assert controller.unresolved_cluster is None
    assert controller.atoms is cluster_atoms


def test_cluster_file_detection_distinguishes_host_potfil(tmp_path):
    from ase2sprkkr import Potential

    host_file = tmp_path / "host.pot"
    host_file.write_text("GLOBAL SYSTEM PARAMETER\nNQ 1\n")
    cluster_file = tmp_path / "cluster.pot"
    cluster_file.write_text("GLOBAL SYSTEM PARAMETER\nNQCLU 1\n")
    native_file = tmp_path / "cluster.clu"
    native_file.write_text("GLOBAL SYSTEM PARAMETER\nNQCLU 1\n")
    assert not Potential.is_cluster_file(host_file)
    assert Potential.is_cluster_file(cluster_file)
    assert Potential.is_cluster_file(native_file)


def test_open_native_cluster_with_explicit_host_preserves_reference(
    monkeypatch, tmp_path,
):
    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential

    from ase2sprkkr_gui.gui.flows import files as file_flows

    cluster_path = tmp_path / "sample.clu"
    cluster_path.write_text("mock-cluster")
    host_path = tmp_path / "host.pot"
    host_path.write_text("mock-host")
    reference = host()

    class HostPotential:
        LATTICE = object()
        atoms = reference

    original_host = HostPotential()
    generated = EmbeddingDraft(original_host)
    generated.set_occupation([generated.center], {"Fe": 1.0})
    expected = generated.to_atoms()

    class Parsed:
        @property
        def atoms(self):
            return expected

        def host_geometry_warning(self):
            return None

    calls = []
    monkeypatch.setattr(Potential, "from_file",
                        staticmethod(lambda path: original_host))
    monkeypatch.setattr(
        ClusterPotential, "from_file",
        staticmethod(lambda path, *, host: (
            calls.append((path, host)) or Parsed()
        )),
    )
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda parent, action, **kwargs: action())

    class Recent:
        def __init__(self):
            self.saved = []

        def remember(self, kind, path):
            self.saved.append((kind, path))

    recent = Recent()
    controller = WorkspaceController(WorkspaceState(atoms=host()))
    generation = controller.structure_generation
    assert file_flows.load_embedded_cluster(
        controller, recent, cluster_path, None, host_path=host_path
    )
    assert controller.atoms is expected
    assert controller.atoms.embedding_host is original_host
    assert controller.structure_generation == generation.next()
    assert recent.saved == [("structure", cluster_path)]
    assert calls == [(cluster_path, original_host)]


def test_invalid_cluster_import_does_not_replace_workspace(monkeypatch, tmp_path):
    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential

    from ase2sprkkr_gui.gui.flows import files as file_flows

    initial = host()
    controller = WorkspaceController(WorkspaceState(atoms=initial))
    generation = controller.structure_generation
    monkeypatch.setattr(Potential, "from_file",
                        staticmethod(lambda path: object()))
    monkeypatch.setattr(ClusterPotential, "from_file",
                        staticmethod(lambda path, *, host: (_ for _ in ()).throw(
                            ValueError("Bad cluster")
                        )))
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda parent, action, **kwargs: action())
    errors = []
    monkeypatch.setattr(file_flows.QMessageBox, "critical",
                        lambda *args: errors.append(args))

    assert not file_flows.load_embedded_cluster(
        controller, None, tmp_path / "bad.clu", None, host_path=tmp_path / "host.pot"
    )
    assert errors and "Bad cluster" in str(errors[0])
    assert controller.atoms is initial
    assert controller.structure_generation == generation


def test_embedded_global_preview_shows_distant_sites_without_allowing_picking():
    dialog = BuildEmbeddingDialog(host())
    outside = HostSite(0, (15, -3, 2))
    dialog.draft.include([outside])
    dialog._render()
    assert outside in dialog._rendered_sites
    assert outside not in dialog._local_sites
    selected_before = dialog._selected_site
    click_preview(dialog.global_preview, outside.position(dialog.draft.host))
    assert dialog._selected_site == selected_before

    # The map stays at the origin; increase its rings to reach a distant cell.
    dialog.layer.setValue(2)
    dialog.cell_rings.setValue(18)
    click_cell(dialog, outside.cell_index)
    dialog._render()
    assert outside in dialog._local_sites
    click_preview(dialog.local_preview, outside.position(dialog.draft.host))
    assert dialog._selected_site == outside


def test_2d_editor_can_reopen_special_native_translation_vectors():
    from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

    parent = Atoms("Cu", positions=[[0, 0, 0]], cell=[2, 2, 12],
                   pbc=(True, True, False))
    original = HostSite(0, (1, 0, 0, 0, 1))
    cluster = SPRKKRAtoms.from_embedding(
        parent, [(original.original_site, original.cell_index, "Fe")]
    )
    draft = EmbeddingDraft(parent, cluster)
    assert original in draft.cell_sites((1, 0))
    assert original in draft.entries
    assert draft.to_atoms().sites[0].embedding.translation_vector == (1, 0, 0, 0, 1)


def test_reopening_unmodified_cluster_returns_original_structure():
    parent = host()
    original_draft = EmbeddingDraft(parent)
    original_draft.set_occupation([original_draft.center], {"Fe": 1.0})
    cluster = original_draft.to_atoms()
    cluster.sites[0].magnetisation = np.array([0.1, 0.25])
    editor_draft = EmbeddingDraft(parent, cluster)
    assert editor_draft.is_unchanged()
    restored = editor_draft.to_atoms()
    assert restored is cluster
    assert restored.embedding_host is parent
    np.testing.assert_array_equal(restored.sites[0].magnetisation,
                                  cluster.sites[0].magnetisation)
    editor_draft.set_occupation([editor_draft.center], {"Ni": 1.0})
    assert not editor_draft.is_unchanged()
    assert not editor_draft.would_discard_radial_data()


def test_editor_requires_approval_to_drop_calculated_radial_data(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    parent = host()
    draft = EmbeddingDraft(parent)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    dialog = BuildEmbeddingDialog(cluster)
    dialog.occupation.set_occupation({"Fe": 1.0})
    dialog._assign_occupation()
    monkeypatch.setattr(dialog.draft, "would_discard_radial_data", lambda: True)
    prompts = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *args: (prompts.append(args) or QMessageBox.StandardButton.Cancel),
    )
    dialog._accept()
    assert len(prompts) == 1
    assert dialog.result_atoms is None
    assert dialog.draft.entries[dialog.draft.center].occupation == {"Fe": 1.0}
    assert cluster.sites[0].occupation.to_dict(True) == {"Cu": 1.0}


def test_radial_data_reset_requires_explicit_authorization():
    parent = host()
    base = EmbeddingDraft(parent)
    base.include([base.center])
    cluster = base.to_atoms()
    atomic_type = cluster.sites[0].atomic_type(0)
    atomic_type.charge = np.ones(len(atomic_type.mesh))
    edit = EmbeddingDraft(parent, cluster)
    edit.set_occupation([edit.center], {"Fe": 1.0})
    assert edit.would_discard_radial_data()
    with pytest.raises(ValueError, match="allow_radial_reset"):
        edit.to_atoms()
    changed = edit.to_atoms(allow_radial_reset=True)
    assert changed.sites[0].occupation.to_dict(True) == {"Fe": 1.0}
    assert cluster.sites[0].occupation.to_dict(True) == {"Cu": 1.0}


def test_embedding_snapshot_has_single_uncopied_host_link():
    parent = host()
    draft = EmbeddingDraft(parent)
    draft.include([draft.center])
    snapshot = StructureSnapshot.capture(draft.to_atoms())
    assert snapshot.info["sprkkr_embedding_host"] is parent
    assert not hasattr(snapshot, "embedding_host")
    assert snapshot.to_atoms().embedding_host is parent


def test_cell_rings_are_wigner_seitz_rings_about_the_origin():
    dialog = BuildEmbeddingDialog(host())
    for rings, count in ((0, 1), (1, 5), (2, 13)):
        dialog.cell_rings.setValue(rings)
        assert len(dialog.cells._cells) == count
        assert (0, 0, 0) in dialog.cells._cells


def test_unchanged_embedding_editor_does_not_restart_workspace(monkeypatch):
    from ase2sprkkr import SPRKKRAtoms

    parent = SPRKKRAtoms.promote_ase_atoms(host()).potential
    draft = EmbeddingDraft(parent)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    generation = controller.structure_generation
    monkeypatch.setattr(
        "ase2sprkkr_gui.gui.dialogs.structures.embedding.select_build_embedding_structure",
        lambda source, _parent: source,
    )
    assert structure_flows.build_embedding_structure(controller, None) is None
    assert controller.atoms is cluster
    assert controller.structure_generation == generation


def test_versioned_cluster_history_restores_native_file_using_same_host(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential

    from ase2sprkkr_gui.gui.application.historical_state import _restore_state_atoms

    parent = host()
    draft = EmbeddingDraft(parent)
    draft.set_occupation([draft.center], {"Fe": 1.0})
    atoms = draft.to_atoms()

    path = tmp_path / "calculated.clu"
    path.write_text("GLOBAL SYSTEM PARAMETER\nNQCLU 1\n", encoding="utf-8")
    controller = WorkspaceController(WorkspaceState(
        atoms=atoms, potential_path=str(path)
    ))
    state = controller.result_store.state(controller.state_id)
    assert state.potential_version is not None
    assert state.structure_snapshot is not None
    assert state.structure_snapshot.info["sprkkr_embedding_host"] is parent

    calls = []
    monkeypatch.setattr(
        ClusterPotential,
        "from_file",
        staticmethod(lambda path, *, host: (
            calls.append((path, host)) or SimpleNamespace(atoms=atoms.copy())
        )),
    )

    restored = _restore_state_atoms(state)
    assert restored.embedding_host is parent
    assert restored.sites[0].occupation.to_dict(True) == {"Fe": 1.0}
    assert calls == [(path.resolve(), parent)]


def test_mismatched_host_requires_confirmation_before_workspace_replacement(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential
    from PyQt6.QtWidgets import QMessageBox

    from ase2sprkkr_gui.gui.flows import files as file_flows

    parent = host()
    draft = EmbeddingDraft(parent)
    draft.include([draft.center])
    cluster = draft.to_atoms()

    path = tmp_path / "unmatched.clu"
    path.write_text("NQCLU 1\\n", encoding="utf-8")
    original = host()
    controller = WorkspaceController(WorkspaceState(atoms=original))
    before = controller.structure_generation
    prompts = []

    monkeypatch.setattr(Potential, "from_file",
                        staticmethod(lambda *_args: SimpleNamespace(LATTICE=object())))
    monkeypatch.setattr(
        ClusterPotential, "from_file",
        staticmethod(lambda *args, **kwargs: SimpleNamespace(
            atoms=cluster,
            host_geometry_warning=lambda: "Host mismatch",
        )),
    )
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda _parent, fn, **_kw: fn())
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args: (prompts.append(args) or QMessageBox.StandardButton.Cancel),
    )
    assert not file_flows.load_embedded_cluster(
        controller, None, path, None, host_path=tmp_path / "host.pot"
    )
    assert controller.atoms is original
    assert controller.structure_generation == before
    assert len(prompts) == 1


def test_active_cluster_potential_is_not_mistaken_for_a_periodic_host():
    from ase2sprkkr_gui.gui.flows.files import _current_host_potential

    base = host()
    draft = EmbeddingDraft(base)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    cluster._potential = object()  # Simulate an attached non-periodic potential.
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    assert _current_host_potential(controller) is None


def test_guided_cluster_scf_is_available_without_input_parameters():
    from ase2sprkkr import Potential, SPRKKRAtoms

    from ase2sprkkr_gui.gui.workflow.model import RunTask, WorkflowSection
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    native_host = Potential.from_atoms(host())
    native_host.SCF_INFO.SCFSTATUS = "CONVERGED"
    cluster = SPRKKRAtoms.from_embedding(
        native_host, [(0, (0, 0, 0), "Fe")]
    )
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    assert controller.can_run_embedding()
    assert not controller.can_calculate()  # Guided setup creates parameters.
    plan = WorkflowPlanner().for_workspace(controller)
    calculation = plan.group(WorkflowSection.CALCULATE)
    assert calculation is not None
    assert RunTask("scf") in [action.command for action in calculation.actions]


@pytest.mark.parametrize("dimension", [2, 3])
@pytest.mark.parametrize("host_status", ["START", "CONVERGED"])
def test_building_cluster_from_regular_potential_offers_required_scf(
    monkeypatch, gete_host, dimension, host_status,
):
    from ase2sprkkr import SPRKKRAtoms

    from ase2sprkkr_gui.gui.workflow.model import ConvergeHostScf, RunTask, WorkflowSection
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    potential = (gete_host.potential if dimension == 2
                 else SPRKKRAtoms.promote_ase_atoms(host()).potential)
    potential.SCF_INFO.SCFSTATUS = host_status
    controller = WorkspaceController(WorkspaceState(atoms=potential.atoms))

    def accept_cluster(source, _parent):
        native_host, existing = embedding_source(source)
        assert native_host is potential
        assert existing is None
        draft = EmbeddingDraft(native_host)
        draft.include([draft.center])
        return draft.to_atoms()

    monkeypatch.setattr(
        "ase2sprkkr_gui.gui.dialogs.structures.embedding.select_build_embedding_structure",
        accept_cluster,
    )
    result = structure_flows.build_embedding_structure(controller, None)
    assert result is controller.atoms
    assert result.embedding_host is potential
    assert controller.can_run_embedding()
    assert not controller.is_scf_converged()
    plan = WorkflowPlanner().for_workspace(controller)
    calculation = plan.group(WorkflowSection.CALCULATE)
    assert calculation is not None
    expected = ConvergeHostScf() if host_status == "START" else RunTask("scf")
    assert [action.command for action in calculation.actions] == [expected]
    assert potential.SCF_INFO.SCFSTATUS() == host_status


def test_guided_host_attachment_keeps_embedded_site_mapping(monkeypatch, tmp_path):
    from ase2sprkkr import Potential
    from ase2sprkkr_gui.gui.flows import files as file_flows

    draft = EmbeddingDraft(host())
    draft.include([draft.center])
    cluster = draft.to_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    potential = Potential.from_atoms(host())
    path = tmp_path / "host.pot"
    monkeypatch.setattr(
        file_flows.QFileDialog, "getOpenFileName",
        lambda *_args: (str(path), "SPR-KKR host POTFIL (*.pot *.pot_new)"),
    )
    monkeypatch.setattr(Potential, "from_file", lambda _path: potential)
    monkeypatch.setattr(file_flows, "run_modal_task",
                        lambda _parent, work, **_kw: work())
    assert file_flows.ensure_embedded_host_potential(controller, None)
    assert controller.can_run_embedding()
    assert controller.atoms is not cluster
    assert controller.atoms.embedding_host is potential
    np.testing.assert_array_equal(
        controller.atoms.arrays["sprkkr_embedding"],
        cluster.arrays["sprkkr_embedding"],
    )


def test_embedding_preview_uses_qt_labels_without_matplotlib_layout_warning():
    import warnings

    dialog = BuildEmbeddingDialog(host())
    dialog.draft.include([dialog.draft.center])
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        dialog._render()
        dialog.global_preview.canvas.draw()

    assert "Cluster: 1/1" in dialog.preview_info.text()
    assert "Displayed:" in dialog.preview_info.text()
    assert "Host cell (0, 0, 0)" in dialog.local_info.text()
    axes = dialog.global_preview.axes
    assert axes.get_title() == ""
    assert axes.get_xlabel() == ""
    assert axes.get_ylabel() == ""
    assert not any("Tight layout not applied" in str(w.message) for w in captured)


def test_editor_occupation_matches_bulk_rows_with_normalize_and_picker():
    from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor

    dialog = BuildEmbeddingDialog(host())
    assert isinstance(dialog.occupation, OccupationEditor)
    dialog.occupation.set_occupation({"Fe": 0.7, "Ni": 0.3})
    assert dialog.occupation.normalize_check.isChecked()
    assert not dialog.occupation.normalize_check.isHidden()
    assert dialog.occupation.is_valid()
    assert dialog.occupation.occupation() == {"Fe": 0.7, "Ni": 0.3}
    dialog.occupation.set_occupation({"Fe": 0.6})
    assert dialog.occupation.normalize_check.isHidden()
    assert not dialog.occupation.is_valid()
    dialog.occupation.normalize()
    assert dialog.occupation.occupation() == {"Fe": 1.0}
    dialog.occupation.set_occupation({"Vc": 1.0})
    assert dialog.occupation.occupation() == {"X": 1.0}
    dialog.occupation.set_occupation({"Fe": 1.0})
    dialog.occupation.add_row()
    second = dialog.occupation.rows[-1]
    second["elem"].setText("Ni")
    second["occ"].setValue(0.5)
    assert dialog.occupation.is_valid()
    assert dialog.occupation.rows[0]["occ"].value() == 0.5
    assert dialog.draft.entries[dialog.draft.center].occupation == {
        "Fe": 0.5, "Ni": 0.5
    }


def test_normalize_checkbox_scales_other_components_and_can_be_disabled():
    from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor

    control = OccupationEditor(require_full=True)
    control.set_occupation({"Fe": 0.5, "Ni": 0.3, "Co": 0.2})
    assert control.normalize_check.isChecked()
    assert not control.normalize_check.isHidden()

    control.rows[0]["occ"].setValue(0.6)
    assert control.occupation() == {"Fe": 0.6, "Ni": 0.24, "Co": 0.16}
    assert [row["occ"].value() for row in control.rows] == [0.6, 0.24, 0.16]

    control.normalize_check.setChecked(False)
    control.rows[1]["occ"].setValue(0.1)
    assert not control.is_valid()
    assert [row["occ"].value() for row in control.rows] == [0.6, 0.1, 0.16]

    # Checking Normalize fixes existing values without requiring another edit.
    control.normalize_check.setChecked(True)
    assert control.is_valid()
    assert sum(control.occupation().values()) == pytest.approx(1.0)
    assert all(row["occ"].value() == row["entry"].value for row in control.rows)


def test_normalize_checkbox_handles_zero_others_and_row_removal():
    from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor

    control = OccupationEditor(require_full=True)
    control.set_occupation({"Fe": 1.0})
    assert control.normalize_check.isHidden()
    control.add_row()
    assert not control.normalize_check.isHidden()
    control.rows[1]["elem"].setText("Ni")
    control.rows[0]["occ"].setValue(0.75)
    assert control.occupation() == {"Fe": 0.75, "Ni": 0.25}

    control.remove_row(control.entries[0])
    assert control.normalize_check.isHidden()
    assert control.occupation() == {"Ni": 1.0}

    control.set_occupation({"Fe": 0.0, "Ni": 0.0, "Co": 0.0})
    control.normalize_check.setChecked(False)
    control.normalize_check.setChecked(True)
    assert control.is_valid()
    assert sum(control.occupation().values()) == pytest.approx(1.0)
    assert all(row["occ"].value() == row["entry"].value for row in control.rows)


def test_bulk_normalization_checkbox_updates_the_draft():
    from ase2sprkkr_gui.gui.dialogs.structures.element_assignment import (
        ElementAssignmentDialog,
    )

    parent = host()
    parent.set_array("spacegroup_kinds", np.array([0]))
    parent.info["occupancy"] = {"0": {"Fe": 0.7, "Ni": 0.3}}
    dialog = ElementAssignmentDialog()
    dialog.setup(parent)
    editor = dialog._letter_widgets[0].occupation_editor
    editor.rows[0]["occ"].setValue(0.4)
    assert [entry.value for entry in dialog._draft.sites[0].occupancies] == [
        0.4, 0.6
    ]
    editor.normalize_check.setChecked(False)
    editor.rows[1]["occ"].setValue(0.3)
    assert [entry.value for entry in dialog._draft.sites[0].occupancies] == [
        0.4, 0.3
    ]
    editor.normalize_check.setChecked(True)
    assert sum(entry.value for entry in dialog._draft.sites[0].occupancies) == (
        pytest.approx(1.0)
    )


def test_global_preview_highlights_all_equivalents_not_only_selected_cell():
    dialog = BuildEmbeddingDialog(host())
    selected = HostSite(0, (1, 0, 0))
    dialog._selected_cell = selected.cell_index
    dialog._selected_site = selected
    dialog._selected_sites = {selected}
    dialog._update_symmetry_preview()
    dialog._render()
    assert len(dialog._highlighted) == 6
    assert set(dialog._highlighted) <= set(dialog._rendered_sites)
    assert any(site.cell_index != selected.cell_index
               for site in dialog._rendered_sites)
    assert dialog._local_sites == [selected]
    dialog.global_scope.setCurrentIndex(1)  # Current layer
    dialog._render_global()
    assert all(site.cell_index[2] == dialog.layer.value()
               for site in dialog._rendered_sites)
    dialog.global_scope.setCurrentIndex(0)
    dialog._render_global()
    assert set(dialog._highlighted) <= set(dialog._rendered_sites)


def test_bulk_occupation_uses_the_same_widget_as_embedding():
    from ase2sprkkr_gui.gui.dialogs.structures.element_assignment import (
        ElementAssignmentDialog,
    )
    from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor

    parent = host()
    parent.set_array("spacegroup_kinds", np.array([0]))
    parent.info["occupancy"] = {"0": {"Cu": 1.0}}
    editor = ElementAssignmentDialog()
    editor.setup(parent)
    row = editor._letter_widgets[0]
    assert isinstance(row.occupation_editor, OccupationEditor)
    row.occupation_editor.rows[0]["occ"].setValue(0.6)
    assert editor._draft.sites[0].occupancies[0].value == 0.6
    row.occupation_editor.normalize()
    assert editor._draft.sites[0].occupancies[0].value == 1.0


def test_occupation_editor_rejects_unnamed_positive_fraction():
    dialog = BuildEmbeddingDialog(host())
    dialog.occupation.set_occupation({"Fe": 0.5})
    dialog.occupation.add_row()
    dialog.occupation.rows[-1]["occ"].setValue(0.5)
    assert not dialog.occupation.is_valid()
    with pytest.raises(ValueError, match="element is required"):
        dialog.occupation.occupation()


def test_embedding_occupation_is_committed_automatically_only_when_valid(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    dialog = BuildEmbeddingDialog(host())
    site = dialog.draft.center
    prompts = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: prompts.append(args)
    )
    # Editing the selected site's occupation should not ask for a second Apply.
    dialog.occupation.rows[0]["elem"].setText("Fe")
    assert dialog.draft.entries[site].occupation == {"Fe": 1.0}

    # A temporary incomplete mixture must not corrupt the already valid state.
    dialog.occupation.add_row()
    dialog.occupation.rows[0]["occ"].setValue(0.7)
    assert not dialog.occupation.is_valid()
    assert dialog.draft.entries[site].occupation == {"Fe": 1.0}
    assert dialog.occupation.rows[1]["occ"].value() == 0.3

    row = dialog.occupation.rows[1]
    row["elem"].setText("Ni")
    assert dialog.occupation.is_valid()
    assert dialog.draft.entries[site].occupation == {"Fe": 0.7, "Ni": 0.3}
    row["occ"].setValue(0.4)
    assert dialog.draft.entries[site].occupation == {"Fe": 0.6, "Ni": 0.4}
    assert dialog.occupation.rows[1] is row  # No focus-destroying rebuild
    assert prompts == []


def test_embedding_auto_occupation_overwrites_other_symmetry_sites_only_with_consent(
    monkeypatch,
):
    from PyQt6.QtWidgets import QMessageBox

    dialog = BuildEmbeddingDialog(host())
    selected = HostSite(0, (1, 0, 0))
    dialog._selected_cell = selected.cell_index
    dialog._selected_site = selected
    dialog._selected_sites = {selected}
    dialog._refresh_sites()
    dialog.symmetric.setChecked(True)
    orbit = dialog.draft.targets([selected], symmetric=True)
    assert len(orbit) > 1

    dialog.occupation.rows[0]["elem"].setText("Fe")
    assert all(dialog.draft.entries[s].occupation == {"Fe": 1.0} for s in orbit)

    other = next(s for s in orbit if s != selected)
    dialog.draft.set_occupation([other], {"Ni": 1.0})
    messages = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: (
            messages.append(args) or QMessageBox.StandardButton.Cancel
        ),
    )

    dialog.occupation.rows[0]["elem"].setText("Co")
    assert dialog.draft.entries[other].occupation == {"Ni": 1.0}
    assert dialog.occupation.occupation() == {"Fe": 1.0}  # Restored after Cancel

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: (
            messages.append(args) or QMessageBox.StandardButton.Yes
        ),
    )
    dialog.occupation.rows[0]["elem"].setText("Co")
    assert all(dialog.draft.entries[s].occupation == {"Co": 1.0} for s in orbit)

    dialog.occupation.rows[0]["elem"].setText("Mn")
    assert all(dialog.draft.entries[s].occupation == {"Mn": 1.0} for s in orbit)
    assert len(messages) == 2  # Cancel once, then approve the edit sequence


def test_incomplete_occupation_is_not_discarded_by_selection_or_ok(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    # A two-site host makes it possible to navigate the selected site's rows.
    source = Atoms(
        "Cu2", positions=[[0, 0, 0], [1, 1, 1]],
        cell=[2, 2, 2], pbc=True
    )
    dialog = BuildEmbeddingDialog(source)
    selected = dialog._selected_site
    dialog.occupation.rows[0]["occ"].setValue(0.4)
    assert not dialog.occupation.is_valid()

    # Switching the displayed site would silently discard the partial mixture.
    other_row = 1 if selected == dialog._site_rows[0] else 0
    dialog.sites.selectRow(other_row)
    assert dialog._selected_site == selected
    assert dialog.occupation.rows[0]["occ"].value() == 0.4

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: warnings.append(args)
    )
    dialog._accept()
    assert dialog.result_atoms is None
    assert warnings


def test_clicked_grid_cell_matches_its_coordinates_and_not_a_symmetry_cell():
    dialog = BuildEmbeddingDialog(host())
    click_cell(dialog, (0, -1, 0))
    assert dialog._selected_cell == (0, -1, 0)
    assert dialog._selected_site == HostSite(0, (0, -1, 0))
    assert HostSite(0, (-1, -1, 0)) not in dialog._highlighted


def test_local_preview_contains_selected_cell_including_native_translation_entries():
    from ase2sprkkr import SPRKKRAtoms

    parent = Atoms(
        "Cu", positions=[[0, 0, 0]], cell=[2, 2, 12],
        pbc=(True, True, False)
    )
    special = HostSite(0, (1, 0, 0, 0, 1))
    cluster = SPRKKRAtoms.from_embedding(
        parent, [(special.original_site, special.cell_index, "Fe")]
    )
    dialog = BuildEmbeddingDialog(cluster)
    dialog._selected_cell = (1, 0)
    assert special in dialog.draft.cell_sites((1, 0))  # still editable in table
    dialog._render_local()
    assert HostSite(0, (1, 0)) in dialog._local_sites
    assert set(dialog._local_sites) == {HostSite(0, (1, 0)), special}
    assert all(site.cell_index[:2] == (1, 0) for site in dialog._local_sites)


def test_global_whole_mode_includes_all_cluster_sites_and_has_padded_bounds():
    dialog = BuildEmbeddingDialog(host())
    left = HostSite(0, (-3, 1, 0))
    right = HostSite(0, (4, -2, 1))
    dialog.draft.include([left, right])
    dialog.global_scope.setCurrentIndex(0)
    dialog._render_global()
    assert set(dialog.draft.entries).issubset(set(dialog._rendered_sites))
    assert "Cluster: 2/2" in dialog.preview_info.text()
    axes = dialog.global_preview.axes
    dialog.global_preview.canvas.draw()
    bounds = [axes.get_xlim(), axes.get_ylim()]
    for site in (left, right):
        projected, _ = dialog.global_preview.project([site.position(dialog.draft.host)])
        position = projected[0]
        assert all(lo < coordinate < hi for coordinate, (lo, hi) in zip(position, bounds))


def test_cell_site_and_editing_columns_keep_actions_below_site_table():
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication

    dialog = BuildEmbeddingDialog(host())
    dialog.show()
    QApplication.processEvents()
    columns = (dialog.cells.parentWidget(), dialog.sites.parentWidget(),
               dialog.occupation_group.parentWidget())
    outer_splitter = columns[0].parentWidget()
    details_splitter = columns[1].parentWidget()
    details_panel = details_splitter.parentWidget()
    assert outer_splitter.count() == 2
    assert outer_splitter.widget(0) is columns[0]
    assert outer_splitter.widget(1) is details_panel
    assert details_splitter.count() == 2
    assert tuple(details_splitter.widget(i) for i in range(2)) == columns[1:]
    assert columns[0].mapTo(dialog, QPoint()).x() < columns[1].mapTo(dialog, QPoint()).x()
    assert columns[1].mapTo(dialog, QPoint()).x() < columns[2].mapTo(dialog, QPoint()).x()
    expansion = dialog.add_radius_button.parentWidget()
    assert expansion.parentWidget() is details_panel
    assert expansion.geometry().bottom() <= details_splitter.geometry().top()
    assert expansion.title() == ""
    assert dialog.centre_label.parentWidget() is details_panel
    assert dialog.centre_label.geometry().bottom() <= expansion.geometry().top()
    assert not dialog.centre_label.wordWrap()
    assert dialog.centre_label.text().startswith("<b>Cluster centre:</b> Host site")
    assert dialog.centre_button.parentWidget() is columns[1]
    site_header = columns[1].layout().itemAt(0).layout()
    assert site_header.itemAt(0).widget() is dialog.cell_label
    assert site_header.itemAt(site_header.count() - 1).widget() is dialog.centre_button
    assert dialog.centre_button.text() == "Use selected site as cluster centre"
    assert dialog.add_radius_button.text() == "Include within radius"
    assert dialog.add_shells_button.text() == "Include shells"
    assert dialog.symmetric.parentWidget() is columns[0]
    assert dialog.displacement_group.parentWidget() is columns[2]
    for button in (dialog.include_button, dialog.exclude_button):
        assert button.parentWidget() is columns[1]
        assert button.mapTo(dialog, QPoint()).y() >= dialog.sites.mapTo(
            dialog, QPoint(0, dialog.sites.height())
        ).y()
    assert dialog.centre_button.mapTo(dialog, QPoint()).y() < dialog.sites.mapTo(
        dialog, QPoint()
    ).y()
    assert dialog.centre_button.mapTo(dialog, QPoint()).x() > dialog.cell_label.mapTo(
        dialog, QPoint()
    ).x()


@pytest.mark.parametrize("dimension", [2, 3])
def test_host_cell_controls_are_beside_preview_and_sections_are_bold(dimension):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication

    atoms = host()
    atoms.pbc = (True, True, dimension == 3)
    dialog = BuildEmbeddingDialog(atoms)
    dialog.show()
    QApplication.processEvents()
    controls = [dialog.cell_rings]
    if dimension == 3:
        controls += [dialog.cell_plane, dialog.layer]
        assert dialog.layer_label.text() == "Layer"
        dialog.cell_plane.setCurrentIndex(1)
        assert dialog.layer_label.text() == "Layer"
    for control in controls:
        assert control.mapTo(dialog, QPoint()).x() < dialog.cells.mapTo(dialog, QPoint()).x()
    assert not hasattr(dialog, "map_indices")
    assert dialog.cells.figure.get_figwidth() == dialog.cells.figure.get_figheight()
    assert "QGroupBox::title { font-weight: bold; }" in dialog.styleSheet()
    dialog.close()


def test_embedding_footer_equal_buttons_and_compact_scope_labels():
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox

    dialog = BuildEmbeddingDialog(host())
    dialog.show()
    QApplication.processEvents()
    buttons = (
        dialog.undo_button,
        dialog.redo_button,
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok),
        dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel),
    )
    assert len({button.width() for button in buttons}) == 1
    assert dialog.hint.text().startswith("Select a repeated host cell")
    assert dialog.layout().itemAt(0).widget() is not dialog.hint
    assert [dialog.global_scope.itemText(i) for i in range(2)] == [
        "Whole structure", "Current layer",
    ]
    assert dialog._plot_hint_timer.interval() == 900
    assert dialog.cells.canvas in dialog._plot_hints
    assert dialog.local_preview.canvas in dialog._plot_hints
    assert dialog.global_preview.canvas in dialog._plot_hints
    for canvas, outline_type in (
        (dialog.cells.canvas, "Borders:"),
        (dialog.local_preview.canvas, "Rings:"),
        (dialog.global_preview.canvas, "Rings:"),
    ):
        lines = dialog._plot_hints[canvas].splitlines()
        assert lines[0] == "Fill:"
        assert outline_type in lines
        assert all(" — " in line for line in lines if not line.endswith(":"))
        assert any(line.startswith("Blue — ") for line in lines)
        assert any(line.startswith("Bright orange — ") for line in lines)
        assert any(line.startswith("Dark orange — ") for line in lines)
        assert any(line.startswith("Purple — ") for line in lines)
    assert not hasattr(dialog, "preview_legend")


def test_embedding_symmetry_colors_and_actions_follow_same_checkbox():
    from matplotlib.colors import to_rgba

    from ase2sprkkr_gui.gui.widgets.structures.host_cell_map import (
        SELECTED_COLOR, SYMMETRY_APPLY_COLOR, SYMMETRY_PREVIEW_COLOR,
    )

    dialog = BuildEmbeddingDialog(host())
    click_cell(dialog, (1, 0, 0))
    site = dialog._selected_site
    # The 3D orbit also contains sites in other displayed layers. Choose
    # one in the current cell-map plane for both preview assertions.
    related = next(
        other for other in dialog._highlighted
        if other != site and other.cell_index in dialog.cells._cells
    )
    assert dialog.symmetric.isChecked()
    assert dialog._site_style(site)[2] == SELECTED_COLOR
    assert dialog._site_style(related)[2] == SYMMETRY_APPLY_COLOR
    dialog.symmetric.setChecked(False)
    assert dialog._site_style(related)[2] == SYMMETRY_PREVIEW_COLOR

    def map_edge(cell):
        view = dialog.cells
        index = view._cells.index(cell)
        return view.axes.collections[-1].get_edgecolors()[index]

    np.testing.assert_allclose(map_edge(site.cell_index), to_rgba(SELECTED_COLOR))
    np.testing.assert_allclose(
        map_edge(related.cell_index), to_rgba(SYMMETRY_PREVIEW_COLOR)
    )
    dialog.symmetric.setChecked(True)
    assert dialog._site_style(site)[2] == SELECTED_COLOR
    assert dialog._site_style(related)[2] == SYMMETRY_APPLY_COLOR
    np.testing.assert_allclose(
        map_edge(related.cell_index), to_rgba(SYMMETRY_APPLY_COLOR)
    )

    expected = set(dialog._highlighted)
    dialog.include_button.click()
    assert set(dialog.draft.entries) == expected
    dialog.exclude_button.click()
    assert not dialog.draft.entries
    dialog.symmetric.setChecked(False)
    dialog.include_button.click()
    assert set(dialog.draft.entries) == {site}


def test_displacement_is_debounced_and_flushed_before_changing_selected_site():
    dialog = BuildEmbeddingDialog(
        Atoms("Cu2", positions=[[0, 0, 0], [1, 1, 1]],
              cell=[2, 2, 2], pbc=True)
    )
    original = dialog._selected_site
    assert original == dialog._site_rows[0]
    dialog.deltas[0].setValue(0.12)
    assert dialog._displacement_timer.isActive()
    assert original not in dialog.draft.entries
    dialog.sites.selectRow(1)
    assert not dialog._displacement_timer.isActive()
    assert dialog.draft.entries[original].displacement[0] == pytest.approx(0.12)
    assert dialog._selected_site == dialog._site_rows[1]


def test_restore_occupation_is_shared_and_hidden_when_none():
    from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor
    control = OccupationEditor(require_full=True)
    assert not control.restore_btn.isVisible()
    control.set_occupation({"Fe": 1.0})
    control.set_initial_occupation({"Cu": 1.0})
    assert not control.restore_btn.isHidden()
    control.restore_initial()
    assert control.occupation() == {"Cu": 1.0}


def test_embedding_restore_original_occupation_is_in_shared_widget():
    dialog = BuildEmbeddingDialog(host())
    assert not dialog.occupation.restore_btn.isHidden()
    dialog.occupation.rows[0]["elem"].setText("Fe")
    assert dialog.draft.entries[dialog.draft.center].occupation == {"Fe": 1.0}
    dialog.occupation.restore_btn.click()
    assert dialog.draft.entries[dialog.draft.center].occupation == {"Cu": 1.0}


def test_bulk_restore_original_occupation_restores_model_values():
    from ase2sprkkr_gui.gui.dialogs.structures.element_assignment import (
        ElementAssignmentDialog,
    )

    parent = host()
    parent.info["occupancy"] = {"0": {"Cu": 1.0}}
    parent.set_array("spacegroup_kinds", np.array([0]))
    editor = ElementAssignmentDialog()
    editor.setup(parent)
    row = editor._letter_widgets[0]
    assert not row.occupation_editor.restore_btn.isHidden()
    row.occupation_editor.rows[0]["elem"].setText("Fe")
    assert editor._draft.sites[0].occupancies[0].symbol == "Fe"
    row.occupation_editor.restore_initial()
    assert editor._draft.sites[0].occupancies[0].symbol == "Cu"


def test_pending_displacement_is_not_lost_when_occupation_changes():
    dialog = BuildEmbeddingDialog(host())
    site = dialog.draft.center
    dialog.deltas[2].setValue(0.08)
    assert dialog._displacement_timer.isActive()
    dialog.occupation.rows[0]["elem"].setText("Fe")
    assert not dialog._displacement_timer.isActive()
    entry = dialog.draft.entries[site]
    assert entry.displacement[2] == pytest.approx(0.08)
    assert entry.occupation == {"Fe": 1.0}


def test_exclude_after_pending_displacement_does_not_reinclude_atom():
    dialog = BuildEmbeddingDialog(host())
    site = dialog.draft.center
    dialog.deltas[0].setValue(0.14)
    dialog._exclude()
    assert not dialog._displacement_timer.isActive()
    assert site not in dialog.draft.entries


def test_2d_multilayer_detail_contains_entire_transition_region_of_one_cell():
    atoms = Atoms(
        symbols=["Ge"] * 20 + ["Te"] * 20,
        positions=[[0., 0., float(i)] for i in range(40)],
        cell=[2.5, 2.5, 80.0],
        pbc=(True, True, False),
    )
    dialog = BuildEmbeddingDialog(atoms)
    dialog._render()
    n_cells = 13  # Two Wigner-Seitz rings of the square surface lattice
    assert len(dialog._site_rows) == 40  # Site table: one host unit cell
    assert len(dialog._local_sites) == 40  # Full transition region of one cell
    assert len(dialog._rendered_sites) == 40 * n_cells  # Whole host viewport
    assert "Host: 520" in dialog.preview_info.text()
    assert "Transition region" in dialog.local_info.text()
    assert "Cluster: 0/0" in dialog.preview_info.text()

    # Choosing another basis atom changes the highlighted site without
    # discarding the other 39 basis sites of the 2D transition region.
    dialog.sites.selectRow(30)
    dialog._render_local()
    assert len(dialog._local_sites) == 40
    assert HostSite(30, (0, 0)) in dialog._local_sites

    dialog.global_scope.setCurrentIndex(1)
    dialog._render_global()
    assert len(dialog._rendered_sites) == 40 * n_cells
    assert set(dialog._local_sites) <= set(dialog._rendered_sites)

    dialog.global_scope.setCurrentIndex(0)
    dialog._render_global()
    assert len(dialog._rendered_sites) == 40 * n_cells


def test_detail_follows_grid_selection_and_is_independent_of_viewport_size():
    dialog = BuildEmbeddingDialog(host())
    destination = HostSite(0, (1, -1, 0))
    click_cell(dialog, destination.cell_index)
    dialog._render_local()
    assert dialog._local_sites == [destination]
    assert dialog._selected_cell == destination.cell_index
    assert dialog._selected_site == destination
    dialog.cell_rings.setValue(3)
    dialog._render_local()
    assert dialog._local_sites == [destination]


@pytest.mark.parametrize("dimension,scope", [(2, 0), (2, 1), (3, 0), (3, 1)])
def test_cell_ring_spin_redraws_context_without_manual_render(dimension, scope):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    parent = host()
    if dimension == 2:
        parent.pbc = (True, True, False)
    dialog = BuildEmbeddingDialog(parent)
    dialog.cell_rings.setValue(0)
    dialog.global_scope.setCurrentIndex(scope)
    dialog.show()
    QApplication.processEvents()
    QTest.qWait(300)
    preview = dialog.global_preview
    before = np.asarray(preview.canvas.buffer_rgba()).copy()
    assert len(preview._positions) == 1
    draws = []
    preview.canvas.mpl_connect("draw_event", lambda _: draws.append(len(preview._positions)))
    dialog.cell_rings.setFocus()
    QTest.keyClick(dialog.cell_rings, Qt.Key.Key_Up)
    expected = 15 if dimension == 3 and scope == 0 else 5
    # Viewport controls update the model and artists in the same event turn.
    assert len(dialog._rendered_sites) == expected
    assert len(preview._scatter.get_offsets()) == expected
    for _ in range(30):
        QTest.qWait(20)
        if expected in draws:
            break
    assert expected in draws
    assert not np.array_equal(before, np.asarray(preview.canvas.buffer_rgba()))
    assert dialog.undo_stack.count() == 0


@pytest.mark.parametrize("scope", [0, 1])
def test_gete_ring_change_updates_context_points_and_counter_immediately(gete_host, scope):
    dialog = BuildEmbeddingDialog(gete_host)
    dialog.global_scope.setCurrentIndex(scope)
    dialog.cell_rings.setValue(0)
    basis_count = len(gete_host) if scope == 0 else len(dialog.draft.allowed)
    assert len(dialog.global_preview._positions) == basis_count
    dialog.cell_rings.stepUp()
    assert len(dialog.global_preview._positions) == 7 * basis_count
    assert f"Host: {7 * basis_count}" in dialog.preview_info.text()
    dialog.cell_rings.stepDown()
    assert len(dialog.global_preview._positions) == basis_count


def test_cell_map_stays_at_the_origin_after_selecting_another_cell():
    dialog = BuildEmbeddingDialog(host())
    before = set(dialog.cells._cells)
    click_cell(dialog, (1, 1, 0))
    assert dialog._selected_cell == (1, 1, 0)
    assert set(dialog.cells._cells) == before
    assert (0, 0, 0) in before


def test_cell_map_keeps_zoom_when_site_table_selection_is_cleared():
    dialog = BuildEmbeddingDialog(host())
    view = dialog.cells
    view.canvas.draw()
    polygons = view._polygons.copy()
    view.axes.set_xlim(-0.8, 1.4)
    view.axes.set_ylim(-1.5, 1.0)
    view.canvas.draw()
    expected = view.axes.get_xlim(), view.axes.get_ylim()

    # Empty-space clicks in the site table clear the site highlight, not
    # the cell navigation geometry or the user's pan/zoom.
    assert dialog._selected_site is not None
    dialog.sites.clearSelection()
    assert dialog._selected_site is None
    view.canvas.draw()
    assert (view.axes.get_xlim(), view.axes.get_ylim()) == expected
    np.testing.assert_array_equal(view._polygons, polygons)

    dialog.sites.selectRow(0)
    view.canvas.draw()
    assert (view.axes.get_xlim(), view.axes.get_ylim()) == expected
    dialog.symmetric.setChecked(not dialog.symmetric.isChecked())
    view.canvas.draw()
    assert (view.axes.get_xlim(), view.axes.get_ylim()) == expected

    # Changing the actual cell grid is allowed to fit the new geometry.
    dialog.cell_rings.stepUp()
    view.canvas.draw()
    assert (view.axes.get_xlim(), view.axes.get_ylim()) != expected


def test_cell_map_draws_symmetric_outlines_above_adjacent_cells():
    from matplotlib.colors import to_rgba
    from ase2sprkkr_gui.gui.widgets.structures.host_cell_map import (
        HostCellMap, SELECTED_COLOR, SYMMETRY_PREVIEW_COLOR,
    )

    view = HostCellMap()
    cells = [(-1, 0), (0, 0), (1, 0)]
    view.set_cells(
        cells, cell=np.diag([2.0, 2.0, 2.0]), origin=np.zeros(3),
        axes=(0, 1), projection=np.eye(3)[:, :2],
        axis_labels=("x", "y"), selected=(0, 0), counts={},
        modified=set(), equivalents={(-1, 0), (1, 0)},
    )
    view.canvas.draw()

    # The base collection contains all fills and ordinary borders. Each
    # highlight is drawn after it; the selected outline must be last.
    base = view.axes.collections[0]
    highlights = list(view.axes.patches)
    assert len(highlights) == 3
    assert all(patch.get_zorder() > base.get_zorder() for patch in highlights)
    for cell_index, outline in zip(((-1, 0), (1, 0)), highlights[:-1]):
        np.testing.assert_allclose(
            outline.get_xy()[:4], view._polygons[view._cells.index(cell_index)]
        )
        assert outline.get_edgecolor() == to_rgba(SYMMETRY_PREVIEW_COLOR)
        assert outline.get_linestyle() != "-"
    selected_outline = highlights[-1]
    np.testing.assert_allclose(
        selected_outline.get_xy()[:4], view._polygons[view._cells.index((0, 0))]
    )
    assert selected_outline.get_edgecolor() == to_rgba(SELECTED_COLOR)
    assert selected_outline.get_zorder() > max(
        patch.get_zorder() for patch in highlights[:-1]
    )


def test_whole_global_preview_includes_host_even_before_any_cluster_site():
    dialog = BuildEmbeddingDialog(host())
    assert not dialog.draft.entries
    dialog._render_global()
    expected = 13 * 5
    assert len(dialog._rendered_sites) == expected
    assert "Cluster: 0/0" in dialog.preview_info.text()


def test_2d_transition_region_excludes_leads_but_whole_host_shows_them():
    from ase2sprkkr.sprkkr.atoms_region import AtomsRegion

    atoms = Atoms(
        "Cu3", positions=[[0, 0, 0], [0, 0, 2], [0, 0, 4]],
        cell=[2, 2, 12], pbc=(True, True, False),
    )
    atoms.regions = {
        name: AtomsRegion(name, slice(i, i + 1), atoms.cell, atoms=atoms, add=False)
        for i, name in enumerate(("left", "central", "right"))
    }
    dialog = BuildEmbeddingDialog(atoms)
    assert dialog.draft.allowed == frozenset({1})
    dialog._render()
    cells = 13
    assert dialog._local_sites == [HostSite(1, (0, 0))]
    assert all(site.original_site == 1 for site in dialog._local_sites)
    assert len(dialog._rendered_sites) == 3 * cells

    dialog.global_scope.setCurrentIndex(1)
    dialog._render_global()
    assert len(dialog._rendered_sites) == cells
    assert all(site.original_site == 1 for site in dialog._rendered_sites)


@pytest.mark.parametrize("dimension", [2, 3])
@pytest.mark.parametrize("projection", range(4))
def test_real_preview_click_selects_matching_table_site_and_edits_only_it(
    dimension, projection,
):
    atoms = Atoms(
        "Cu3", positions=[[0, 0, 0], [1.3, .4, 1.2], [.3, 1.5, .7]],
        cell=[[2, 0, 0], [.5, 2, 0], [.2, .1, 4]],
        pbc=(True, True, dimension == 3),
    )
    dialog = BuildEmbeddingDialog(atoms)
    dialog._render()
    preview = dialog.local_preview
    preview.projection.setCurrentIndex(projection)
    target = HostSite(2, (0,) * dimension)
    click_preview(preview, target.position(atoms))
    assert dialog._selected_site == target
    assert dialog._site_rows[dialog.sites.currentRow()] == target
    dialog.occupation.rows[0]["elem"].setText("Ni")
    assert set(dialog.draft.entries) == {target}
    assert dialog.draft.entries[target].occupation == {"Ni": 1.0}
    assert atoms.get_chemical_symbols() == ["Cu"] * 3


def test_preview_rotation_drag_does_not_select_another_site():
    atoms = Atoms("Cu2", positions=[[0, 0, 0], [1, 1, 1]], cell=[2] * 3, pbc=True)
    dialog = BuildEmbeddingDialog(atoms)
    dialog._render()
    selected = dialog._selected_site
    click_preview(dialog.local_preview, atoms.positions[1], drag=(20, 0))
    assert dialog._selected_site == selected


def test_overlapping_projection_selects_frontmost_site():
    atoms = Atoms("Cu2", positions=[[0, 0, 0], [0, 0, 2]], cell=[3] * 3, pbc=True)
    dialog = BuildEmbeddingDialog(atoms)
    dialog._render()
    dialog.local_preview.projection.setCurrentIndex(1)  # XY: same screen position
    click_preview(dialog.local_preview, atoms.positions[1])
    assert dialog._selected_site == HostSite(1, (0, 0, 0))


def test_reopened_cluster_starts_at_its_own_cell_and_native_site():
    from ase2sprkkr import SPRKKRAtoms

    parent = host()
    target = HostSite(0, (15, -3, 102))
    cluster = SPRKKRAtoms.from_embedding(parent, [(0, target.cell_index, "Ni")])
    dialog = BuildEmbeddingDialog(cluster)
    dialog._render()
    assert dialog._selected_site == target
    assert dialog._selected_cell == target.cell_index
    assert dialog.layer.value() == 102
    assert dialog._local_sites == [target]
    assert (0, 0, 102) in dialog.cells._cells


def test_layer_change_updates_detail_table_and_context_together():
    dialog = BuildEmbeddingDialog(host())
    dialog.layer.setValue(2)
    dialog.global_scope.setCurrentIndex(1)
    dialog._render()
    target = HostSite(0, (0, 0, 2))
    assert dialog._site_rows == dialog._local_sites == [target]
    assert dialog._selected_site == target
    assert all(site.cell_index[2] == 2 for site in dialog._rendered_sites)


def test_2d_detail_fit_excludes_lead_positions_and_vacuum():
    from ase2sprkkr.sprkkr.atoms_region import AtomsRegion

    atoms = Atoms(
        "Cu4", positions=[[0, 0, -100], [0, 0, 1], [0, 0, 3], [0, 0, 100]],
        cell=[2, 2, 300], pbc=(True, True, False),
    )
    atoms.regions = {
        "central": AtomsRegion("central", slice(1, 3), atoms.cell, atoms=atoms, add=False)
    }
    dialog = BuildEmbeddingDialog(atoms)
    dialog._render()
    assert dialog._local_sites == [HostSite(1, (0, 0)), HostSite(2, (0, 0))]
    corners = dialog._selected_cell_corners()
    assert set(corners[:, 2]) == {1, 3}
    assert np.ptp(dialog.local_preview._positions[:, 2]) == 2
    assert np.ptp(dialog.global_preview._positions[:, 2]) == 200


def test_preview_keeps_zoom_and_orientation_when_editing_occupation():
    dialog = BuildEmbeddingDialog(host())
    dialog._render()
    preview = dialog.local_preview
    preview.canvas.draw()
    preview.set_view(35, 20)
    x, y = preview.axes.transData.transform((0, 0))
    before = preview.axes.get_xlim()
    event = MouseEvent("scroll_event", preview.canvas, x, y, button="up", step=2)
    preview.canvas.callbacks.process("scroll_event", event)
    zoomed = preview.axes.get_xlim()
    assert np.ptp(zoomed) < np.ptp(before)
    dialog.occupation.rows[0]["elem"].setText("Ni")
    dialog._render_local()
    assert preview.axes.get_xlim() == zoomed
    assert preview.view_angles == (35, 20)


@pytest.fixture
def gete_host():
    from pathlib import Path

    import ase2sprkkr
    from ase2sprkkr import Potential

    path = Path(ase2sprkkr.__file__).parent / "potentials/examples/GeTe.pot"
    return Potential.from_file(path).atoms


@pytest.mark.parametrize("cell_index", [(0, 0), (1, 1), (2, 0)])
def test_gete_transition_cell_outline_encloses_its_native_sites(gete_host, cell_index):
    from ase2sprkkr_gui.ase.embedding import embedding_cell

    dialog = BuildEmbeddingDialog(gete_host)
    click_cell(dialog, cell_index)
    dialog._render()
    assert dialog.local_info.text() == f"Transition region {cell_index} · 40 sites"
    assert dialog.cell_label.text() == f"Cell {cell_index}"
    origin, cell = embedding_cell(gete_host)
    np.testing.assert_allclose(origin, gete_host.regions["left"].cell[2])
    np.testing.assert_allclose(cell, gete_host.regions["central"].cell)
    corner = dialog._selected_cell_corners()[0]
    np.testing.assert_allclose(corner, origin + np.asarray(cell_index) @ gete_host.cell[:2])
    # Native basis sites remain in their actual host cell; no modulo/wrapping
    # of atom positions may disguise an incorrectly drawn cell boundary.
    positions = np.array([site.position(gete_host) for site in dialog._local_sites])
    fractions = np.linalg.solve(cell.T, (positions - corner).T).T
    assert fractions.min() >= -1e-8
    assert fractions.max() <= 1 + 1e-8
    assert len(positions) == 40


def test_gete_symmetry_preview_has_real_host_surroundings_outside_navigation_box(gete_host):
    dialog = BuildEmbeddingDialog(gete_host)
    click_cell(dialog, (2, 0))
    dialog.sites.selectRow(dialog._site_rows.index(HostSite(24, (2, 0))))
    dialog._render()
    assert len(dialog._highlighted) == 6
    assert not dialog.draft.entries  # Previewing an orbit does not include it
    assert any(site.cell_index not in dialog.cells._cells for site in dialog._highlighted)
    centre = dialog.draft.center.position(gete_host)
    radii = [np.linalg.norm(site.position(gete_host) - centre) for site in dialog._highlighted]
    np.testing.assert_allclose(radii, radii[0])
    for site in dialog._highlighted:
        # Every previewed site is part of a complete host cell, rather than
        # an extra floating marker outside the materialized host structure.
        assert all(HostSite(i, site.cell_index) in dialog._rendered_host_sites
                   for i in range(len(gete_host)))
        rendered = dialog.global_preview._positions[dialog._rendered_sites.index(site)]
        np.testing.assert_allclose(rendered, site.position(gete_host))


def test_oblique_cell_map_preserves_angles_lengths_and_click_coordinates():
    dialog = BuildEmbeddingDialog(Atoms(
        "Cu", positions=[[0, 0, 0]], cell=[[4, 0, 0], [1, 2, 0], [0, 0, 4]],
        pbc=(True, True, False),
    ))
    view = dialog.cells
    view.canvas.draw()
    polygon = view._polygons[view._cells.index((0, 0))]
    # Longest projected vector is one; a2 keeps its actual slope and scale.
    np.testing.assert_allclose(polygon, [[0, 0], [1, 0], [1.25, .5], [.25, .5]])
    pixels = view.axes.transData.transform(polygon)
    first, second = pixels[1] - pixels[0], pixels[3] - pixels[0]
    assert np.linalg.norm(second) / np.linalg.norm(first) == pytest.approx(np.sqrt(5) / 4)
    assert np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second)) == pytest.approx(1 / np.sqrt(5))
    # Click a known physical location inside cell (1, 1), independently of
    # the widget's polygon-to-cell bookkeeping.
    x, y = view.axes.transData.transform((1.875, .75))
    for name in ("button_press_event", "button_release_event"):
        view.canvas.callbacks.process(name, MouseEvent(name, view.canvas, x, y, button=1))
    assert dialog._selected_cell == (1, 1)
    assert dialog._selected_site == HostSite(0, (1, 1))


@pytest.mark.parametrize("plane,axes,fixed", [(0, (0, 1), 2), (1, (0, 2), 1), (2, (1, 2), 0)])
def test_3d_cell_map_planes_keep_selection_and_navigate_correct_indices(plane, axes, fixed):
    dialog = BuildEmbeddingDialog(host())
    dialog.cell_rings.setValue(4)
    dialog.layer.setValue(2)
    click_cell(dialog, (1, -1, 2))
    selected = dialog._selected_site
    dialog.cell_plane.setCurrentIndex(plane)
    assert dialog.cell_plane.currentText() == ("XY", "XZ", "YZ")[plane]
    assert dialog._selected_site == selected
    assert dialog._selected_cell == selected.cell_index
    assert dialog.layer.value() == selected.cell_index[fixed]
    destination = list(selected.cell_index)
    destination[axes[0]] += 1
    destination[axes[1]] -= 1
    click_cell(dialog, tuple(destination))
    dialog.global_scope.setCurrentIndex(1)
    dialog._render()
    assert dialog._selected_cell == tuple(destination)
    assert dialog._local_sites == [HostSite(0, tuple(destination))]
    assert all(site.cell_index[fixed] == destination[fixed] for site in dialog._rendered_sites)


def test_cell_map_navigation_does_not_discard_unfinished_occupation():
    dialog = BuildEmbeddingDialog(host())
    dialog.occupation.rows[0]["occ"].setValue(.5)
    click_cell(dialog, (1, 1, 0))
    assert dialog._selected_cell == (0, 0, 0)
    assert dialog.occupation.rows[0]["occ"].value() == .5


def test_symmetry_preview_rings_do_not_override_cluster_membership():
    dialog = BuildEmbeddingDialog(host())
    click_cell(dialog, (1, 0, 0))
    site = dialog._selected_site
    color, _, edge, _ = dialog._site_style(site)
    assert color == "#a6aeb6"  # A selected host atom is still outside the cluster
    from ase2sprkkr_gui.gui.widgets.structures.host_cell_map import SELECTED_COLOR
    assert edge == SELECTED_COLOR
    dialog._include()
    assert dialog._site_style(site)[0] == "#4b92cf"
    dialog.occupation.rows[0]["elem"].setText("Ni")
    assert dialog._site_style(site)[0] == "#d88c49"


@pytest.mark.parametrize("size", [(300, 750), (850, 280), (600, 600)])
def test_projected_fit_uses_full_canvas_without_cropping_on_resize(gete_host, size):
    from PyQt6.QtWidgets import QApplication

    from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview

    dialog = BuildEmbeddingDialog(gete_host)
    positions = gete_host.positions[sorted(dialog.draft.allowed)]
    corners = dialog._selected_cell_corners()
    preview = EmbeddingPreview()
    preview.set_points(positions, ["gray"] * len(positions), [23] * len(positions), cell_corners=corners)
    preview.resize(*size)
    preview.show()
    QApplication.processEvents()
    for angles in ((25, -60), (75, 10), (90, -90), (-45, 30)):
        preview.set_view(*angles)
        preview._fit()
        preview.canvas.draw()
        projected, _ = preview.project(np.concatenate((positions, corners)))
        pixels = preview.axes.transData.transform(projected)
        width, height = preview.figure.bbox.width, preview.figure.bbox.height
        assert pixels[:, 0].min() >= 20
        assert pixels[:, 0].max() <= width - 20
        assert pixels[:, 1].min() >= 20
        assert pixels[:, 1].max() <= height - 20
        assert max(np.ptp(pixels[:, 0]) / width, np.ptp(pixels[:, 1]) / height) > .7
        np.testing.assert_allclose(preview.axes.get_position().bounds, (0, 0, 1, 1))


def test_gete_overview_fills_gaps_between_symmetry_surroundings(gete_host):
    dialog = BuildEmbeddingDialog(gete_host)
    click_cell(dialog, (-1, 0))
    dialog.sites.selectRow(17)  # Screenshot's #22 site
    dialog._render()
    cells = {site.cell_index for site in dialog._rendered_host_sites}
    for y in {cell[1] for cell in cells}:
        xvalues = sorted(x for x, row in cells if row == y)
        assert xvalues == list(range(min(xvalues), max(xvalues) + 1))


def select_table_rows(dialog, rows):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    dialog.show()
    QApplication.processEvents()
    for i, row in enumerate(rows):
        item = dialog.sites.item(row, 0)
        dialog.sites.scrollToItem(item)
        QTest.mouseClick(dialog.sites.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier if i else Qt.KeyboardModifier.NoModifier,
                         dialog.sites.visualItemRect(item).center())


def three_site_host():
    return Atoms("CuNiFe", positions=[[0, 0, 0], [1, 1, 1], [.5, 1.5, .3]],
                 cell=[3, 3, 3], pbc=True)


def test_occupation_and_displacement_have_frames_separate_from_site_table():
    dialog = BuildEmbeddingDialog(three_site_host())
    assert dialog.occupation.parentWidget() is dialog.occupation_group
    assert all(spin.parentWidget() is dialog.displacement_group for spin in dialog.deltas)
    assert dialog.sites.parentWidget() not in (dialog.occupation_group, dialog.displacement_group)


def test_multiselection_occupation_restore_and_include_exclude_keep_all_rows():
    dialog = BuildEmbeddingDialog(three_site_host())
    select_table_rows(dialog, (0, 1))
    selected = {HostSite(0, (0, 0, 0)), HostSite(1, (0, 0, 0))}
    assert dialog._selected_sites == selected
    assert "Different occupations" in dialog.occupation_info.text()
    assert not dialog.centre_button.isEnabled()
    assert not dialog.draft.entries
    dialog.occupation.rows[0]["elem"].setText("Co")
    assert set(dialog.draft.entries) == selected
    assert all(entry.occupation == {"Co": 1.} for entry in dialog.draft.entries.values())
    assert len(dialog.sites.selectionModel().selectedRows()) == 2
    dialog.occupation.restore_btn.click()
    assert dialog.draft.entries[HostSite(0, (0, 0, 0))].occupation == {"Cu": 1.}
    assert dialog.draft.entries[HostSite(1, (0, 0, 0))].occupation == {"Ni": 1.}
    dialog._exclude()
    assert not dialog.draft.entries
    assert dialog._selected_sites == selected
    dialog._include()
    assert set(dialog.draft.entries) == selected


def test_multiselection_pending_displacement_applies_before_selecting_other_row():
    dialog = BuildEmbeddingDialog(three_site_host())
    select_table_rows(dialog, (0, 1))
    dialog.deltas[0].setValue(.12)
    select_table_rows(dialog, (2,))
    assert dialog._selected_sites == {HostSite(2, (0, 0, 0))}
    assert len(dialog.draft.entries) == 2
    for index in (0, 1):
        np.testing.assert_allclose(dialog.draft.entries[HostSite(index, (0, 0, 0))].displacement,
                                   [.12, 0, 0])
    assert HostSite(2, (0, 0, 0)) not in dialog.draft.entries


def test_shift_selection_keeps_range_and_uses_clicked_site_as_active():
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    dialog = BuildEmbeddingDialog(three_site_host())
    select_table_rows(dialog, (0,))
    item = dialog.sites.item(2, 0)
    QTest.mouseClick(dialog.sites.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ShiftModifier, dialog.sites.visualItemRect(item).center())
    assert dialog._selected_sites == set(dialog._site_rows)
    assert dialog._selected_site == dialog._site_rows[2]


def test_restore_respects_independent_edits_of_other_symmetry_sites(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    dialog = BuildEmbeddingDialog(host())
    click_cell(dialog, (1, 0, 0))
    selected = dialog._selected_site
    dialog.symmetric.setChecked(True)
    other = next(site for site in dialog._highlighted if site != selected)
    dialog.draft.set_occupation([selected], {"Fe": 1.})
    dialog.draft.set_occupation([other], {"Co": 1.})
    dialog._changed()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog.occupation.restore_btn.click()
    assert dialog.draft.entries[selected].occupation == {"Fe": 1.}
    assert dialog.draft.entries[other].occupation == {"Co": 1.}
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.occupation.restore_btn.click()
    assert all(entry.occupation == {"Cu": 1.} for entry in dialog.draft.entries.values())


def test_lattice_map_axis_labels_remain_inside_resized_canvas():
    dialog = BuildEmbeddingDialog(host())
    view = dialog.cells
    view.resize(350, 500)
    view.canvas.resize(350, 500)
    view.canvas.draw()
    renderer = view.canvas.get_renderer()
    for label in (view.axes.xaxis.label, view.axes.yaxis.label):
        bounds = label.get_window_extent(renderer)
        assert bounds.x0 >= 0
        assert bounds.y0 >= 0
        assert bounds.x1 <= view.figure.bbox.width
        assert bounds.y1 <= view.figure.bbox.height


def test_multisite_symmetry_displacement_rejects_conflicting_orbits_atomically():
    draft = EmbeddingDraft(host())
    with pytest.raises(ValueError, match="conflicts"):
        draft.set_displacement([HostSite(0, (1, 0, 0)), HostSite(0, (0, 1, 0))],
                               [.1, 0, 0], symmetric=True)
    assert not draft.entries


@pytest.mark.parametrize("rings,count", [(0, 1), (1, 7), (2, 19), (3, 37)])
def test_gete_cell_rings_have_six_neighbours_and_remain_centred(gete_host, rings, count):
    offsets = set(cell_ring_offsets(gete_host.cell[:2], rings))
    assert len(offsets) == count
    assert (0, 0) in offsets
    assert all((-x, -y) in offsets for x, y in offsets)


@pytest.mark.parametrize("basis", [
    [[1., 0.], [0., 1.]],  # A vertex contact must not add diagonal neighbours.
    [[1., 0.], [0., 3.]],  # Longer-axis neighbours are still Voronoi neighbours.
    [[1., 0.], [.5, np.sqrt(3) / 2]],
    [[1., 0.], [-.5, np.sqrt(3) / 2]],
    [[1., 0.], [.3, 1.7]],  # Six neighbours at unequal physical distances.
    [[1., 0.], [7., 1.]],  # Rectangular lattice in a skewed primitive basis.
    [[1., 0.], [8.35, .7]],  # Neighbours can have large original indices.
])
def test_cell_rings_match_independent_voronoi_adjacency(basis):
    from scipy.spatial import Voronoi

    basis = np.asarray(basis)
    indices = np.array([(x, y) for x in range(-16, 17) for y in range(-16, 17)])
    diagram = Voronoi(indices @ basis)
    origin = np.flatnonzero(np.all(indices == 0, axis=1))[0]
    neighbours = set()
    for points, vertices in zip(diagram.ridge_points, diagram.ridge_vertices):
        if origin not in points:
            continue
        assert -1 not in vertices  # The sampled lattice encloses the origin.
        edge = diagram.vertices[vertices]
        if np.linalg.norm(edge[0] - edge[1]) > 1e-9:
            other = points[1] if points[0] == origin else points[0]
            neighbours.add(tuple(indices[other]))

    vectors = np.column_stack((basis, np.zeros(2)))
    assert set(cell_ring_offsets(vectors, 1)) == neighbours | {(0, 0)}
    # Ring two is graph distance two, not the second distinct distance shell.
    expected = neighbours | {(0, 0)}
    expected |= {(x + dx, y + dy) for x, y in list(expected) for dx, dy in neighbours}
    assert set(cell_ring_offsets(vectors, 2)) == expected


@pytest.mark.parametrize("scale", [1e-9, 1., 1e9])
def test_cell_rings_use_the_physical_metric_independent_of_rotation_and_scale(scale):
    vectors = np.array([[1., 0., 0.], [.3, 1.7, 0.]])
    # Tilt the lattice away from Cartesian XY, preserving its physical metric.
    tilted = vectors @ np.array([[1., 0., 0.], [0., .6, .8], [0., -.8, .6]]) * scale
    original = tilted.copy()
    assert cell_ring_offsets(tilted, 3) == cell_ring_offsets(vectors, 3)
    np.testing.assert_array_equal(tilted, original)


@pytest.mark.parametrize("vectors", [
    np.zeros((2, 3)), [[1., 0., 0.], [2., 0., 0.]],
    [[1., 0., 0.], [0., np.nan, 0.]], [[1., 0., 0.], [0., np.inf, 0.]],
])
def test_cell_rings_reject_degenerate_or_nonfinite_lattices(vectors):
    with pytest.raises(ValueError, match="Cell-map vectors"):
        cell_ring_offsets(vectors, 1)


def focus_embedding_control(dialog, control):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    dialog.show()
    dialog.activateWindow()
    control.setFocus()
    QApplication.processEvents()
    for _ in range(30):
        QTest.qWait(20)  # Wait for focus activation and the debounced preview.
        if not dialog._expansion_timer.isActive():
            break
    assert not dialog._expansion_timer.isActive()
    dialog._render()


def test_preview_controls_are_on_the_outer_sides_of_the_canvases():
    from PyQt6.QtCore import QPoint

    dialog = BuildEmbeddingDialog(host())
    focus_embedding_control(dialog, dialog.cell_rings)
    for preview, right in ((dialog.local_preview, False), (dialog.global_preview, True)):
        controls = [preview.projection, preview.fit_button]
        if right:
            controls.insert(0, dialog.global_scope)
        assert len({control.width() for control in controls}) == 1
        canvas_left = preview.canvas.mapTo(preview, QPoint()).x()
        canvas_right = canvas_left + preview.canvas.width()
        for control in (preview.projection, preview.fit_button):
            x = control.mapTo(preview, QPoint()).x()
            if right:
                assert x >= canvas_right
            else:
                assert x + control.width() <= canvas_left
        preview.projection.setCurrentIndex(1)
        assert preview.view_angles == (90., -90.)
        preview._zoom_factor = 2.
        preview.fit_button.click()
        assert preview._zoom_factor == 1.


@pytest.mark.parametrize("mode", ["radius", "shells"])
def test_focused_expansion_previews_the_exact_addition_without_mutating_entries(mode):
    dialog = BuildEmbeddingDialog(host())
    centre = dialog.draft.center
    dialog.draft.set_occupation([centre], {"Fe": 1.})
    dialog.draft.set_displacement([centre], [.1, 0., 0.])
    dialog.cell_rings.setValue(0)  # The preview must reach beyond the viewport.
    dialog.radius.setValue(2.01)
    control = dialog.radius if mode == "radius" else dialog.shells
    focus_embedding_control(dialog, control)
    assert dialog._expansion_mode == mode
    expected = (dialog.draft.sites_within_radius(2.01) if mode == "radius"
                else dialog.draft.sites_within_shells(1))
    assert dialog._expansion_sites == set(expected)
    assert len(expected) == 7
    assert set(expected) <= set(dialog._rendered_sites)
    assert "6 new sites" in dialog.expansion_info.text()
    assert len(dialog.draft.entries) == 1
    assert dialog.draft.entries[centre].occupation == {"Fe": 1.}
    np.testing.assert_array_equal(dialog.draft.entries[centre].displacement, [.1, 0., 0.])
    for site in set(expected) - {centre}:
        assert dialog._site_style(site)[0] == "#69b88e"
        assert dialog._site_style(site)[2:] == ("#329466", 1.6)

    button = dialog.add_radius_button if mode == "radius" else dialog.add_shells_button
    focus_embedding_control(dialog, button)
    assert dialog._expansion_sites == set(expected)
    button.click()
    dialog._update_expansion_preview()
    assert set(dialog.draft.entries) == set(expected)
    assert "0 new sites" in dialog.expansion_info.text()
    assert dialog.draft.entries[centre].occupation == {"Fe": 1.}
    np.testing.assert_array_equal(dialog.draft.entries[centre].displacement, [.1, 0., 0.])
    assert all(dialog._site_style(site)[0] == "#4b92cf" for site in set(expected) - {centre})


def test_expansion_preview_tracks_mode_value_and_centre_and_clears_on_focus_out():
    dialog = BuildEmbeddingDialog(host())
    dialog.radius.setValue(0.)
    focus_embedding_control(dialog, dialog.radius)
    assert dialog._expansion_sites == {dialog.draft.center}
    focus_embedding_control(dialog, dialog.shells)
    assert len(dialog._expansion_sites) == 7
    dialog.shells.setValue(0)
    focus_embedding_control(dialog, dialog.shells)
    assert dialog._expansion_sites == {dialog.draft.center}
    new_centre = HostSite(0, (3, 0, 0))
    dialog.draft.set_center(new_centre)
    dialog._changed()
    focus_embedding_control(dialog, dialog.shells)
    assert dialog._expansion_sites == {new_centre}
    assert new_centre in dialog._rendered_sites
    assert not dialog.draft.entries
    dialog.shells.setValue(1)  # Queue a preview then leave before it executes.
    focus_embedding_control(dialog, dialog.cell_rings)
    assert dialog._expansion_mode is None
    assert not dialog._expansion_sites
    assert not dialog._expansion_timer.isActive()
    assert dialog.expansion_info.isHidden()


def test_invalid_expansion_preview_is_inline_and_does_not_leave_old_candidates(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    dialog = BuildEmbeddingDialog(host())
    dialog.radius.setValue(2.01)
    focus_embedding_control(dialog, dialog.radius)
    assert len(dialog._expansion_sites) == 7
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog.radius.setValue(1000.)
    focus_embedding_control(dialog, dialog.radius)
    assert not dialog._expansion_sites
    assert "Cannot preview expansion" in dialog.expansion_info.text()
    assert not warnings
    assert not dialog.draft.entries


def test_expansion_preview_uses_only_the_gete_transition_region(gete_host):
    dialog = BuildEmbeddingDialog(gete_host)
    focus_embedding_control(dialog, dialog.radius)
    assert dialog._expansion_sites == set(dialog.draft.sites_within_radius(5.))
    assert all(site.original_site in dialog.draft.allowed for site in dialog._expansion_sites)
    assert dialog._expansion_sites <= set(dialog._rendered_sites)
    assert not dialog.draft.entries


@pytest.mark.parametrize("edit", ["center", "displacement"])
def test_calculated_cluster_edit_keeps_radial_starting_density_and_embedded_tab(tmp_path, edit):
    """An edited cluster can restart from its old radial data without convergence."""
    from pathlib import Path
    import ase2sprkkr
    from ase2sprkkr import Potential
    from ase2sprkkr_gui.gui.dialogs.structures.structure_editor import (
        StructureEditorDialog,
    )

    examples = Path(ase2sprkkr.__file__).resolve().parent / "potentials" / "examples"
    cluster_file = examples / "Fe3CoFe3.clu.iterating.pot"
    host_file = examples / "Fe3CoFe3.host.pot"
    if not cluster_file.is_file() or not host_file.is_file():
        pytest.skip("Native calculated cluster fixtures are not installed")

    parent = Potential.from_file(host_file)
    original = Potential.from_file(cluster_file, host=parent).atoms
    draft = EmbeddingDraft(parent, original)
    if edit == "center":
        draft.set_center(next(key for key in draft.entries if key != draft.center))
    else:
        key = next(iter(draft.entries))
        old_displacement = draft.entries[key].displacement.copy()
        draft.set_displacement([key], old_displacement + [0.02, 0.0, 0.0])

    assert not draft.would_discard_radial_data()
    edited = draft.to_atoms()
    assert edited is not original
    assert edited.embedding_host is parent
    assert "sprkkr_embedding" in edited.arrays
    assert edited.info["sprkkr_embedding_scf_status"] == "ITERATING"
    for before, after in zip(original.sites, edited.sites):
        for atom_type in before.occupation:
            copied = next(a for a in after.occupation if a.symbol == atom_type.symbol)
            assert copied is not atom_type
            assert not np.shares_memory(
                copied.potential.raw_value, atom_type.potential.raw_value
            )
            np.testing.assert_array_equal(copied.potential.raw_value,
                                          atom_type.potential.raw_value)
            np.testing.assert_array_equal(copied.charge.raw_value,
                                          atom_type.charge.raw_value)

    output = tmp_path / "edited.clupot"
    Potential.from_atoms(edited).save_to_file(output)
    reopened = Potential.from_file(output, host=parent).atoms
    assert "sprkkr_embedding" in reopened.arrays
    assert reopened.info["sprkkr_embedding_scf_status"] == "ITERATING"
    dialog = StructureEditorDialog(reopened)
    try:
        assert dialog._embedded_index() >= 0
        assert dialog.tabs.tabText(dialog._embedded_index()) == "Embedded"
    finally:
        dialog.close()


def test_unavailable_new_element_requires_radial_reset():
    """An unrelated element's potential is never relabeled as a starting guess."""
    from pathlib import Path
    import ase2sprkkr
    from ase2sprkkr import Potential

    examples = Path(ase2sprkkr.__file__).resolve().parent / "potentials" / "examples"
    cluster_file = examples / "Fe3CoFe3.clu.iterating.pot"
    host_file = examples / "Fe3CoFe3.host.pot"
    if not cluster_file.is_file() or not host_file.is_file():
        pytest.skip("Native calculated cluster fixtures are not installed")
    parent = Potential.from_file(host_file)
    source = Potential.from_file(cluster_file, host=parent).atoms
    draft = EmbeddingDraft(parent, source)
    key = next(iter(draft.entries))
    draft.set_occupation([key], {"Au": 1.0})
    assert draft.would_discard_radial_data()
    with pytest.raises(ValueError, match="allow_radial_reset"):
        draft.to_atoms()
    edited = draft.to_atoms(allow_radial_reset=True)
    assert edited.info["sprkkr_embedding_scf_status"] == "START"
    assert "sprkkr_embedding" in edited.arrays
