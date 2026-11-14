"""Palette-based color blending without hard-coded backgrounds."""
from PyQt6.QtGui import QColor


def blend(background: QColor, foreground: QColor, amount: float) -> QColor:
    return QColor(
        round(background.red() * (1. - amount) + foreground.red() * amount),
        round(background.green() * (1. - amount) + foreground.green() * amount),
        round(background.blue() * (1. - amount) + foreground.blue() * amount),
    )


def mixed_color(
    foreground: QColor,
    background: QColor,
    foreground_weight: float,
) -> QColor:
    background_weight = 1.0 - foreground_weight
    return QColor(
        round(
            foreground.red() * foreground_weight
            + background.red() * background_weight
        ),
        round(
            foreground.green() * foreground_weight
            + background.green() * background_weight
        ),
        round(
            foreground.blue() * foreground_weight
            + background.blue() * background_weight
        ),
    )
