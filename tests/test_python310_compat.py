"""Guard minimum Python 3.10 syntax support using the standard library."""

import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "guy4ase"


class Python310CompatibilityTest(unittest.TestCase):
    def test_package_sources_are_python310_compatible(self):
        failures = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(PROJECT_ROOT)
            try:
                ast.parse(source, filename=str(relative), feature_version=10)
            except SyntaxError as error:
                failures.append(
                    f"{relative}:{error.lineno or 1}: "
                    f"not valid Python 3.10 syntax: {error.msg}"
                )
        self.assertFalse(failures, "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
