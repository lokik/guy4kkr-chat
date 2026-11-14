from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_execution_profile_application_module_imports_without_qt_or_dialogs():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import ase2sprkkr_gui.gui.application.execution_profiles
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('ase2sprkkr_gui.gui.dialogs.') for name in sys.modules)
assert not any(name.startswith('ase2sprkkr_gui.gui.widgets.') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )
