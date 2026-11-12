from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.execution_profiles import ProfileDraft
from guy4ase.gui.widgets.execution_profiles import MpiEditor, ProfileForm


def _app():
    return QApplication.instance() or QApplication([])


def test_profile_form_exposes_all_execution_types():
    _application = _app()
    form = ProfileForm()

    kinds = [form.kind.itemData(index) for index in range(form.kind.count())]
    labels = [form.kind.itemText(index) for index in range(form.kind.count())]

    assert kinds == ["local", "ssh", "psij", "ssh-psij"]
    assert labels == [
        "Local computer",
        "Remote computer (SSH)",
        "Workload manager (PSI/J)",
        "Remote workload manager (SSH + PSI/J)",
    ]
    form.close()


def test_profile_form_explains_selected_run_target():
    _application = _app()
    form = ProfileForm()

    expected = {
        "local": "Run directly on this computer.",
        "ssh": "Run on another computer connected over SSH.",
        "psij": (
            "Submit the calculation to a workload manager accessible from this computer."
        ),
        "ssh-psij": (
            "Connect to a remote cluster over SSH and submit the calculation "
            "to its workload manager."
        ),
    }
    for kind, description in expected.items():
        form.kind.setCurrentIndex(form.kind.findData(kind))
        assert form.run_target_description.text() == description

    form.close()


def test_profile_form_serializes_all_execution_types():
    _application = _app()
    form = ProfileForm()

    form.kind.setCurrentIndex(form.kind.findData("local"))
    assert form.values()["executor"] == "local"

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    form.host.setText("user@cluster")
    ssh = form.values()
    assert ssh["executor"] == "ssh"
    assert ssh["host"] == "user@cluster"
    assert "psij_backend" not in ssh

    form.kind.setCurrentIndex(form.kind.findData("psij"))
    form.psij_backend.setText("slurm")
    psij = form.values()
    assert psij["executor"] == "psij"
    assert psij["psij_backend"] == "slurm"
    assert "host" not in psij

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    combined = form.values()
    assert combined["executor"] == "ssh"
    assert combined["host"] == "user@cluster"
    assert combined["psij_backend"] == "slurm"
    form.close()


def test_profile_form_shows_only_backend_specific_sections():
    _application = _app()
    form = ProfileForm()

    form.kind.setCurrentIndex(form.kind.findData("local"))
    assert form.ssh_box.isHidden()
    assert form.psij_box.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    assert not form.ssh_box.isHidden()
    assert form.psij_box.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("psij"))
    assert form.ssh_box.isHidden()
    assert not form.psij_box.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    assert not form.ssh_box.isHidden()
    assert not form.psij_box.isHidden()
    form.close()


def test_mpi_editor_supports_all_modes():
    _application = _app()
    editor = MpiEditor()

    assert not hasattr(editor, "setText")

    for mode, value in (
        ("auto", "auto"),
        ("enabled", True),
        ("disabled", False),
    ):
        editor.mode.setCurrentIndex(editor.mode.findData(mode))
        assert editor.value() == value

    editor.mode.setCurrentIndex(editor.mode.findData("processes"))
    editor.processes.setValue(12)
    assert editor.value() == 12
    assert editor.detail.currentWidget() is editor.processes

    editor.mode.setCurrentIndex(editor.mode.findData("command"))
    editor.command.setText("mpirun --bind-to core")
    assert editor.value() == ["mpirun", "--bind-to", "core"]
    assert editor.detail.currentWidget() is editor.command
    editor.close()


def test_mpi_editor_loads_existing_typed_values():
    _application = _app()
    editor = MpiEditor()

    for value, mode in (
        (None, "auto"),
        ("auto", "auto"),
        (True, "enabled"),
        (False, "disabled"),
        (8, "processes"),
        (["srun", "-n", "4"], "command"),
    ):
        editor.set_value(value)
        assert editor.mode.currentData() == mode

    assert editor.command.text() == "srun -n 4"
    editor.close()


def test_mpi_warning_is_visible_only_for_autodetection_and_is_preserved():
    _application = _app()
    form = ProfileForm()

    assert form.mpi_warning.isHidden()
    form.mode.setCurrentIndex(form.mode.findData("expert"))
    form.mpi.set_value("auto")
    assert not form.mpi_warning.isHidden()
    assert form.mpi_warning.isChecked()

    form.mpi_warning.setChecked(False)
    form.mpi.set_value(8)
    assert form.mpi_warning.isHidden()
    assert form.values()["mpi_warning"] is False

    form.mpi.set_value("auto")
    assert not form.mpi_warning.isHidden()
    assert not form.mpi_warning.isChecked()
    form.close()


def test_profile_form_loads_mpi_warning_with_true_default():
    _application = _app()
    form = ProfileForm()

    form.load(ProfileDraft("default", {"mpi": "auto"}))
    assert form.mpi_warning.isChecked()

    form.load(
        ProfileDraft(
            "quiet",
            {"mpi": "auto", "mpi_warning": False},
        )
    )
    assert not form.mpi_warning.isChecked()
    assert form.values()["mpi_warning"] is False
    form.close()


def test_profile_form_defaults_to_simple_with_only_common_settings():
    _application = _app()
    form = ProfileForm()
    assert form.mode.currentData() == "simple"
    assert not form.kind.isHidden()
    assert not form.mpi.isHidden()
    assert not form.executable_dir.isHidden()
    assert form.executable_suffix.isHidden()
    assert form.mpi_warning.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    for field in (form.host, form.local_root, form.remote_root):
        assert not field.isHidden()
    for field in (
        form.ssh_options,
        form.remote_command,
        form.input_sync,
        form.output_sync,
    ):
        assert field.isHidden()
        assert form._ssh_form.labelForField(field).isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    assert not form.psij_backend.isHidden()
    assert form.psij_url.isHidden()
    assert form._psij_form.labelForField(form.psij_url).isHidden()
    form.close()


def test_profile_form_expert_switch_restores_all_advanced_fields():
    _application = _app()
    form = ProfileForm()
    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    form.mode.setCurrentIndex(form.mode.findData("expert"))
    for field in (
        form.executable_suffix,
        form.ssh_options,
        form.remote_command,
        form.input_sync,
        form.output_sync,
        form.psij_url,
        form.mpi_warning,
    ):
        assert not field.isHidden()

    form.mpi.set_value(8)
    assert form.mpi_warning.isHidden()
    form.mode.setCurrentIndex(form.mode.findData("simple"))
    assert form.remote_command.isHidden()
    assert not form.remote_root.isHidden()
    form.mode.setCurrentIndex(form.mode.findData("expert"))
    assert not form.remote_command.isHidden()
    form.close()


def test_simple_mode_preserves_advanced_values_when_editing_common_settings():
    _application = _app()
    form = ProfileForm()
    configured = {
        "executor": "ssh",
        "mpi": "auto",
        "mpi_warning": False,
        "executable_dir": "/opt/sprkkr",
        "executable_suffix": "_v8",
        "host": "user@cluster",
        "local_root": "/local/work",
        "remote_root": "/remote/work",
        "ssh_options": ["-p", "2222"],
        "remote_command": ["ase2sprkkr", "remote"],
        "input_sync": "never",
        "output_sync": "always",
        "psij_backend": "slurm",
        "psij_url": "ssh://batch.example",
    }
    form.load(ProfileDraft("cluster", configured))
    assert form.mode.currentData() == "simple"
    assert form.values() == configured

    form.host.setText("other@cluster")
    expected = {**configured, "host": "other@cluster"}
    assert form.values() == expected
    form.mode.setCurrentIndex(form.mode.findData("expert"))
    assert form.values() == expected
    form.mode.setCurrentIndex(form.mode.findData("simple"))
    assert form.values() == expected
    form.close()
