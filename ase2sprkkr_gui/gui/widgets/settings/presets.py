"""Settings page for input-parameter and task-scoped YAML presets."""
from __future__ import annotations

import re

from ase2sprkkr import InputParameters
from ase2sprkkr.input_parameters.presets import PresetStore
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QStyle,
    QVBoxLayout, QWidget,
)

from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.tasks import is_guided_task


_PRESET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def preset_scopes(identifiers: tuple[str, ...]) -> tuple[str, ...]:
    """Only show namespaces that actually contain presets, not all tasks."""
    return tuple(sorted(
        {identifier.rsplit(".", 1)[0] for identifier in identifiers},
        key=lambda scope: (scope.startswith("task:"), scope.split(":", 1)[1]),
    ))


def scope_label(scope: str) -> str:
    kind, owner = scope.split(":", 1)
    return f"{'IPD' if kind == 'input_parameters' else 'Task'}  ·  {owner.upper()}"


class PresetsSettingsPage(QFrame):
    """Manage exact preset namespaces; saving is immediate, as in the editors."""

    def __init__(
        self, parent: QWidget | None = None, *, store: PresetStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store if store is not None else PresetStore()

        root = QVBoxLayout(self)
        explanation = QLabel(
            "Create reusable input-parameter presets for an IPD or an individual "
            "task. IPD presets can be shared by tasks using the same parameters.",
            self,
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QWidget(splitter)
        left.setMinimumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.addWidget(QLabel("IPDs and tasks with presets", left))
        self.scopes = QListWidget(left)
        self.scopes.setObjectName("presetScopes")
        self.scopes.setAlternatingRowColors(True)
        self.scopes.currentItemChanged.connect(self._refresh_presets)
        left_layout.addWidget(self.scopes, 1)
        self.new_scope_button = QPushButton("New preset for…", left)
        self.new_scope_button.setObjectName("newPresetForTask")
        self.new_scope_button.setToolTip("Choose an IPD or task, including one with no presets yet")
        self.new_scope_button.setIcon(
            QIcon.fromTheme(
                "list-add", self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
            )
        )
        self.new_scope_button.clicked.connect(self._choose_scope)
        left_layout.addWidget(self.new_scope_button)
        splitter.addWidget(left)

        self.details = QWidget(splitter)
        right_layout = QVBoxLayout(self.details)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.preset_heading = QLabel("Presets", self.details)
        right_layout.addWidget(self.preset_heading)
        self.presets = QListWidget(self.details)
        self.presets.setObjectName("scopedPresets")
        self.presets.setAlternatingRowColors(True)
        self.presets.currentItemChanged.connect(self._update_buttons)
        self.presets.itemDoubleClicked.connect(lambda _item: self._copy_preset())
        right_layout.addWidget(self.presets, 1)

        actions = QHBoxLayout()
        self.add_button = self._action_button(
            "Add…", "list-add", QStyle.StandardPixmap.SP_FileDialogNewFolder,
            "Create a new preset for the selected IPD or task", self._add_preset,
        )
        self.copy_button = self._action_button(
            "Copy…", "edit-copy", QStyle.StandardPixmap.SP_FileIcon,
            "Use the selected preset as the starting point for a new preset",
            self._copy_preset,
        )
        self.remove_button = self._action_button(
            "Remove", "edit-delete", QStyle.StandardPixmap.SP_TrashIcon,
            "Delete the selected preset", self._remove_preset,
        )
        for button in (self.add_button, self.copy_button, self.remove_button):
            actions.addWidget(button)
        actions.addStretch(1)
        right_layout.addLayout(actions)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 700])

        note = QLabel(
            "Preset changes are saved immediately, even if you later cancel Settings.",
            self,
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self._refresh_scopes()

    def _action_button(self, label, icon, fallback, tooltip, callback):
        button = QPushButton(label, self.details)
        button.setIcon(QIcon.fromTheme(icon, self.style().standardIcon(fallback)))
        button.setIconSize(QSize(18, 18))
        button.setMinimumSize(QSize(110, 34))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def _current_scope(self) -> str | None:
        item = self.scopes.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _current_preset(self) -> str | None:
        item = self.presets.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _refresh_scopes(
        self, select_scope: str | None = None, select_preset: str | None = None,
    ) -> None:
        if select_scope is None:
            select_scope = self._current_scope()
        self.scopes.blockSignals(True)
        self.scopes.clear()
        try:
            identifiers = self._store.list()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot list presets", str(exc))
            identifiers = ()
        for scope in preset_scopes(identifiers):
            item = QListWidgetItem(scope_label(scope), self.scopes)
            item.setData(Qt.ItemDataRole.UserRole, scope)
        for row in range(self.scopes.count()):
            if self.scopes.item(row).data(Qt.ItemDataRole.UserRole) == select_scope:
                self.scopes.setCurrentRow(row)
                break
        else:
            if self.scopes.count():
                self.scopes.setCurrentRow(0)
        self.scopes.blockSignals(False)
        self._refresh_presets(select_preset=select_preset)

    def _refresh_presets(
        self, *_args, select_preset: str | None = None,
    ) -> None:
        scope = self._current_scope()
        if select_preset is None:
            select_preset = self._current_preset()
        self.presets.blockSignals(True)
        self.presets.clear()
        self.preset_heading.setText(
            f"Presets · {scope_label(scope)}" if scope else "Select an IPD or task"
        )
        if scope:
            try:
                names = self._store.list()
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Cannot list presets", str(exc))
                names = ()
            prefix = scope + "."
            for name in names:
                if name.startswith(prefix):
                    item = QListWidgetItem(name[len(prefix):], self.presets)
                    item.setData(Qt.ItemDataRole.UserRole, name)
            for row in range(self.presets.count()):
                if self.presets.item(row).data(Qt.ItemDataRole.UserRole) == select_preset:
                    self.presets.setCurrentRow(row)
                    break
            else:
                if self.presets.count():
                    self.presets.setCurrentRow(0)
        self.presets.blockSignals(False)
        self.details.setEnabled(scope is not None)
        self._update_buttons()

    def _update_buttons(self, *_args) -> None:
        scope = self._current_scope()
        preset = self._current_preset()
        self.add_button.setEnabled(scope is not None)
        self.copy_button.setEnabled(scope is not None and preset is not None)
        self.remove_button.setEnabled(scope is not None and preset is not None)

    @staticmethod
    def _scope_choices() -> tuple[tuple[str, str], ...]:
        def allowed(name):
            return _PRESET_NAME.fullmatch(str(name)) is not None

        ipds = (
            (f"IPD  ·  {name.upper()}", f"input_parameters:{name.lower()}")
            for name in InputParameters.input_parameters_registry.names()
            if allowed(name)
        )
        tasks = (
            (f"Task  ·  {name.upper()}", f"task:{name.lower()}")
            for name in InputParameters.task_registry.names()
            if allowed(name)
        )
        return tuple(sorted((*ipds, *tasks), key=lambda row: row[0]))

    def _choose_scope(self) -> None:
        choices = self._scope_choices()
        labels = [label for label, _ in choices]
        if not choices:
            QMessageBox.information(self, "No IPDs or tasks", "No input-parameter definitions are available.")
            return
        label, accepted = QInputDialog.getItem(
            self, "New preset", "Choose an IPD or task:", labels, 0, False,
        )
        if accepted:
            scope = dict(choices)[label]
            self._open_editor(scope)

    def _add_preset(self) -> None:
        scope = self._current_scope()
        if scope:
            self._open_editor(scope)

    def _copy_preset(self) -> None:
        scope, preset = self._current_scope(), self._current_preset()
        if scope and preset:
            self._open_editor(scope, base_preset=preset)

    def _open_editor(self, scope: str, *, base_preset: str | None = None) -> None:
        kind, owner = scope.split(":", 1)
        try:
            parameters = (
                InputParameters.for_definition(owner)
                if kind == "input_parameters" else InputParameters.for_task(owner)
            )
            if base_preset:
                parameters.load_preset(base_preset, clear_first=True, store=self._store)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open preset editor", str(exc))
            return

        def save(edited: InputParameters) -> bool:
            return self._save_named_preset(scope, edited, base_preset=base_preset)

        task = parameters.task_name
        if task and is_guided_task(task):
            dialog = GuidedInputParametersDialog(
                task, parameters, self, preset_save=save,
            )
        else:
            dialog = InputParametersDialog(parameters, self, preset_save=save)
        dialog.exec()

    def _copy_suggestion(self, base_preset: str | None) -> str:
        if not base_preset:
            return ""
        stem = base_preset.rsplit(".", 1)[-1] + "_copy"
        taken = set(self._store.list())
        scope = base_preset.rsplit(".", 1)[0]
        suggestion = stem
        suffix = 2
        while f"{scope}.{suggestion}" in taken:
            suggestion = f"{stem}{suffix}"
            suffix += 1
        return suggestion

    def _save_named_preset(
        self, scope: str, parameters: InputParameters, *,
        base_preset: str | None = None,
    ) -> bool:
        suggestion = self._copy_suggestion(base_preset)
        while True:
            name, accepted = QInputDialog.getText(
                self, "Save preset", f"Preset name for {scope_label(scope)}:",
                QLineEdit.EchoMode.Normal, suggestion,
            )
            if not accepted:
                return False
            name = name.strip()
            if not _PRESET_NAME.fullmatch(name):
                QMessageBox.warning(
                    self, "Invalid preset name",
                    "Use letters, digits, underscores or hyphens, starting with a letter or digit.",
                )
                suggestion = name
                continue
            identifier = f"{scope}.{name.lower()}"
            if identifier in self._store.list():
                QMessageBox.warning(
                    self, "Preset already exists",
                    f"'{name}' already exists in {scope_label(scope)}. Choose another name.",
                )
                suggestion = name
                continue
            try:
                parameters.save_preset(identifier, store=self._store)
            except FileExistsError:
                QMessageBox.warning(
                    self, "Preset already exists", "That name has just been taken. Choose another.",
                )
                suggestion = name
                continue
            except (OSError, TypeError, ValueError) as exc:
                QMessageBox.critical(self, "Cannot save preset", str(exc))
                return False
            self._refresh_scopes(select_scope=scope, select_preset=identifier)
            return True

    def _remove_preset(self) -> None:
        identifier = self._current_preset()
        if not identifier:
            return
        answer = QMessageBox.question(
            self, "Remove preset", f"Delete preset '{identifier}' permanently?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.resolve(identifier).unlink()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot remove preset", str(exc))
            return
        self._refresh_scopes()
