"""GUI helpers for revision-sensitive document changes."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.workspace_controller import DocumentChange


def document_change_applied(parent: QWidget, change: DocumentChange) -> bool:
    """Explain an unresolved stale change at the GUI workflow boundary."""
    if change is DocumentChange.APPLIED:
        return True
    if change is DocumentChange.CANCELLED:
        # The injected conflict resolver already asked the user and they declined.
        return False
    QMessageBox.information(
        parent,
        "Document Changed",
        "The document changed before this operation could be applied. "
        "The stale changes were discarded.",
    )
    return False
