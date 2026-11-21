"""Buttons with consistently centered icons and bounded, wrapped labels."""
from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPalette
from PyQt6.QtWidgets import (
    QPushButton, QStyle, QStyleOptionButton, QStyleOptionToolButton,
    QStylePainter, QToolButton,
)


def _wrap_title(text: str, metrics: QFontMetrics, width: int) -> list[str]:
    """Wrap an action title to at most two lines, eliding the last one."""
    words = text.split()
    if not words:
        return []
    lines = []
    while words and len(lines) < 2:
        line = words.pop(0)
        while words and metrics.horizontalAdvance(line + " " + words[0]) <= width:
            line += " " + words.pop(0)
        if words and len(lines) == 1:
            line += " " + " ".join(words)
            words.clear()
        lines.append(metrics.elidedText(line, Qt.TextElideMode.ElideRight, width))
    return lines


def _wrap_header_title(text: str, metrics: QFontMetrics, width: int) -> list[str]:
    """Split a command into two balanced lines, even if it fits on one."""
    words = text.split()
    if len(words) < 2:
        return [metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)] if text else []
    options = []
    for split in range(1, len(words)):
        left, right = " ".join(words[:split]), " ".join(words[split:])
        a, b = metrics.horizontalAdvance(left), metrics.horizontalAdvance(right)
        options.append((
            (max(0, max(a, b) - width), abs(a - b), max(a, b)),
            (left, right),
        ))
    _, lines = min(options, key=lambda candidate: candidate[0])
    return [
        metrics.elidedText(line, Qt.TextElideMode.ElideRight, width)
        for line in lines
    ]


def _draw_content(
    painter, button, rect: QRect, *, under: bool = False,
    two_line: bool = False,
) -> None:
    """Paint inside the clickable rect, never into the split-menu arrow."""
    # Reclaim the 2px top/bottom padding for stacked header labels.
    # Horizontal padding still protects text from the split-menu arrow.
    bounds = rect.adjusted(7, 0 if two_line else 4, -7, 0 if two_line else -4)
    if bounds.width() <= 0 or bounds.height() <= 0:
        return
    icon = button.icon().pixmap(
        button.iconSize(),
        QIcon.Mode.Normal if button.isEnabled() else QIcon.Mode.Disabled,
    )
    ratio = max(1.0, icon.devicePixelRatioF())
    iw, ih = round(icon.width() / ratio), round(icon.height() / ratio)
    text = (
        "" if isinstance(button, QToolButton)
        and button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        else button.text()
    )
    title, *remainder = text.split("\n", 1)
    filename = remainder[0] if remainder else ""
    enabled_role = (
        QPalette.ColorRole.ButtonText if button.isEnabled()
        else QPalette.ColorRole.PlaceholderText
    )
    painter.save()
    painter.setClipRect(bounds)
    painter.setPen(button.palette().color(enabled_role))
    try:
        if not title:
            painter.drawPixmap(
                bounds.center().x() - iw // 2,
                bounds.center().y() - ih // 2, icon,
            )
            return

        base_font = button.font()
        if under and two_line:
            # Reserve both text rows even for a one-line command. Otherwise
            # centering each variable-height block makes icons jump vertically
            # when a recent filename is shown or a long title wraps.
            title_font = QFont(base_font)
            title_font.setWeight(QFont.Weight.DemiBold)
            file_font = QFont(base_font)
            file_font.setPointSizeF(max(7.0, base_font.pointSizeF() * .85))
            title_metrics = QFontMetrics(title_font)
            file_metrics = QFontMetrics(file_font)
            row_height = title_metrics.height()
            total_height = ih + 2 * row_height
            if total_height > bounds.height():
                # Keep the icon size, but allow the text to adapt to a large
                # system font within the fixed-height navigation button.
                title_font.setPointSizeF(max(7.0, base_font.pointSizeF() * .9))
                file_font.setPointSizeF(max(7.0, base_font.pointSizeF() * .8))
                title_metrics = QFontMetrics(title_font)
                file_metrics = QFontMetrics(file_font)
                row_height = title_metrics.height()
                total_height = ih + 2 * row_height

            icon_y = bounds.top() + max(0, (bounds.height() - total_height) // 2)
            painter.drawPixmap(bounds.center().x() - iw // 2, icon_y, icon)
            text_y = icon_y + ih
            title_lines = (
                [title_metrics.elidedText(
                    title, Qt.TextElideMode.ElideRight, bounds.width(),
                )] if filename else
                _wrap_header_title(title, title_metrics, bounds.width())
            )
            painter.setFont(title_font)
            for row, line in enumerate(title_lines):
                painter.drawText(
                    QRect(bounds.left(), text_y + row * row_height,
                          bounds.width(), row_height),
                    Qt.AlignmentFlag.AlignCenter, line,
                )
            if filename:
                # A lighter, smaller filename is secondary to the command,
                # with the same second-row baseline across recent buttons.
                file_y = text_y + row_height + max(
                    0, (row_height - file_metrics.height()) // 2,
                )
                if button.isEnabled():
                    foreground = button.palette().color(enabled_role)
                    background = button.palette().color(QPalette.ColorRole.Button)
                    painter.setPen(QColor(
                        round(.76 * foreground.red() + .24 * background.red()),
                        round(.76 * foreground.green() + .24 * background.green()),
                        round(.76 * foreground.blue() + .24 * background.blue()),
                    ))
                painter.setFont(file_font)
                painter.drawText(
                    QRect(bounds.left(), file_y, bounds.width(),
                          file_metrics.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    file_metrics.elidedText(
                        filename, Qt.TextElideMode.ElideLeft, bounds.width(),
                    ),
                )
            return

        if under:
            metrics = QFontMetrics(base_font)
            label = metrics.elidedText(
                title, Qt.TextElideMode.ElideRight, bounds.width(),
            )
            block_height = ih + 4 + metrics.height()
            y = bounds.center().y() - block_height // 2
            painter.drawPixmap(bounds.center().x() - iw // 2, y, icon)
            painter.drawText(
                QRect(bounds.left(), y + ih + 4, bounds.width(), metrics.height()),
                Qt.AlignmentFlag.AlignCenter, label,
            )
            return

        title_font = QFont(base_font)
        title_font.setBold(True)
        title_metrics = QFontMetrics(title_font)
        small_font = QFont(base_font)
        small_font.setPointSizeF(max(7.0, base_font.pointSizeF() * .90))
        small_metrics = QFontMetrics(small_font)

        # Align all labeled toolbar icons to a fixed left inset instead of
        # centering the icon and variable-length text as a group.
        # Only the main subcontrol is available; never paint into an arrow.
        icon_x = bounds.left() + 5
        text_x = icon_x + iw + 10
        width = max(1, bounds.right() - text_x + 1)
        title_lines = _wrap_title(title, title_metrics, width)
        file_label = (
            small_metrics.elidedText(
                filename, Qt.TextElideMode.ElideLeft, width,
            ) if filename else ""
        )
        title_h = len(title_lines) * title_metrics.height()
        file_h = small_metrics.height() if filename else 0
        block_h = title_h + file_h
        top = bounds.center().y() - block_h // 2

        # Align the icon vertically with the text block.
        painter.drawPixmap(
            icon_x, bounds.center().y() - ih // 2, icon,
        )
        painter.setFont(title_font)
        for i, line in enumerate(title_lines):
            painter.drawText(
                QRect(text_x, top + i * title_metrics.height(),
                      width, title_metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )
        if filename:
            painter.setFont(small_font)
            painter.drawText(
                QRect(text_x, top + title_h, width, file_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                file_label,
            )
    finally:
        painter.restore()


class CenteredIconToolButton(QToolButton):
    """Toolbutton with a centered icon in labeled, compact and split modes."""

    def paintEvent(self, event) -> None:
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        option.text = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        main_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ToolButton, option,
            QStyle.SubControl.SC_ToolButton, self,
        )
        if self.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup:
            menu_rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_ToolButton, option,
                QStyle.SubControl.SC_ToolButtonMenu, self,
            )
            if menu_rect.isValid() and menu_rect.left() > main_rect.left():
                main_rect.setRight(min(main_rect.right(), menu_rect.left() - 1))
        two_line = bool(self.property("twoLineUnderIcon"))
        if two_line:
            # A theme may inset the style subcontrol by a few pixels; use
            # the full button height while retaining its menu-free width.
            main_rect.setTop(self.rect().top())
            main_rect.setBottom(self.rect().bottom())
        _draw_content(
            painter, self, main_rect,
            under=self.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
            two_line=two_line,
        )


class CenteredIconPushButton(QPushButton):
    """Pushbutton with the same icon/text positioning as the toolbuttons."""

    def paintEvent(self, event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        content_rect = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self,
        )
        two_line = bool(self.property("twoLineUnderIcon"))
        if two_line:
            content_rect.setTop(self.rect().top())
            content_rect.setBottom(self.rect().bottom())
        _draw_content(
            painter, self, content_rect, under=two_line, two_line=two_line,
        )
