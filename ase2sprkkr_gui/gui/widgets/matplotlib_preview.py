"""Expandable Matplotlib previews shared by structure-related GUI widgets.

A fullscreen dialog gets its own figure: a preview must retain its Qt parent,
mouse callbacks and editable state while the user inspects a larger view.
"""
from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
import pickle

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from matplotlib.image import imread
from PyQt6.QtCore import Qt, QSize, QPointF
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton, QToolButton, QVBoxLayout, QWidget,
)


def _fullscreen_figure(figure: Figure) -> Figure:
    """Clone plotted artists and 3D axes, without moving the original canvas."""
    try:
        return pickle.loads(pickle.dumps(figure, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        # Custom Matplotlib artists can contain non-pickleable state. The
        # preview must still expand, albeit as a non-interactive image.
        image = BytesIO()
        figure.savefig(image, format="png", dpi=max(150, figure.dpi))
        image.seek(0)
        snapshot = Figure(figsize=figure.get_size_inches())
        axes = snapshot.add_axes((0, 0, 1, 1))
        axes.imshow(imread(image, format="png"))
        axes.set_axis_off()
        return snapshot


def _fullscreen_icon() -> QIcon:
    """A small black expand symbol, legible on both dark and light plots."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#171717"))
    pen.setWidthF(1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    # Four diagonal arrows pointing outwards, not a square outline.
    for dx in (-1, 1):
        for dy in (-1, 1):
            tip = QPointF(9 + dx * 6, 9 + dy * 6)
            painter.drawLine(QPointF(9 + dx * 2, 9 + dy * 2), tip)
            painter.drawLine(tip, QPointF(tip.x() - dx * 3.5, tip.y()))
            painter.drawLine(tip, QPointF(tip.x(), tip.y() - dy * 3.5))
    painter.end()
    return QIcon(pixmap)


class _FullscreenWidgetDialog(QDialog):
    """Modal window holding an independently interactive preview widget."""

    def __init__(self, viewer: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Matplotlib preview")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)
        self.controls = QHBoxLayout()
        self.controls.addStretch(1)
        close_button = QPushButton("Close (Esc)", self)
        close_button.clicked.connect(self.reject)
        self.controls.addWidget(close_button)
        layout.addLayout(self.controls)
        layout.addWidget(viewer, 1)

        self._close_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._close_shortcut.activated.connect(self.reject)
        viewer.setFocus()


class _FullscreenFigureDialog(_FullscreenWidgetDialog):
    """Ordinary Matplotlib figures use native 2D/3D navigation controls."""

    def __init__(self, figure: Figure, parent: QWidget | None = None) -> None:
        self.canvas = FigureCanvasQTAgg(figure)
        super().__init__(self.canvas, parent)
        self.controls.insertWidget(0, NavigationToolbar2QT(self.canvas, self))
        self.canvas.setFocus()


class PreviewFigureCanvas(FigureCanvasQTAgg):
    """Matplotlib canvas with a fullscreen button and double-click shortcut."""

    def __init__(self, figure: Figure) -> None:
        super().__init__(figure)
        # Custom previews can provide a fresh, interactive viewer instead of
        # cloning artists (which loses their own Matplotlib event handlers).
        self.fullscreen_factory: Callable[[], QWidget] | None = None
        self._fullscreen_enabled = True

        self.fullscreen_button = QToolButton(self)
        self.fullscreen_button.setObjectName("previewFullscreenButton")
        self.fullscreen_button.setToolTip("Open fullscreen preview")
        self.fullscreen_button.setAccessibleName("Open fullscreen preview")
        self.fullscreen_button.setIcon(_fullscreen_icon())
        self.fullscreen_button.setIconSize(QSize(16, 16))
        self.fullscreen_button.setFixedSize(24, 24)
        self.fullscreen_button.setStyleSheet(
            "QToolButton { background-color: rgba(248, 248, 248, 210);"
            " border: none; border-radius: 3px; padding: 0; }"
            "QToolButton:hover { background-color: white; }"
        )
        self.fullscreen_button.clicked.connect(self.open_fullscreen)
        self.fullscreen_button.move(6, 6)
        self.fullscreen_button.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "fullscreen_button"):
            self.fullscreen_button.move(6, 6)

    def set_fullscreen_enabled(self, enabled: bool) -> None:
        """Hide fullscreen affordances in an already-expanded preview."""
        self._fullscreen_enabled = bool(enabled)
        self.fullscreen_button.setVisible(self._fullscreen_enabled)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._fullscreen_enabled and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.open_fullscreen()
            return
        super().mouseDoubleClickEvent(event)

    def open_fullscreen(self) -> None:
        if not self._fullscreen_enabled:
            return
        dialog = (
            _FullscreenWidgetDialog(self.fullscreen_factory(), self.window())
            if self.fullscreen_factory is not None
            else _FullscreenFigureDialog(_fullscreen_figure(self.figure), self.window())
        )
        dialog.showFullScreen()
        dialog.exec()
