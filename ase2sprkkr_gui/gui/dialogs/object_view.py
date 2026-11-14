"""Read-only result/object inspection, separate from parameter editing."""
from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence as AbcSequence
from pathlib import Path
from typing import Any, Optional

import numpy as np
from ase2sprkkr.common.configuration_containers import ConfigurationContainer
from ase2sprkkr.common.options import BaseOption
from ase2sprkkr.common.repeated_configuration_containers import (
    RepeatedConfigurationContainer,
)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QToolButton,
    QTreeWidgetItem,
    QWidget,
)

from ase2sprkkr_gui.gui.dialogs._tree_base import _TreeDialogBase
from ase2sprkkr_gui.gui.widgets.result_actions import result_action_icon, result_action_tooltip


class ReadOnlyObjectDialog(_TreeDialogBase):
    def __init__(self, value: Any, title: str = 'View Value', parent: Optional[QWidget] = None):
        self._value = value
        self._visited: set[int] = set()
        super().__init__(title, parent=parent, filter_all_columns=True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(['Name', 'Type', 'Value', 'Comment', 'Actions'])
        self._tree.setColumnWidth(4, 140)
        self.close_btn = self._add_footer_button('Close', self.close)
        self._build_tree()

    def _build_tree(self) -> None:
        self._visited.clear()
        self._add_value('value', self._value, None)
        self._tree.expandToDepth(1)

    def _safe_text(self, value: Any) -> str:
        if isinstance(value, BaseOption):
            try:
                value = value()
            except Exception as exc:
                return f'<error: {exc}>'
        if value is None:
            return 'None'
        if isinstance(value, np.ndarray):
            return '<Data>'
        if isinstance(value, str):
            return value
        try:
            return str(value)
        except Exception:
            return repr(value)

    def _is_scalar(self, value: Any) -> bool:
        if isinstance(value, BaseOption):
            try:
                value = value()
            except Exception:
                return True
        scalar_types = (str, bytes, int, float, bool, complex, type(None), Path)
        if isinstance(value, scalar_types):
            return True
        if isinstance(value, (np.generic, np.ndarray)):
            return True
        return False

    def _iter_object_items(self, value: Any) -> list[tuple[str, Any, str]]:
        if isinstance(value, np.ndarray):
            return []
        if isinstance(value, RepeatedConfigurationContainer):
            values = value._values
            iterable = values.items() if isinstance(values, Mapping) else enumerate(values)
            return [(f'[{key}]', item, '') for key, item in iterable]
        if isinstance(value, ConfigurationContainer):
            return [(str(key), item, '') for key, item in value.items().items()]
        if isinstance(value, Mapping):
            return [(str(key), item, '') for key, item in value.items()]
        if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
            return [(f'[{idx}]', item, '') for idx, item in enumerate(value)]
        if hasattr(value, '__dict__'):
            out = []
            for key, item in vars(value).items():
                if key.startswith('_'):
                    continue
                if callable(item):
                    continue
                out.append((str(key), item, ''))
            return out
        return []

    def _add_value(self, name: str, value: Any, parent: Optional[QTreeWidgetItem]) -> None:
        type_name = type(value).__name__
        display = self._safe_text(value)
        if len(display) > 500:
            display = display[:497] + '...'

        item = QTreeWidgetItem([name, type_name, display if self._is_scalar(value) else '', ''])
        item.setToolTip(1, type_name)
        if display:
            item.setToolTip(2, display)
        self._add_child(parent, item)
        self._add_actions(item, value)

        if self._is_scalar(value):
            return

        obj_id = id(value)
        if obj_id in self._visited:
            item.setText(3, 'Already shown above')
            return
        self._visited.add(obj_id)

        children = self._iter_object_items(value)
        if not children:
            item.setText(2, display)
            return

        for child_name, child_value, comment in children:
            child = QTreeWidgetItem([child_name, type(child_value).__name__, '', comment])
            self._add_child(item, child)
            if self._is_scalar(child_value):
                child_display = self._safe_text(child_value)
                child.setText(2, child_display)
                child.setToolTip(2, child_display)
                self._add_actions(child, child_value)
            else:
                item.removeChild(child)
                self._add_value(child_name, child_value, item)

    def _add_actions(self, item: QTreeWidgetItem, value: Any) -> None:
        actions_method = getattr(value, 'actions', None)
        if not callable(actions_method):
            return
        try:
            actions = tuple(actions_method())
        except Exception:
            return
        if not actions:
            return

        holder = QWidget(self._tree)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for action in actions:
            button = QToolButton(holder)
            button.setAutoRaise(True)
            button.setIcon(result_action_icon(self.style(), action))
            button.setToolTip(result_action_tooltip(value, action))
            button.clicked.connect(lambda _checked=False, v=value, a=action: self._execute_action(v, a))
            layout.addWidget(button)
        layout.addStretch(1)
        self._tree.setItemWidget(item, 4, holder)

    def _execute_action(self, value: Any, action: str) -> None:
        execute_value_action(value, action, self)


def execute_value_action(
    value: Any, action: str, parent: QWidget
) -> None:
    """Execute one advertised result action with uniform error handling."""
    try:
        if action in {"data", "edit"}:
            result = value.data() if action == "data" else value()
            display_name = getattr(
                value, "display_name", getattr(value, "name", "Value")
            )
            show_readonly_object_dialog(
                result,
                title=f"View {display_name}",
                parent=parent,
            )
            return
        method = getattr(value, action)
        method()
    except Exception as exc:  # noqa: BLE001 - plugin action boundary
        QMessageBox.critical(
            parent,
            "Action Error",
            f"Failed to execute action '{action}':\n{exc}",
        )


def show_readonly_object_dialog(value: Any, title: str = 'View Value', parent: Optional[QWidget] = None) -> ReadOnlyObjectDialog:
    dlg = ReadOnlyObjectDialog(value, title=title, parent=parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
