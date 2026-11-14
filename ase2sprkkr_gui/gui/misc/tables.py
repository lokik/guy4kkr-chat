"""Sizing shared by compact parameter tables."""

from PyQt6.QtCore import Qt


def fit_table_height(table, maximum_rows=8):
    """Fit actual rows and the header; scroll only when the row limit is exceeded."""
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    height = 2 * table.frameWidth()
    if not table.horizontalHeader().isHidden():
        height += table.horizontalHeader().sizeHint().height()
    height += sum(table.rowHeight(row) for row in range(min(table.rowCount(), maximum_rows)))
    table.setFixedHeight(height)
