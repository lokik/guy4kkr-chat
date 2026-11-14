"""No compatibility namespace is retained after the application rename."""
from pathlib import Path

from setuptools.config.pyprojecttoml import read_configuration

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_name_and_gui_entry_point():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "ase2sprkkr-gui"' in project
    assert '"ase2sprkkr-gui" = "ase2sprkkr_gui.main:main"' in project
    assert 'cli = "ase2sprkkr_gui.cli"' in project


def test_only_new_package_namespace_is_installed():
    assert (ROOT / "ase2sprkkr_gui" / "__init__.py").is_file()

    # Check the packages setuptools actually discovers for the distribution.
    # An old, untracked directory in a developer's checkout is not installed.
    packages = read_configuration(ROOT / "pyproject.toml")["tool"]["setuptools"]["packages"]
    assert "ase2sprkkr_gui" in packages
    assert all(
        name == "ase2sprkkr_gui" or name.startswith("ase2sprkkr_gui.")
        for name in packages
    )
