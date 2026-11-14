"""Small palette-aware visual primitives shared by application dialogs.

This module defines a visual grammar, not a global theme. Callers still own
their semantic accent colors and layout; these helpers only make tinting,
typographic hierarchy, borders and button states consistent.
"""
from __future__ import annotations

from typing import Literal

from PyQt6.QtGui import QColor, QFont, QPalette

from ase2sprkkr_gui.gui.misc.colors import blend

# A compact spacing scale. Large window-specific margins may combine these.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

PANEL_RADIUS = 6
BORDER_WIDTH = 1
SELECTED_BORDER_WIDTH = 3
ACTION_ACCENT_WIDTH = 6

PANEL_TINT_LIGHT = .08
PANEL_TINT_DARK = .16
NAVIGATION_TINT_LIGHT = .36
NAVIGATION_TINT_DARK = .48
ACCENT_BORDER_MIX = .25
HOVER_TINT_INCREMENT = .10

HeadingLevel = Literal["window", "dialog", "section"]


def is_dark(palette: QPalette) -> bool:
    """Return whether the palette window background is perceptually dark."""
    return palette.color(QPalette.ColorRole.Window).lightness() <= 128


def palette_tint(
    palette: QPalette,
    accent: QColor,
    *,
    light_amount: float,
    dark_amount: float,
    role: QPalette.ColorRole = QPalette.ColorRole.Window,
) -> QColor:
    """Blend an accent into a palette role with theme-appropriate intensity."""
    return blend(
        palette.color(role),
        accent,
        dark_amount if is_dark(palette) else light_amount,
    )


def heading_font(base: QFont, level: HeadingLevel) -> QFont:
    """Return a relative heading font which respects the system base font."""
    font = QFont(base)
    if font.pointSizeF() > 0:
        size = font.pointSizeF()
        target = {
            "window": max(size + 8.0, 24.0),
            "dialog": max(size + 3.0, 14.0),
            "section": size + 1.0,
        }[level]
        font.setPointSizeF(target)
    font.setWeight(QFont.Weight.DemiBold)
    return font


def secondary_text_stylesheet(palette: QPalette) -> str:
    """Style explanatory text from the palette, including dark themes."""
    color = palette.color(QPalette.ColorRole.PlaceholderText)
    return f"color: {color.name()};"


def group_panel_stylesheet(palette: QPalette, accent: QColor) -> str:
    """Return the shared rounded, lightly tinted group-panel appearance."""
    background = palette_tint(
        palette,
        accent,
        light_amount=PANEL_TINT_LIGHT,
        dark_amount=PANEL_TINT_DARK,
    )
    border = blend(
        palette.color(QPalette.ColorRole.Mid), accent, ACCENT_BORDER_MIX
    )
    return (
        "QGroupBox {"
        f"background-color: {background.name()}; "
        f"border: {BORDER_WIDTH}px solid {border.name()}; "
        f"border-radius: {PANEL_RADIUS}px; margin-top: 0.8em; "
        f"padding: {SPACE_SM}px;"
        "} QGroupBox::title {"
        f"subcontrol-origin: margin; left: {SPACE_SM}px; padding: 0 3px;"
        "}"
    )


def navigation_tile_stylesheet(
    palette: QPalette,
    accent: QColor,
    *,
    selected: bool,
) -> str:
    """Style a colored navigation tile while keeping its page identity strong."""
    amount = NAVIGATION_TINT_DARK if is_dark(palette) else NAVIGATION_TINT_LIGHT
    background = blend(palette.color(QPalette.ColorRole.Window), accent, amount)
    hover = blend(
        palette.color(QPalette.ColorRole.Window),
        accent,
        min(amount + HOVER_TINT_INCREMENT, 1.0),
    )
    quiet_border = blend(
        palette.color(QPalette.ColorRole.Mid), accent, ACCENT_BORDER_MIX
    )
    border = accent if selected else quiet_border
    width = SELECTED_BORDER_WIDTH if selected else BORDER_WIDTH
    text = palette.color(QPalette.ColorRole.WindowText)
    return (
        "QLabel {"
        f"background-color: {background.name()}; color: {text.name()}; "
        f"border: {width}px solid {border.name()}; "
        f"border-radius: {PANEL_RADIUS}px;"
        "} QLabel:hover {"
        f"background-color: {hover.name()}; border-color: {accent.name()};"
        "}"
    )


def action_card_stylesheet(
    palette: QPalette,
    accent: QColor,
    selector: str,
    *,
    subtle: bool = False,
) -> str:
    """Return a semantic action-card style with common hover and border rules."""
    amount = .08 if subtle else .22
    background = blend(palette.color(QPalette.ColorRole.Button), accent, amount)
    hover = blend(
        palette.color(QPalette.ColorRole.Button),
        accent,
        min(amount + HOVER_TINT_INCREMENT, 1.0),
    )
    text = palette.color(QPalette.ColorRole.ButtonText)
    return (
        f"{selector} {{ text-align: left; padding: 0; "
        f"color: {text.name()}; background-color: {background.name()}; "
        f"border: {BORDER_WIDTH}px solid {accent.name()}; "
        f"border-left: {ACTION_ACCENT_WIDTH}px solid {accent.name()}; "
        f"border-radius: {PANEL_RADIUS}px; }} "
        f"{selector}:hover {{ color: {text.name()}; "
        f"background-color: {hover.name()}; }}"
    )


def button_stylesheet(
    palette: QPalette,
    selector: str = "QPushButton",
    *,
    primary: bool = False,
) -> str:
    """Return a palette-derived primary or secondary button style."""
    if primary:
        background = palette.color(QPalette.ColorRole.Highlight)
        hover = blend(
            background,
            palette.color(QPalette.ColorRole.HighlightedText),
            .10,
        )
        pressed = blend(background, palette.color(QPalette.ColorRole.Window), .18)
        text = palette.color(QPalette.ColorRole.HighlightedText)
        border = background
    else:
        background = palette.color(QPalette.ColorRole.Button)
        accent = palette.color(QPalette.ColorRole.Highlight)
        hover = blend(background, accent, .10)
        pressed = blend(background, accent, .18)
        text = palette.color(QPalette.ColorRole.ButtonText)
        border = blend(palette.color(QPalette.ColorRole.Mid), accent, .12)
    disabled_background = palette.color(QPalette.ColorRole.Button)
    disabled_text = palette.color(QPalette.ColorRole.PlaceholderText)
    return (
        f"{selector} {{ color: {text.name()}; background-color: {background.name()}; "
        f"border: {BORDER_WIDTH}px solid {border.name()}; "
        f"border-radius: {PANEL_RADIUS}px; padding: {SPACE_XS}px {SPACE_SM}px; }} "
        f"{selector}:hover {{ background-color: {hover.name()}; }} "
        f"{selector}:pressed {{ background-color: {pressed.name()}; }} "
        f"{selector}:disabled {{ color: {disabled_text.name()}; "
        f"background-color: {disabled_background.name()}; }}"
    )
