"""Guards for the minimum supported Python version.

This test intentionally depends only on the standard library so CI can run it
before installing Guy4ase or ase2sprkkr dependencies.
"""

import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "guy4ase"


def _has_postponed_annotations(tree):
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            yield node.returns


def _pep604_lines(tree):
    for annotation in _annotations(tree):
        for node in ast.walk(annotation):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                yield node.lineno


class Python39CompatibilityTest(unittest.TestCase):
    def test_package_sources_are_python39_compatible(self):
        failures = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(PROJECT_ROOT)
            try:
                tree = ast.parse(
                    source,
                    filename=str(relative),
                    feature_version=9,
                )
            except SyntaxError as error:
                failures.append(
                    "%s:%s: not valid Python 3.9 syntax: %s"
                    % (relative, error.lineno or 1, error.msg)
                )
                continue

            if _has_postponed_annotations(tree):
                continue
            for line in _pep604_lines(tree):
                failures.append(
                    "%s:%s: PEP 604 annotation requires "
                    "'from __future__ import annotations' on Python 3.9"
                    % (relative, line)
                )

        self.assertFalse(failures, "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
