"""Reusable editors for SPR-KKR execution profiles."""
from __future__ import annotations

import shlex
from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.execution_profiles import ProfileDraft, draft_kind

SYNC_POLICIES = ("changed", "always", "missing", "never")
MPI_MODES = (
    ("auto", "Autodetect"),
    ("enabled", "Yes"),
    ("disabled", "No"),
    ("processes", "Number of processes"),
    ("command", "Command"),
)
RUN_TARGET_DESCRIPTIONS = {
    "local": "Run directly on this computer.",
    "ssh": "Run on another computer connected over SSH.",
    "psij": "Submit the calculation to a workload manager accessible from this computer.",
    "ssh-psij": (
        "Connect to a remote cluster over SSH and submit the calculation "
        "to its workload manager."
    ),
}


def argv_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return shlex.join(str(item) for item in value)


class MpiEditor(QWidget):
    """Typed editor for the supported MPI profile values."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.mode = QComboBox(self)
        for value, label in MPI_MODES:
            self.mode.addItem(label, value)
        self.mode.setMinimumContentsLength(18)
        layout.addWidget(self.mode)

        self.detail = QStackedWidget(self)
        self._blank = QWidget(self.detail)
        self.processes = QSpinBox(self.detail)
        self.processes.setRange(1, 1_000_000)
        self.processes.setValue(2)
        self.command = QLineEdit(self.detail)
        self.command.setPlaceholderText("e.g. mpirun --bind-to core")
        self.detail.addWidget(self._blank)
        self.detail.addWidget(self.processes)
        self.detail.addWidget(self.command)
        layout.addWidget(self.detail, 1)

        self.mode.currentIndexChanged.connect(self._update_detail)
        self._update_detail()

    def _update_detail(self) -> None:
        mode = self.mode.currentData()
        if mode == "processes":
            self.detail.setCurrentWidget(self.processes)
        elif mode == "command":
            self.detail.setCurrentWidget(self.command)
        else:
            self.detail.setCurrentWidget(self._blank)

    def set_value(self, value: Any) -> None:
        if value is None or value == "auto":
            mode = "auto"
        elif value is True:
            mode = "enabled"
        elif value is False:
            mode = "disabled"
        elif isinstance(value, int):
            mode = "processes"
            self.processes.setValue(max(1, value))
        elif isinstance(value, (tuple, list)):
            mode = "command"
            self.command.setText(argv_text(value))
        elif isinstance(value, str):
            mode = "command"
            self.command.setText(value)
        else:
            mode = "auto"
        self.mode.setCurrentIndex(max(self.mode.findData(mode), 0))
        self._update_detail()

    def value(self) -> Any:
        mode = self.mode.currentData()
        if mode == "auto":
            return "auto"
        if mode == "enabled":
            return True
        if mode == "disabled":
            return False
        if mode == "processes":
            return self.processes.value()
        return shlex.split(self.command.text())


class ProfileForm(QWidget):
    """Edit one profile draft; backend-specific sections follow its type."""

    KINDS = (
        ("local", "Local computer"),
        ("ssh", "Remote computer (SSH)"),
        ("psij", "Workload manager (PSI/J)"),
        ("ssh-psij", "Remote workload manager (SSH + PSI/J)"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(14)

        self.title = QLabel("Profile settings", self)
        title_font = self.title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        self.title.setFont(title_font)
        root.addWidget(self.title)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Settings:", self))
        self.mode = QComboBox(self)
        self.mode.addItem("Simple", "simple")
        self.mode.addItem("Expert", "expert")
        self.mode.setToolTip(
            "Simple shows common settings; Expert also shows commands, "
            "synchronization policies and other advanced options."
        )
        self.mode.currentIndexChanged.connect(self._update_visibility)
        mode_row.addWidget(self.mode)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        self.read_only_note = QLabel(
            "This profile is provided by another configuration source and is read-only.",
            self,
        )
        self.read_only_note.setWordWrap(True)
        root.addWidget(self.read_only_note)

        self.form_widget = QWidget(self)
        form_root = QVBoxLayout(self.form_widget)
        form_root.setContentsMargins(0, 0, 0, 0)
        form_root.setSpacing(12)

        run_box = QGroupBox("Run target", self.form_widget)
        run_form = QFormLayout(run_box)
        run_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.kind = QComboBox(run_box)
        for value, label in self.KINDS:
            self.kind.addItem(label, value)
        self.kind.setMinimumContentsLength(30)
        self.kind.currentIndexChanged.connect(self._update_visibility)
        run_form.addRow("Type:", self.kind)
        self.run_target_description = QLabel(run_box)
        self.run_target_description.setWordWrap(True)
        self.run_target_description.setStyleSheet("color: palette(mid);")
        run_form.addRow(self.run_target_description)
        self.mpi = MpiEditor(run_box)
        self.mpi.mode.currentIndexChanged.connect(self._update_mpi_warning_visibility)
        run_form.addRow("MPI:", self.mpi)
        self.mpi_warning = QCheckBox("Warn if MPI is not detected", run_box)
        self.mpi_warning.setToolTip(
            "Show a warning when MPI autodetection cannot find an MPI runner "
            "and the calculation falls back to non-MPI execution."
        )
        self.mpi_warning.setChecked(True)
        run_form.addRow(self.mpi_warning)
        form_root.addWidget(run_box)

        executable_box = QGroupBox("SPR-KKR executables", self.form_widget)
        executable_form = QFormLayout(executable_box)
        executable_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.executable_dir = QLineEdit(executable_box)
        self.executable_dir.setPlaceholderText("Use PATH when empty")
        executable_form.addRow("Directory:", self.executable_dir)
        self.executable_suffix = QLineEdit(executable_box)
        self.executable_suffix.setPlaceholderText("e.g. _v8")
        executable_form.addRow("Suffix:", self.executable_suffix)
        self._executable_form = executable_form
        form_root.addWidget(executable_box)

        self.ssh_box = QGroupBox("SSH connection and workspace", self.form_widget)
        ssh_form = QFormLayout(self.ssh_box)
        ssh_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.host = QLineEdit(self.ssh_box)
        self.host.setPlaceholderText("user@cluster.example")
        ssh_form.addRow("Host:", self.host)
        self.local_root = QLineEdit(self.ssh_box)
        ssh_form.addRow("Local root:", self.local_root)
        self.remote_root = QLineEdit(self.ssh_box)
        ssh_form.addRow("Remote root:", self.remote_root)
        self.ssh_options = QLineEdit(self.ssh_box)
        self.ssh_options.setPlaceholderText("e.g. -p 2222")
        ssh_form.addRow("SSH options:", self.ssh_options)
        self.remote_command = QLineEdit(self.ssh_box)
        self.remote_command.setPlaceholderText("ase2sprkkr remote")
        ssh_form.addRow("Remote command:", self.remote_command)
        self.input_sync = QComboBox(self.ssh_box)
        self.output_sync = QComboBox(self.ssh_box)
        for policy in SYNC_POLICIES:
            self.input_sync.addItem(policy)
            self.output_sync.addItem(policy)
        ssh_form.addRow("Input sync:", self.input_sync)
        ssh_form.addRow("Output sync:", self.output_sync)
        self._ssh_form = ssh_form
        form_root.addWidget(self.ssh_box)

        self.psij_box = QGroupBox("Workload manager (PSI/J)", self.form_widget)
        psij_form = QFormLayout(self.psij_box)
        psij_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.psij_backend = QLineEdit(self.psij_box)
        self.psij_backend.setPlaceholderText("slurm")
        psij_form.addRow("Backend:", self.psij_backend)
        self.psij_url = QLineEdit(self.psij_box)
        self.psij_url.setPlaceholderText("Optional executor URL")
        psij_form.addRow("URL:", self.psij_url)
        self._psij_form = psij_form
        form_root.addWidget(self.psij_box)

        root.addWidget(self.form_widget)
        root.addStretch(1)
        self._update_visibility()

    @staticmethod
    def _set_row_visible(layout: QFormLayout, field: QWidget, visible: bool) -> None:
        """Hide both the editor and its label (not just the editor)."""
        field.setVisible(visible)
        label = layout.labelForField(field)
        if label is not None:
            label.setVisible(visible)

    def _update_mpi_warning_visibility(self) -> None:
        self.mpi_warning.setVisible(
            self.mode.currentData() == "expert"
            and self.mpi.mode.currentData() == "auto"
        )

    def _update_visibility(self) -> None:
        kind = str(self.kind.currentData())
        ssh = kind in {"ssh", "ssh-psij"}
        psij = kind in {"psij", "ssh-psij"}
        expert = self.mode.currentData() == "expert"

        self.run_target_description.setText(RUN_TARGET_DESCRIPTIONS.get(kind, ""))
        self.ssh_box.setVisible(ssh)
        self.psij_box.setVisible(psij)
        self._update_mpi_warning_visibility()

        self._set_row_visible(self._executable_form, self.executable_suffix, expert)
        for field in (self.host, self.local_root, self.remote_root):
            self._set_row_visible(self._ssh_form, field, ssh)
        for field in (
            self.ssh_options,
            self.remote_command,
            self.input_sync,
            self.output_sync,
        ):
            self._set_row_visible(self._ssh_form, field, ssh and expert)
        self._set_row_visible(self._psij_form, self.psij_backend, psij)
        self._set_row_visible(self._psij_form, self.psij_url, psij and expert)

    def load(self, draft: ProfileDraft) -> None:
        values = draft.values
        kind = draft_kind(values)
        self.kind.setCurrentIndex(max(self.kind.findData(kind), 0))
        self.mpi.set_value(values.get("mpi"))
        self.mpi_warning.setChecked(bool(values.get("mpi_warning", True)))
        self.executable_dir.setText(str(values.get("executable_dir") or ""))
        self.executable_suffix.setText(str(values.get("executable_suffix") or ""))
        self.host.setText(str(values.get("host") or ""))
        self.local_root.setText(str(values.get("local_root") or ""))
        self.remote_root.setText(str(values.get("remote_root") or ""))
        self.ssh_options.setText(argv_text(values.get("ssh_options")))
        self.remote_command.setText(argv_text(values.get("remote_command")))
        self.input_sync.setCurrentText(str(values.get("input_sync") or "changed"))
        self.output_sync.setCurrentText(str(values.get("output_sync") or "changed"))
        self.psij_backend.setText(str(values.get("psij_backend") or ""))
        self.psij_url.setText(str(values.get("psij_url") or ""))
        self.form_widget.setEnabled(not draft.read_only)
        self.read_only_note.setVisible(draft.read_only)
        self._update_visibility()

    def values(self) -> dict[str, Any]:
        kind = str(self.kind.currentData())
        executor = "ssh" if kind == "ssh-psij" else kind
        values: dict[str, Any] = {
            "executor": executor,
            "mpi": self.mpi.value(),
            "mpi_warning": self.mpi_warning.isChecked(),
        }
        for name, edit in (
            ("executable_dir", self.executable_dir),
            ("executable_suffix", self.executable_suffix),
        ):
            text = edit.text().strip()
            if text:
                values[name] = text

        if kind in {"ssh", "ssh-psij"}:
            for name, edit in (
                ("host", self.host),
                ("local_root", self.local_root),
                ("remote_root", self.remote_root),
            ):
                text = edit.text().strip()
                if text:
                    values[name] = text
            ssh_options = shlex.split(self.ssh_options.text())
            remote_command = shlex.split(self.remote_command.text())
            if ssh_options:
                values["ssh_options"] = ssh_options
            if remote_command:
                values["remote_command"] = remote_command
            values["input_sync"] = self.input_sync.currentText()
            values["output_sync"] = self.output_sync.currentText()

        if kind in {"psij", "ssh-psij"}:
            backend = self.psij_backend.text().strip()
            url = self.psij_url.text().strip()
            if backend:
                values["psij_backend"] = backend
            if url:
                values["psij_url"] = url
        return values
