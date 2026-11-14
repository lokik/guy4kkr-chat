"""Persistent command history for the structure-creation Python console."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import platformdirs

from ase2sprkkr_gui.gui.application.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)


def default_shell_history_path() -> Path:
    """Use an OS-specific per-user state directory on Windows, macOS and Linux."""
    return Path(
        platformdirs.user_state_dir("ase2sprkkr_gui", appauthor="ase2sprkkr")
    ) / "python_shell_history.json"


class ShellHistory:
    """Store executed multiline commands, never interpreter state or output."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_shell_history_path()

    def load(self) -> list[str]:
        try:
            commands = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            if not isinstance(exc, FileNotFoundError):
                logger.warning("Cannot read Python shell history %s: %s", self.path, exc)
            return []
        if not isinstance(commands, list) or any(
            not isinstance(command, str) for command in commands
        ):
            logger.warning("Invalid Python shell history at %s", self.path)
            return []
        return [command for command in commands if command]

    def save(self, commands: list[str]) -> None:
        """Replace the file atomically; callers report failures non-fatally."""
        atomic_write_json(self.path, commands)


def python_repl_history_path() -> Path:
    """Use the same history path as CPython's interactive prompt.

    PYTHON_HISTORY has been supported by CPython since 3.13. Older
    interpreters always use the home-directory .python_history file.
    """
    import os
    import sys

    override = (
        os.environ.get("PYTHON_HISTORY")
        if sys.version_info >= (3, 13) and not sys.flags.ignore_environment
        else None
    )
    return Path(override).expanduser() if override else Path.home() / ".python_history"


class PythonReplHistory:
    """Share with CPython's ordinary REPL without replacing its history file.

    The Python 3.13+ REPL represents multiline inputs by CRLF continuation,
    whereas the older readline REPL sees them as separate history lines.
    Both formats are readable by modern CPython. Legacy libedit files use a
    different encoding, identified by their magic header.
    """

    _EDITLINE_HEADER = b"_HiStOrY_V2_"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else python_repl_history_path()

    def load(self) -> list[str]:
        try:
            content = self.path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("Cannot read Python REPL history %s: %s", self.path, exc)
            return []

        lines = content.split(b"\n")
        if lines and lines[0].startswith(self._EDITLINE_HEADER):
            # The editline format escapes each entry on one physical line.
            return [
                line.decode("unicode-escape", errors="replace")
                for line in lines[1:] if line
            ]

        # Match the multiline extension of CPython's _pyrepl.readline.
        result: list[str] = []
        pending: list[str] = []
        for part in content.decode("utf-8", errors="replace").split("\n"):
            if part.endswith("\r"):
                pending.append(part[:-1])
            else:
                command = "\n".join((*pending, part))
                if command:
                    result.append(command)
                pending.clear()
        return result

    def append(self, commands: list[str]) -> None:
        """Append only new commands; never overwrite ordinary Python history."""
        import os

        if not commands:
            return
        legacy = False
        try:
            with self.path.open("rb") as stream:
                legacy = stream.readline().startswith(self._EDITLINE_HEADER)
        except FileNotFoundError:
            pass
        prepared = [
            command.replace("\r\n", "\n")
            for command in commands if command
        ]
        if not prepared:
            return
        if legacy:
            payload = b"".join(
                command.encode("unicode-escape") + b"\n"
                for command in prepared
            )
        else:
            payload = b"".join(
                command.replace("\n", "\r\n").encode("utf-8") + b"\n"
                for command in prepared
            )
        # One O_APPEND write prevents overwriting history created by Python
        # sessions. Mode 0600 protects a newly created command history file.
        descriptor = os.open(
            self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
        finally:
            os.close(descriptor)
