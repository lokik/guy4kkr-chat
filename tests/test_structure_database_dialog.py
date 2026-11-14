import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from PyQt6.QtCore import QCoreApplication, QEvent

from ase2sprkkr_gui.gui.dialogs.structures.spacegroup_selector import SpaceGroupSelectorDialog
from ase2sprkkr_gui.gui.dialogs.structures.database import StructureDatabaseDialog
from ase2sprkkr_gui.physics.structure_database import load_structure_database


def test_filtered_selection_and_details_stay_synchronized():
    dialog = StructureDatabaseDialog()

    dialog.search_edit.setText("CsCl")

    assert dialog.selected_prototype is not None
    assert dialog.selected_prototype.name.startswith("B2")
    assert "Space group 221" in dialog.details_label.text()
    assert "B2" in dialog.details_label.text()
    assert dialog.table.horizontalHeaderItem(0).text() == "Description"
    assert dialog.table.horizontalHeaderItem(1).text() == "Structure type"
    dialog.close()


def test_unknown_structure_type_is_presented_without_source_placeholder():
    dialog = StructureDatabaseDialog()

    dialog.search_edit.setText("ReSi2")

    assert dialog.table.item(0, 1).text() == "Unknown"
    assert "Unknown oI6 ReSi2" in dialog.details_label.text()
    assert "???" not in dialog.details_label.text()
    dialog.close()


def test_every_database_prototype_can_preload_the_shared_editor():
    dialog = SpaceGroupSelectorDialog()

    for prototype in load_structure_database():
        dialog.load_prototype(prototype)
        selected_space_group = int(
            dialog.table.item(dialog.table.currentRow(), 0).text()
        )
        assert selected_space_group == prototype.space_group
        assert sum(map(len, dialog._selected_sites.values())) == len(prototype.sites)

    dialog.close()


def test_shared_editor_creates_representative_database_structures():
    dialog = SpaceGroupSelectorDialog()
    expected_atom_counts = {
        "B2    cP2   CsCl": 2,
        "C4    tP6   TiO2 (Rutil)": 6,
        "L1_1  hR32  CuPt": 6,
        "Molecular Perovskite x": 12,
    }

    prototypes = {item.name: item for item in load_structure_database()}
    for name, atom_count in expected_atom_counts.items():
        dialog.load_prototype(prototypes[name])
        values = {
            "a": 4.0,
            "b": 5.0,
            "c": 6.0,
            "α": 80.0,
            "β": 90.0,
            "γ": 100.0,
        }
        for key, value in values.items():
            if dialog._lat_vars[key].isEnabled():
                dialog._lat_vars[key].setText(str(value))

        atoms = dialog.create_atoms()
        assert len(atoms) == atom_count
        assert len(set(atoms.arrays["spacegroup_kinds"])) == len(
            prototypes[name].sites
        )

    dialog.close()


def test_structure_editor_deferred_gui_work_is_object_owned(_qt_application):
    dialog = SpaceGroupSelectorDialog()
    prototype = next(
        item for item in load_structure_database() if item.name.startswith("C4 ")
    )
    dialog.load_prototype(prototype)

    assert dialog._draw_timer.parent() is dialog
    assert dialog._draw_timer.isActive()
    assert dialog._focus_timer.parent() is dialog

    wyckoff = next(iter(dialog._wyckoff_widgets.values()))
    assert wyckoff._focus_filter.parent() is wyckoff
    assert wyckoff._focus_filter._leave_timer.parent() is wyckoff._focus_filter

    # Deleting the dialog must cancel its pending redraw rather than leaving a
    # Python callback that can run against an already-destroyed Qt widget tree.
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _qt_application.processEvents()


def test_database_editor_focuses_first_editable_lattice_parameter(_qt_application):
    dialog = SpaceGroupSelectorDialog()
    prototype = next(
        item for item in load_structure_database() if item.name.startswith("C4 ")
    )
    dialog.load_prototype(prototype)
    dialog.show()

    dialog.focus_lattice_parameters()
    _qt_application.processEvents()

    assert _qt_application.focusWidget() is dialog._lat_vars["a"]
    dialog.close()
