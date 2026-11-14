"""Reusable Guided-style action cards."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui import presentation as _presentation
from ase2sprkkr_gui.gui.style import (
    SPACE_LG,
    SPACE_SM,
    action_card_stylesheet,
    heading_font,
)


def action_card_accent(
    palette: QPalette,
    category: _presentation.ActionCategory,
) -> QColor:
    """Return the semantic accent used by Guided action cards."""
    return {
        "structure": QColor("#3979b8"),
        "load": QColor("#527f9f"),
        "calculation": QColor("#398552"),
        "destructive": QColor("#b34444"),
        "neutral": palette.color(QPalette.ColorRole.Mid),
    }[category]


def configure_action_card(
    button: QAbstractButton,
    title: str,
    description: str,
    icon: QIcon,
    *,
    category: _presentation.ActionCategory = "structure",
    icon_size: QSize | None = None,
    minimum_height: int = 68,
    menu_button: bool = False,
    subtle: bool = False,
) -> None:
    """Give a push/tool button the same visual treatment as Guided actions."""
    if icon_size is None:
        icon_size = QSize(26, 26)

    button.setText("")
    button.setProperty("workflowActionTitle", title)
    button.setAccessibleName(title)
    button.setAccessibleDescription(description)
    button.setMinimumHeight(minimum_height)
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    button.setCursor(Qt.CursorShape.PointingHandCursor)

    layout = QHBoxLayout(button)
    layout.setContentsMargins(
        SPACE_LG, SPACE_SM, 34 if menu_button else SPACE_LG, SPACE_SM
    )
    layout.setSpacing(SPACE_LG)

    icon_label = QLabel(button)
    icon_label.setFixedSize(icon_size)
    icon_label.setPixmap(icon.pixmap(icon_size))
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout.addWidget(icon_label)

    text_widget = QWidget(button)
    text_layout = QVBoxLayout(text_widget)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)

    title_label = QLabel(title, text_widget)
    title_label.setForegroundRole(QPalette.ColorRole.ButtonText)
    title_label.setFont(heading_font(title_label.font(), "section"))
    title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    text_layout.addWidget(title_label)

    if description:
        description_label = QLabel(description, text_widget)
        description_label.setForegroundRole(QPalette.ColorRole.ButtonText)
        description_label.setWordWrap(True)
        description_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        text_layout.addWidget(description_label)

    text_widget.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    text_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout.addWidget(text_widget, 1)

    selector = "QToolButton" if isinstance(button, QToolButton) else "QPushButton"
    button.setStyleSheet(
        action_card_stylesheet(
            button.palette(),
            action_card_accent(button.palette(), category),
            selector,
            subtle=subtle,
        )
    )
