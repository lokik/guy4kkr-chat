"""Persistent, screen-safe geometry for top-level GUI windows."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PyQt6.QtGui import QGuiApplication, QScreen
from PyQt6.QtWidgets import QWidget

from ase2sprkkr_gui.gui.application.atomic_io import atomic_write_json
from ase2sprkkr_gui.gui.application.config import config_home

_WINDOW_ID_PROPERTY = "_ase2sprkkr_gui_window_geometry_id"
_DEFAULT_STORE_OBJECT_NAME = "_ase2sprkkr_gui_window_geometry_store"


@dataclass(frozen=True)
class WindowPlacement:
    """Geometry and state to use when a window is first shown."""

    geometry: QRect
    maximized: bool


@dataclass(frozen=True)
class _SavedWindowState:
    geometry: QRect
    maximized: bool
    screen: str | None = None


def default_window_geometry_path() -> Path:
    """Return the per-user path used for persisted window geometry."""
    return config_home() / "window_geometry.json"


def _intersection_area(first: QRect, second: QRect) -> int:
    intersection = first.intersected(second)
    if intersection.isEmpty():
        return 0
    return intersection.width() * intersection.height()


def adjust_window_geometry(
    geometry: QRect,
    available: QRect,
    *,
    center_if_outside: bool = False,
) -> QRect:
    """Fit *geometry* completely inside one screen's available rectangle."""
    width = min(max(1, geometry.width()), max(1, available.width()))
    height = min(max(1, geometry.height()), max(1, available.height()))

    if center_if_outside and _intersection_area(geometry, available) == 0:
        x = available.x() + (available.width() - width) // 2
        y = available.y() + (available.height() - height) // 2
        return QRect(x, y, width, height)

    max_x = available.right() - width + 1
    max_y = available.bottom() - height + 1
    x = min(max(geometry.x(), available.left()), max_x)
    y = min(max(geometry.y(), available.top()), max_y)
    return QRect(x, y, width, height)


def restore_window_geometry(
    geometry: QRect,
    available: QRect,
    *,
    default_size: QSize,
    center_if_outside: bool = False,
) -> QRect:
    """Restore saved geometry, replacing implausibly small sizes with the default."""
    minimum_width = max(
        1, min(max(1, default_size.width() // 2), max(1, available.width() // 4))
    )
    minimum_height = max(
        1, min(max(1, default_size.height() // 2), max(1, available.height() // 4))
    )
    was_outside = _intersection_area(geometry, available) == 0
    restored = QRect(geometry)
    if restored.width() < minimum_width or restored.height() < minimum_height:
        restored.setSize(default_size)
    if center_if_outside and was_outside:
        restored.moveCenter(available.center())
    return adjust_window_geometry(restored, available)


class WindowGeometryStore(QObject):
    """Load, apply, track and persist geometry for registered windows."""

    def __init__(
        self,
        path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path or default_window_geometry_path()
        self._states: dict[str, _SavedWindowState] = {}
        self.load()
        app = QGuiApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.save)

    def load(self) -> None:
        """Load saved geometry; missing or corrupt files behave as empty."""
        self._states.clear()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        windows = data.get("windows")
        if not isinstance(windows, dict):
            return
        for window_id, value in windows.items():
            state = self._decode_state(value)
            if isinstance(window_id, str) and state is not None:
                self._states[window_id] = state

    def save(self) -> bool:
        """Persist all known window states."""
        data = {
            "windows": {
                window_id: {
                    "x": state.geometry.x(),
                    "y": state.geometry.y(),
                    "width": state.geometry.width(),
                    "height": state.geometry.height(),
                    "maximized": state.maximized,
                    "screen": state.screen,
                }
                for window_id, state in sorted(self._states.items())
            }
        }
        try:
            atomic_write_json(self.path, data)
        except OSError:
            return False
        return True

    def placement(
        self,
        window: QWidget,
        window_id: str,
        *,
        default_size: QSize | tuple[int, int],
        default_maximized: bool = False,
    ) -> WindowPlacement:
        """Return a saved/default placement adjusted to currently available screens."""
        default = self._size(default_size)
        saved = self._states.get(window_id)
        if saved is None:
            screen = self._fallback_screen(window)
            if screen is None:
                return WindowPlacement(
                    QRect(0, 0, default.width(), default.height()),
                    default_maximized,
                )
            available = screen.availableGeometry()
            geometry = QRect(0, 0, default.width(), default.height())
            geometry.moveCenter(available.center())
            return WindowPlacement(
                adjust_window_geometry(geometry, available),
                default_maximized,
            )

        screen = self._screen_for_saved_state(window, saved)
        if screen is None:
            return WindowPlacement(saved.geometry, saved.maximized)
        available = screen.availableGeometry()
        geometry = restore_window_geometry(
            saved.geometry,
            available,
            default_size=default,
            center_if_outside=_intersection_area(saved.geometry, available) == 0,
        )
        return WindowPlacement(geometry, saved.maximized)

    def manage(
        self,
        window: QWidget,
        window_id: str,
        *,
        default_size: QSize | tuple[int, int],
        default_maximized: bool = False,
    ) -> WindowPlacement:
        """Restore a window and start tracking it for later persistence."""
        placement = self.placement(
            window,
            window_id,
            default_size=default_size,
            default_maximized=default_maximized,
        )
        window.setGeometry(placement.geometry)
        if placement.maximized:
            window.setWindowState(
                window.windowState() | Qt.WindowState.WindowMaximized
            )
        setattr(window, _WINDOW_ID_PROPERTY, window_id)
        window.installEventFilter(self)
        return placement

    def eventFilter(  # noqa: N802 - Qt API
        self, watched: QObject, event: QEvent
    ) -> bool:
        window_id = getattr(watched, _WINDOW_ID_PROPERTY, None)
        if isinstance(watched, QWidget) and isinstance(window_id, str):
            event_type = event.type()
            if event_type in {
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.WindowStateChange,
            }:
                self._capture(watched, window_id)
            elif event_type in {QEvent.Type.Hide, QEvent.Type.Close}:
                self._capture(watched, window_id)
                self.save()
        return False

    def _capture(self, window: QWidget, window_id: str) -> None:
        state = window.windowState()
        if state & Qt.WindowState.WindowMinimized:
            return
        maximized = bool(state & Qt.WindowState.WindowMaximized)
        geometry = window.normalGeometry() if maximized else window.geometry()
        if not geometry.isValid() or geometry.width() <= 0 or geometry.height() <= 0:
            return
        screen = window.screen()
        self._states[window_id] = _SavedWindowState(
            QRect(geometry),
            maximized,
            screen.name() if screen is not None else None,
        )

    def _screen_for_saved_state(
        self,
        window: QWidget,
        saved: _SavedWindowState,
    ) -> QScreen | None:
        screens = list(QGuiApplication.screens())
        if not screens:
            return None

        if saved.screen:
            named = next(
                (screen for screen in screens if screen.name() == saved.screen),
                None,
            )
            if named is not None:
                return named

        overlapping = max(
            screens,
            key=lambda screen: _intersection_area(
                saved.geometry, screen.availableGeometry()
            ),
        )
        if _intersection_area(saved.geometry, overlapping.availableGeometry()) > 0:
            return overlapping
        return self._fallback_screen(window)

    @staticmethod
    def _fallback_screen(window: QWidget) -> QScreen | None:
        parent = window.parentWidget()
        if parent is not None and parent.screen() is not None:
            return parent.screen()
        screen = window.screen()
        if screen is not None:
            return screen
        return QGuiApplication.primaryScreen()

    @staticmethod
    def _size(value: QSize | tuple[int, int]) -> QSize:
        if isinstance(value, QSize):
            return QSize(value)
        width, height = value
        return QSize(int(width), int(height))

    @staticmethod
    def _decode_state(value: Any) -> _SavedWindowState | None:
        if not isinstance(value, dict):
            return None
        try:
            x = int(value["x"])
            y = int(value["y"])
            width = int(value["width"])
            height = int(value["height"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if width <= 0 or height <= 0:
            return None
        maximized = value.get("maximized", False)
        if not isinstance(maximized, bool):
            maximized = False
        screen = value.get("screen")
        if not isinstance(screen, str) or not screen:
            screen = None
        return _SavedWindowState(
            QRect(x, y, width, height),
            maximized,
            screen,
        )


def window_geometry_store() -> WindowGeometryStore:
    """Return the store owned by the current GUI application."""
    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("window geometry requires an active QGuiApplication")

    store = app.findChild(WindowGeometryStore, _DEFAULT_STORE_OBJECT_NAME)
    if store is None:
        store = WindowGeometryStore(parent=app)
        store.setObjectName(_DEFAULT_STORE_OBJECT_NAME)
    return store


def window_placement(
    window: QWidget,
    window_id: str,
    *,
    default_size: QSize | tuple[int, int],
    default_maximized: bool = False,
) -> WindowPlacement:
    """Return screen-safe placement for *window_id* without applying it."""
    return window_geometry_store().placement(
        window,
        window_id,
        default_size=default_size,
        default_maximized=default_maximized,
    )


def manage_window_geometry(
    window: QWidget,
    window_id: str,
    *,
    default_size: QSize | tuple[int, int],
    default_maximized: bool = False,
) -> WindowPlacement:
    """Restore, track and later persist a top-level window's geometry."""
    return window_geometry_store().manage(
        window,
        window_id,
        default_size=default_size,
        default_maximized=default_maximized,
    )
