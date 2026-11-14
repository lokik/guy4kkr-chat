from __future__ import annotations

from ase import Atoms

from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.flows import visualization


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)

    settings.load()
    assert settings.viewer == "ase"

    settings.viewer = "vmd"
    settings.share_python_shell_history = False
    assert settings.save()

    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.viewer == "vmd"
    assert loaded.share_python_shell_history is False


def test_corrupt_settings_keep_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    settings = ApplicationSettings(path)
    settings.load()

    assert settings.viewer == "ase"
    assert settings.share_python_shell_history is True


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


class _FakeProfileStore:
    """Isolate settings UI behavior from user configuration files."""

    reserved_names = frozenset()

    def __init__(self):
        self.saved = []

    def drafts(self):
        from ase2sprkkr_gui.gui.application.execution_profiles import ProfileDraft

        return {
            "local": ProfileDraft(
                "local", {"executor": "local", "mpi": "auto"}
            )
        }

    def save(self, drafts):
        self.saved.append({
            name: dict(draft.values) for name, draft in drafts.items()
        })


def test_settings_has_independent_frame_tabs(tmp_path):
    from PyQt6.QtWidgets import QFrame

    from ase2sprkkr_gui.gui.dialogs.settings import SettingsDialog
    from ase2sprkkr_gui.gui.widgets.settings.general import GeneralSettingsPage
    from ase2sprkkr_gui.gui.widgets.settings.run_configurations import RunConfigurationsPage

    dialog = SettingsDialog(
        ApplicationSettings(tmp_path / "settings.json"),
        profile_store=_FakeProfileStore(),
    )
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "General", "Run configurations"
    ]
    assert all(isinstance(dialog.tabs.widget(i), QFrame) for i in range(2))
    assert isinstance(dialog.general_page, GeneralSettingsPage)
    assert isinstance(dialog.run_configurations_page, RunConfigurationsPage)
    assert dialog.general_page.visualization_group.title() == "Visualization"
    assert dialog.general_page.sprkkr_group.title() == "SPR-KKR"
    assert dialog.general_page.python_shell_group.title() == "Python shell"
    assert dialog.share_python_shell_history is (
        dialog.general_page.share_python_shell_history
    )
    assert dialog.share_python_shell_history.isChecked()
    assert dialog.viewer is dialog.general_page.viewer
    assert dialog.dataset_default_mode is dialog.general_page.dataset_default_mode
    dialog.close()


def test_settings_accept_commits_run_profiles_and_application_defaults(tmp_path):
    from PyQt6.QtWidgets import QDialog

    from ase2sprkkr_gui.gui.dialogs.settings import SettingsDialog

    settings = ApplicationSettings(tmp_path / "settings.json")
    store = _FakeProfileStore()
    dialog = SettingsDialog(settings, profile_store=store)
    page = dialog.run_configurations_page
    page.form.executable_dir.setText("/opt/sprkkr")
    dataset = dialog.general_page.dataset_default_mode
    dataset.setCurrentIndex(dataset.findData("uuid"))
    dialog.share_python_shell_history.setChecked(False)

    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert store.saved[0]["local"]["executable_dir"] == "/opt/sprkkr"
    reloaded = ApplicationSettings(settings.path)
    reloaded.load()
    assert reloaded.dataset_default_mode == "uuid"
    assert reloaded.share_python_shell_history is False
    dialog.close()


def test_settings_without_run_edits_does_not_rewrite_profiles(tmp_path):
    from ase2sprkkr_gui.gui.dialogs.settings import SettingsDialog

    settings = ApplicationSettings(tmp_path / "settings.json")
    store = _FakeProfileStore()
    dialog = SettingsDialog(settings, profile_store=store)
    dialog.accept()
    assert store.saved == []
    dialog.close()


def test_run_profile_edits_survive_switching_profiles(tmp_path):
    from ase2sprkkr_gui.gui.application.execution_profiles import ProfileDraft
    from ase2sprkkr_gui.gui.dialogs.settings import SettingsDialog

    class TwoProfiles(_FakeProfileStore):
        def drafts(self):
            return {
                "first": ProfileDraft("first", {"executor": "local"}),
                "second": ProfileDraft("second", {"executor": "local"}),
            }

    store = TwoProfiles()
    dialog = SettingsDialog(
        ApplicationSettings(tmp_path / "settings.json"), profile_store=store
    )
    page = dialog.run_configurations_page
    assert page.list.currentRow() == 0
    page.form.executable_dir.setText("/opt/first")
    page.list.setCurrentRow(1)
    page.form.executable_dir.setText("/opt/second")
    dialog.accept()
    assert store.saved[0]["first"]["executable_dir"] == "/opt/first"
    assert store.saved[0]["second"]["executable_dir"] == "/opt/second"
    dialog.close()


def test_settings_cancel_does_not_commit_run_profiles(tmp_path):
    from ase2sprkkr_gui.gui.dialogs.settings import SettingsDialog

    settings = ApplicationSettings(tmp_path / "settings.json")
    store = _FakeProfileStore()
    dialog = SettingsDialog(settings, profile_store=store)
    dialog.run_configurations_page.form.executable_dir.setText("/opt/other")
    dialog.reject()

    assert store.saved == []
    assert not settings.path.exists()
    dialog.close()


def test_settings_run_profile_save_failure_keeps_dialog_open(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog, QMessageBox

    from ase2sprkkr_gui.gui.dialogs.settings import SettingsDialog

    class FailingStore(_FakeProfileStore):
        def save(self, drafts):
            raise OSError("profiles are read-only")

    messages = []
    monkeypatch.setattr(
        QMessageBox, "critical",
        lambda _parent, title, message: messages.append((title, message))
    )
    dialog = SettingsDialog(
        ApplicationSettings(tmp_path / "settings.json"),
        profile_store=FailingStore(),
    )
    dialog.run_configurations_page.form.executable_dir.setText("/opt/test")
    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert messages == [
        ("Cannot Save Run Configurations", "profiles are read-only")
    ]
    dialog.close()


def test_bundled_settings_icon_is_renderable():
    from PyQt6.QtGui import QIcon

    from ase2sprkkr_gui.gui.misc.icons import settings_icon
    from ase2sprkkr_gui.gui.misc.resources import icon_path

    icon = QIcon(str(icon_path("settings-cog.svg")))
    assert not icon.isNull()
    assert not icon.pixmap(24, 24).isNull()
    assert not settings_icon().pixmap(24, 24).isNull()
