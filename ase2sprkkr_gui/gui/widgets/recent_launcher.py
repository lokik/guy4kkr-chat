"""Qt rendering helpers for recently used structures and outputs."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget

from ase2sprkkr_gui.gui import recent_presentation as _recent


def _populate_menu_items(
    menu: QMenu,
    items: tuple[_recent.RecentMenuItem, ...],
    open_recent: Callable[[str], None],
    *,
    empty_text: str = _recent.RECENT_MENU_EMPTY_TEXT,
) -> QMenu:
    menu.clear()
    if not items:
        action = QAction(empty_text, menu)
        action.setEnabled(False)
        menu.addAction(action)
        return menu

    for item in items:
        action = QAction(item.label, menu)
        action.setToolTip(item.tooltip)
        action.triggered.connect(
            lambda _checked=False, item_path=item.path: open_recent(item_path)
        )
        menu.addAction(action)
    return menu


def populate_recent_menu(
    menu: QMenu,
    snapshot: _recent.RecentHistorySnapshot,
    kind: _recent.RecentFileKind,
    open_recent: Callable[[str], None],
    *,
    base: str | Path | None = None,
) -> QMenu:
    """Populate one recent-file menu from one captured history snapshot."""
    return _populate_menu_items(
        menu,
        _recent.recent_menu_items(snapshot.paths(kind), base=base),
        open_recent,
    )


def build_recent_launch_menu(
    parent: QWidget,
    presentation: _recent.RecentLaunchPresentation,
    open_recent: Callable[[_recent.RecentLaunchKind, str], None],
    *,
    menu: QMenu | None = None,
) -> QMenu:
    """Render an already-resolved shared Continue-recent presentation.

    Reuse existing submenus when refreshing. ``QMenu.clear()`` removes their
    actions but does not destroy child menu objects immediately, so recreating
    the submenus on every history update would retain an ever-growing set of
    QObject children on the long-lived parent menu.
    """
    if menu is None and isinstance(parent, QToolButton):
        menu = parent.menu()
    if menu is None:
        menu = QMenu(parent)

    existing_submenus = {
        submenu.title(): submenu
        for action in menu.actions()
        if (submenu := action.menu()) is not None
    }
    menu.clear()

    for group in presentation.groups:
        submenu = existing_submenus.pop(group.title, None)
        if submenu is None:
            submenu = QMenu(group.title, menu)
        _populate_menu_items(
            submenu,
            group.items,
            lambda path, item_kind=group.kind: open_recent(item_kind, path),
            empty_text=group.empty_text,
        )
        menu.addMenu(submenu)

    for obsolete in existing_submenus.values():
        obsolete.deleteLater()
    return menu
