"""Transactional text editing of a task's SPRKKR input file."""
import re
from io import StringIO

from pyparsing import ParseBaseException
from PyQt6.QtGui import QFontDatabase, QTextCursor, QTextFormat
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
)


class InputFileEditor(QDialog):
    """Only publish a new parameter object after successful parsing on OK.

    ``apply_parameters(candidate)`` is an optional caller-supplied application
    callback. Input-file parsing/validation errors keep the draft open; callback
    failures are programming errors and are not presented as text-file errors.
    This editor has no dependency on either the guided session or the expert tree.
    """

    def __init__(self, parameters, parent=None, *, apply_parameters=None):
        super().__init__(parent)
        self._parameters = parameters
        self._apply_parameters = apply_parameters
        self.parameters = None
        self.error_line = None
        self.setWindowTitle(f"Edit {parameters.task_name.upper()} input file")
        self.resize(850, 700)
        layout = QVBoxLayout(self)
        hint = QLabel("Edit the generated input for this task. OK parses and applies it; Cancel discards edits. "
                      "Comments and formatting are not retained when the input is regenerated.", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.editor = QPlainTextEdit(self)
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlainText(parameters.to_string(validate=False))
        self.editor.textChanged.connect(self._clear_error)
        layout.addWidget(self.editor, 1)
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _clear_error(self):
        self.error_line = None
        self.editor.setExtraSelections([])
        self.error_label.clear()
        self.error_label.hide()

    def accept(self):
        """Parse a candidate, then publish it through the application callback."""
        self._clear_error()
        try:
            # Autodetect only the IPD selected by the native TASK declaration.
            # Parsing through the old instance could silently accept another
            # task's text as the current task.
            candidate = type(self._parameters).from_file(
                StringIO(self.editor.toPlainText())
            )
            expected = self._parameters.definition_name
            actual = candidate.definition_name
            if actual.casefold() != expected.casefold():
                raise ValueError(
                    f"Expected {expected.upper()} input-parameter schema, "
                    f"got {actual.upper()}."
                )
        except Exception as error:
            self._show_error(error)
            return

        if self._apply_parameters is not None:
            self._apply_parameters(candidate)
        self.parameters = candidate
        super().accept()

    def _semantic_error_line(self, error):
        """Best-effort location for semantic input errors without parser offsets."""
        message = str(error)
        names = re.findall(r"(?:option|parameter|member|section)\s+(?:named\s+)?['\"`]?([\w]+(?:\.[\w]+)*)",
                           message, re.IGNORECASE)
        names += re.findall(r"['\"`]([A-Za-z_]\w*(?:\.\w+)*)['\"`]", message)
        lines = self.editor.toPlainText().splitlines()
        for path in names:
            parts = path.split('.')
            section = parts[-2].upper() if len(parts) > 1 else None
            active_section = None
            token = re.compile(rf"(?<![\w]){re.escape(parts[-1])}(?=\s*(?:=|$))", re.IGNORECASE)
            for number, line in enumerate(lines, 1):
                # Remove comments and quoted values before looking for names.
                code = re.sub(r"'[^']*'|\"[^\"]*\"|#.*$", "", line)
                header = re.match(r"^([A-Za-z_]\w*)\b", code)
                if header:
                    active_section = header.group(1).upper()
                if (section is None or section == active_section) and token.search(code):
                    return number
        return None

    def _show_error(self, error):
        """Locate a chained parser error, or heuristically highlight a semantic error.

        Highlight a whole line: pyparsing expands tabs, so its column is not a
        reliable Qt document offset. Errors without a location still stay open.
        """
        parser_error = error
        seen = set()
        while not isinstance(parser_error, ParseBaseException) and id(parser_error) not in seen:
            seen.add(id(parser_error))
            parser_error = parser_error.__cause__ or parser_error.__context__
            if parser_error is None:
                break
        message = str(error)
        located_parse_error = isinstance(parser_error, ParseBaseException) and parser_error.pstr
        self.error_line = parser_error.lineno if located_parse_error else self._semantic_error_line(error)
        if self.error_line is not None:
            block = self.editor.document().findBlockByNumber(self.error_line - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                # pyparsing expands tabs, so its column cannot be used directly
                # as a document offset. Highlight the whole suspected line.
                self.editor.setTextCursor(cursor)
                self.editor.ensureCursorVisible()
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                color = self.palette().highlight().color()
                color.setAlpha(90)
                selection.format.setBackground(color)
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                self.editor.setExtraSelections([selection])
            column = f", column {parser_error.col}" if located_parse_error else ""
            message = f"Suspected location: line {self.error_line}{column}.\n{message}"
        self.error_label.setText(message)
        self.error_label.show()
        self.editor.setFocus()
