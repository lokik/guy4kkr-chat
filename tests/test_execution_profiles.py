from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.execution_profiles import ProfileDraft
from guy4ase.gui.dialogs import profiles as profiles_dialogs
from guy4ase.gui.widgets.execution_profiles import ProfileForm


def _app():
    return QApplication.instance() or QApplication([])


class _ReadOnlyStore:
    def drafts(self):
        return {
            "ase": ProfileDraft(
                "ase",
                {"executor": "local"},
                read_only=True,
            )
        }


def test_profile_form_changes_fields_with_execution_type():
    _application = _app()
    form = ProfileForm()

    form.kind.setCurrentIndex(form.kind.findData("local"))
    assert form.host.isHidden()
    assert form.psij_backend.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    assert not form.host.isHidden()
    assert form.psij_backend.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    assert not form.host.isHidden()
    assert not form.psij_backend.isHidden()
    form.close()


def test_profile_form_parses_mpi_and_backend_specific_values():
    _application = _app()
    form = ProfileForm()
    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    form.mpi.set_value(8)
    form.host.setText("user@cluster")
    form.ssh_options.setText("-p 2222")
    form.psij_backend.setText("slurm")

    values = form.values()

    assert values["executor"] == "ssh"
    assert values["mpi"] == 8
    assert values["mpi_warning"] is True
    assert values["host"] == "user@cluster"
    assert values["ssh_options"] == ["-p", "2222"]
    assert values["psij_backend"] == "slurm"
    assert values["backend"] == "psij"
    form.close()


def test_read_only_profile_cannot_be_deleted_or_edited():
    _application = _app()
    dialog = profiles_dialogs.ProfilesDialog(store=_ReadOnlyStore())

    assert not dialog.delete_button.isEnabled()
    assert not dialog.form.form_widget.isEnabled()
    dialog.close()


def test_standalone_profile_dialog_reuses_run_settings_page():
    from guy4ase.gui.widgets.settings.run_configurations import RunConfigurationsPage

    dialog = profiles_dialogs.ProfilesDialog(store=_ReadOnlyStore())
    assert isinstance(dialog.page, RunConfigurationsPage)
    assert dialog.form is dialog.page.form
    assert dialog.delete_button is dialog.page.delete_button
    assert dialog.findChildren(RunConfigurationsPage) == [dialog.page]
    dialog.close()
