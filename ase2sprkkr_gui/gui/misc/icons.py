"""Common user-facing icons, with a bundled fallback for minimal Qt themes."""
from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.input_parameters.task_preferences import task_ui_name


def settings_icon() -> QIcon:
    """Use the system settings symbol, never a file-view icon as fallback."""
    return QIcon.fromTheme(
        "preferences-system", QIcon(str(icon_path("settings-cog.svg")))
    )

def application_icon() -> QIcon:
    """Return the bundled, platform-independent SPR-KKR application icon."""
    return QIcon(str(icon_path("sprkkr-orbital.svg")))


def task_icon(task: str) -> QIcon:
    """Use an optional bundled icon named after the canonical native task."""
    from ase2sprkkr_gui.gui.misc.resources import task_icon_path

    path = task_icon_path(task_ui_name(task))
    return QIcon(str(path)) if path is not None else QIcon()


def badge_icon(base: QIcon, kind: Literal["recent", "reconverge", "new"]) -> QIcon:
    """Combine an unchanged object icon with a consistent semantic badge.

    Recent means a previous item, reconverge means rerun SCF from the current
    potential, and new means starting a *different* SCF from that potential.
    The badge is rendered at several resolutions to stay crisp in 24 px bars.
    """
    if base.isNull():
        return base

    decorated = QIcon()
    for size in (24, 32, 48, 64, 96):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(size / 48, size / 48)

        # Use the source image itself, notably the familiar bulk_crystal.png;
        # do not substitute a different symbol for a recent structure.
        painter.drawPixmap(QRect(1, 1, 42, 42), base.pixmap(QSize(42, 42)))

        center = QPointF(36, 36)
        painter.setPen(QPen(QColor("#ffffff"), 3.5))
        painter.setBrush(QColor("#f4fafb"))
        painter.drawEllipse(center, 9.3, 9.3)
        painter.setPen(QPen(QColor("#26384e"), 1.8))
        painter.drawEllipse(center, 9.3, 9.3)

        if kind == "recent":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 5.5, 5.5)
            painter.setPen(QPen(QColor("#26384e"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(36, 32.6), center)
            painter.drawLine(center, QPointF(38.7, 37.5))
        elif kind == "reconverge":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(
                QColor("#087f83"), 2.5, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
            ))
            painter.drawArc(QRectF(30.6, 30.6, 10.8, 10.8), 115 * 16, 285 * 16)
            painter.drawLine(QPointF(40.5, 31.6), QPointF(42.3, 31.5))
            painter.drawLine(QPointF(40.5, 31.6), QPointF(41.0, 34.0))
        elif kind == "new":
            painter.setPen(QPen(
                QColor("#087f83"), 3, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            ))
            painter.drawLine(QPointF(36, 31.3), QPointF(36, 40.7))
            painter.drawLine(QPointF(31.3, 36), QPointF(40.7, 36))
        else:
            raise ValueError(f"Unknown icon badge: {kind}")

        painter.end()
        decorated.addPixmap(pixmap)

    return decorated
