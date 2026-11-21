"""Undoable draft transactions, independent of the embedding dialog's views."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from ase2sprkkr_gui.ase.embedding import EmbeddingDraft, EmbeddingDraftState


class _DraftEdit(QUndoCommand):
    def __init__(self, stack, before, after, text, merge_key):
        super().__init__(text)
        self.stack = stack
        self.before = before
        self.after = after
        self.merge_key = merge_key
        self._first_redo = True

    def id(self):
        return 1 if self.merge_key is not None else -1

    def mergeWith(self, other):
        if not isinstance(other, _DraftEdit) or self.merge_key != other.merge_key:
            return False
        self.after = other.after
        self.setObsolete(self.before == self.after)
        return True

    def undo(self):
        self.stack.restore(self.before)

    def redo(self):
        # apply() already ran and validated the first edit. QUndoStack.push()
        # calls redo too; only an actual redo should replace the live controls.
        if not self._first_redo:
            self.stack.restore(self.after)
        self._first_redo = False


class EmbeddingUndoStack(QUndoStack):
    """Record atomic edits and merge only within an explicit editing visit.

    Snapshots contain just cluster entries and the physical centre. They are
    never installed by reference, so edits after undo cannot corrupt redo.
    """

    stateRestored = pyqtSignal()

    def __init__(self, draft: EmbeddingDraft, parent=None):
        super().__init__(parent)
        self.draft = draft
        self._visit = 0
        self.setUndoLimit(100)

    def end_edit(self):
        self._visit += 1

    def edit_key(self, context):
        return self._visit, context

    def last_edit_matches(self, key):
        return (key is not None and self.canUndo()
                and self.command(self.index() - 1).merge_key == key)

    def apply(self, operation, text, *, merge_key=None):
        if merge_key is None:
            self.end_edit()
        before = self.draft.snapshot()
        try:
            operation()
        except Exception:
            self.draft.restore(before)
            raise
        after = self.draft.snapshot()
        if before == after:
            return False
        self.push(_DraftEdit(self, before, after, text, merge_key))
        return True

    def restore(self, state: EmbeddingDraftState):
        self.draft.restore(state)
        self.end_edit()
        self.stateRestored.emit()
