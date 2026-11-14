"""Shared dialog shell for searchable tree views."""
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _TreeDialogBase(QDialog):
    def __init__(self, title: str, parent: Optional[QWidget] = None, *, filter_all_columns: bool = False):
        super().__init__(parent)
        self._filter_all_columns = filter_all_columns
        self.setWindowTitle(title)
        self.resize(800, 600)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name…")
        self._filter_clear_btn = QPushButton("Clear")
        self._expand_all_btn = QPushButton("Expand all")
        self._collapse_all_btn = QPushButton("Collapse all")

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(['Name', 'Type', 'Value', 'Comment'])
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.setColumnWidth(0, 300)

        root = QVBoxLayout(self)
        self._root_layout = root
        header = QWidget(self)
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.addWidget(QLabel("Search:"))
        header_l.addWidget(self._filter_edit, 1)
        header_l.addWidget(self._filter_clear_btn)
        header_l.addStretch(1)
        header_l.addWidget(self._expand_all_btn)
        header_l.addWidget(self._collapse_all_btn)
        self._header_layout = header_l
        root.addWidget(header, 0)
        root.addWidget(self._tree, 1)

        self._footer = QHBoxLayout()
        self._footer.addStretch(1)
        root.addLayout(self._footer)

        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_clear_btn.clicked.connect(self._clear_filter)
        self._expand_all_btn.clicked.connect(self._tree.expandAll)
        self._collapse_all_btn.clicked.connect(self._tree.collapseAll)

    def _add_footer_button(self, text: str, slot: callable) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        self._footer.addWidget(button)
        return button

    def _add_child(self, parent: Optional[QTreeWidgetItem], child: QTreeWidgetItem) -> None:
        if parent is None:
            self._tree.addTopLevelItem(child)
        else:
            parent.addChild(child)

    def _clear_filter(self) -> None:
        self._filter_edit.setText("")
        self._filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _item_filter_texts(self, item: QTreeWidgetItem) -> list[str]:
        if self._filter_all_columns:
            return [item.text(i) or "" for i in range(self._tree.columnCount())]
        return [item.text(0) or ""]

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            if not needle:
                for i in range(item.childCount()):
                    visit(item.child(i))
                item.setHidden(False)
                return True

            self_match = any(needle in column.lower() for column in self._item_filter_texts(item))
            child_match = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    child_match = True
            visible = self_match or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self._tree.topLevelItemCount()):
            visit(self._tree.topLevelItem(i))
