"""No compatibility namespace is retained after the application rename."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_name_and_gui_entry_point():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "ase2sprkkr-gui"' in project
    assert '"ase2sprkkr-gui" = "ase2sprkkr_gui.main:main"' in project
    assert 'cli = "ase2sprkkr_gui.cli"' in project


def test_only_new_package_namespace_is_installed():
    assert (ROOT / "ase2sprkkr_gui" / "__init__.py").is_file()
    assert not (ROOT / "guy4ase").exists()
