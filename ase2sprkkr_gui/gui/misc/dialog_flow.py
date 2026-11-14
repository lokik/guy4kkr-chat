"""Compose simple linear wizard dialogs."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


class DialogAction(str, Enum):
    """Navigation actions returned by dialog wrapper functions."""

    BACK = "back"


def chain_dialogs(
    *dialogs: Callable[..., Any],
    parent: QWidget | None = None,
) -> Any | None:
    """Run a linear wizard and return its final value.

    The first dialog is called with ``parent``. Each following dialog receives
    the previous step's result as its first argument, plus ``parent`` and
    ``back=True``. ``None`` cancels the whole wizard and
    :attr:`DialogAction.BACK` returns to the previous step.
    """
    history: list[Any] = []
    step = 0

    while step < len(dialogs):
        dialog = dialogs[step]
        if step == 0:
            result = dialog(parent=parent)
        else:
            result = dialog(history[step - 1], parent=parent, back=True)

        if result is None:
            return None
        if result == DialogAction.BACK:
            if step == 0:
                return None
            step -= 1
            continue

        if step < len(history):
            history[step] = result
        else:
            history.append(result)
        step += 1

    return history[-1] if history else None
