from __future__ import annotations

import ast
from pathlib import Path

import ase2sprkkr


ROOT = Path(__file__).parents[1] / "ase2sprkkr_gui"
_ROOT_EXPORTS = frozenset(ase2sprkkr.__all__)


def test_root_exported_backend_names_use_root_imports():
    violations = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module == "ase2sprkkr" or not module.startswith("ase2sprkkr."):
                continue
            imported = _ROOT_EXPORTS.intersection(alias.name for alias in node.names)
            if imported:
                violations.append(
                    f"{path.relative_to(ROOT.parent)}:{node.lineno}: "
                    f"{', '.join(sorted(imported))}"
                )

    assert not violations, (
        "Names exported by ase2sprkkr.__all__ must be imported from the root "
        "package in Ase2sprkkr:\n" + "\n".join(violations)
    )
