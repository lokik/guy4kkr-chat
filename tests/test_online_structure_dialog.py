import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from ase import Atoms
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem

from ase2sprkkr_gui.gui.dialogs.structures.online_database import _DOWNLOADED_ROLE, OnlineStructureDialog
from ase2sprkkr_gui.online_databases import (
    DownloadedStructure,
    ProviderCapabilities,
    SearchPage,
    StructureDatabaseProvider,
    StructureProvenance,
    StructureSummary,
)


class _FakeProvider(StructureDatabaseProvider):
    id = "fake"
    name = "Test Database"
    capabilities = ProviderCapabilities()

    def __init__(self):
        self.search_calls = []
        self.fetch_calls = []
        self.summary = StructureSummary(
            provider_id=self.id,
            entry_id="test-1",
            formula="FeO",
            name="test structure",
            site_count=2,
        )

    def search(self, query, *, page_url=None):
        self.search_calls.append((query, page_url))
        return SearchPage((self.summary,), total=1)

    def fetch(self, summary):
        self.fetch_calls.append(summary)
        atoms = Atoms(
            "FeO",
            positions=((0, 0, 0), (1, 1, 1)),
            cell=(2, 2, 2),
            pbc=True,
        )
        provenance = StructureProvenance(
            provider_id=self.id,
            provider_name=self.name,
            entry_id=summary.entry_id,
            entry_url="https://example.test/test-1",
            retrieved_at="2026-01-01T00:00:00+00:00",
            license_name="CC0-1.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            experimental=True,
        )
        atoms.info["online_database"] = provenance.as_dict()
        return DownloadedStructure(atoms, summary, provenance)


def _process_until(application, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    application.processEvents()
    assert predicate()


def test_search_fetch_and_open_use_one_provider_flow():
    application = QApplication.instance() or QApplication([])
    provider = _FakeProvider()
    dialog = OnlineStructureDialog(providers=(provider,))

    assert dialog._results_stack.currentWidget() is dialog._status_panel
    assert dialog._search_status.wordWrap()

    dialog._elements_edit.setText("fe, O")
    dialog._start_new_search()
    _process_until(application, lambda: dialog._table.rowCount() == 1)

    assert provider.search_calls[0][0].elements == ("Fe", "O")
    assert dialog._results_stack.currentWidget() is dialog._table_panel
    assert "1 result on this page" in dialog._page_status.text()
    assert dialog._table.item(0, 0).text() == "FeO"
    assert not dialog._open_button.isEnabled()

    dialog._table.selectRow(0)
    _process_until(application, dialog._open_button.isEnabled)

    assert provider.fetch_calls == [provider.summary]
    assert dialog.selected_atoms.get_chemical_formula() == "FeO"
    assert dialog.selected_atoms.info["online_database"]["entry_id"] == "test-1"
    dialog.close()


def test_downloaded_structure_is_cached_when_selection_changes():
    application = QApplication.instance() or QApplication([])
    provider = _FakeProvider()
    second_summary = StructureSummary(
        provider_id=provider.id,
        entry_id="test-2",
        formula="Cu",
        name="second structure",
        site_count=1,
    )
    dialog = OnlineStructureDialog(providers=(provider,))
    dialog._fill_table(SearchPage((provider.summary, second_summary)))

    dialog._table.selectRow(0)
    _process_until(application, dialog._open_button.isEnabled)
    downloaded = dialog._downloaded
    assert len(provider.fetch_calls) == 1
    assert dialog._table.item(0, 0).data(_DOWNLOADED_ROLE)

    dialog._table.selectRow(1)
    _process_until(application, lambda: len(provider.fetch_calls) == 2)
    dialog._table.selectRow(0)
    application.processEvents()

    assert dialog._open_button.isEnabled()
    assert dialog._downloaded is downloaded
    assert len(provider.fetch_calls) == 2
    dialog.close()
    application.processEvents()


def test_download_state_color_adapts_to_dark_and_light_palettes():
    application = QApplication.instance() or QApplication([])
    provider = _FakeProvider()
    dialog = OnlineStructureDialog(providers=(provider,))
    dialog._fill_table(SearchPage((provider.summary,)))
    item = dialog._table.item(0, 0)
    delegate = dialog._table.itemDelegate()

    for text, base, expected_range in (
        (QColor("#ffffff"), QColor("#202020"), range(195, 205)),
        (QColor("#000000"), QColor("#ffffff"), range(60, 70)),
    ):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Base, base)
        option = QStyleOptionViewItem()
        option.palette = palette
        delegate.initStyleOption(
            option,
            dialog._table.indexFromItem(item),
        )
        muted = option.palette.color(QPalette.ColorRole.Text)

        assert muted.red() in expected_range
        assert muted.green() in expected_range
        assert muted.blue() in expected_range

    item.setData(_DOWNLOADED_ROLE, True)
    option = QStyleOptionViewItem()
    option.palette.setColor(
        QPalette.ColorRole.Text,
        QColor("#123456"),
    )
    delegate.initStyleOption(
        option,
        dialog._table.indexFromItem(item),
    )
    assert (
        option.palette.color(QPalette.ColorRole.Text)
        == QColor("#123456")
    )
    dialog.close()
    application.processEvents()


def test_advanced_controls_build_one_normalized_query():
    application = QApplication.instance() or QApplication([])
    dialog = OnlineStructureDialog(providers=(_FakeProvider(),))
    dialog._elements_edit.setText("Fe, O")
    dialog._element_match.setCurrentIndex(
        dialog._element_match.findData("any")
    )
    dialog._excluded_elements_edit.setText("Pb; U")
    dialog._element_count.minimum.setValue(2)
    dialog._element_count.maximum.setValue(4)
    dialog._site_count.minimum.setValue(3)
    dialog._site_count.maximum.setValue(20)
    dialog._dimensionality.setCurrentIndex(
        dialog._dimensionality.findData(2)
    )
    dialog._structure_order.setCurrentIndex(
        dialog._structure_order.findData("disordered")
    )
    dialog._modified_range.after.setText("2020-01-02")
    dialog._modified_range.before.setText("2024-03-04")

    query = dialog._query()

    assert query.elements == ("Fe", "O")
    assert query.element_match == "any"
    assert query.excluded_elements == ("Pb", "U")
    assert (query.min_elements, query.max_elements) == (2, 4)
    assert (query.min_sites, query.max_sites) == (3, 20)
    assert query.dimensionality == 2
    assert query.structure_order == "disordered"
    assert query.modified_after.isoformat() == "2020-01-02"
    assert query.modified_before.isoformat() == "2024-03-04"
    dialog.close()
    application.processEvents()


def test_provider_specific_editor_adds_typed_condition():
    application = QApplication.instance() or QApplication([])
    dialog = OnlineStructureDialog()
    nomad_index = dialog._provider_combo.findData("nomad")
    dialog._provider_combo.setCurrentIndex(nomad_index)
    application.processEvents()

    editor = dialog._provider_filter_editor
    program_index = editor.property_combo.findData("program")
    editor.property_combo.setCurrentIndex(program_index)
    contains_index = editor.operator_combo.findData("CONTAINS")
    editor.operator_combo.setCurrentIndex(contains_index)
    editor.value_edit.setText("VASP")
    editor._add_filter()

    query = dialog._query()

    assert len(query.property_filters) == 1
    assert query.property_filters[0].key == "program"
    assert query.property_filters[0].operator == "CONTAINS"
    assert query.property_filters[0].value == "VASP"
    dialog.close()
    application.processEvents()


def test_search_error_replaces_table_and_wraps():
    application = QApplication.instance() or QApplication([])
    dialog = OnlineStructureDialog(providers=(_FakeProvider(),))
    dialog._show_results("Previous successful result.")

    dialog._search_token = 3
    dialog._search_failed(3, "A long provider error " * 20)

    assert dialog._results_stack.currentWidget() is dialog._status_panel
    assert dialog._search_status.wordWrap()
    assert "A long provider error" in dialog._search_status.text()
    dialog.close()


def test_default_dialog_lists_all_supported_providers():
    application = QApplication.instance() or QApplication([])
    dialog = OnlineStructureDialog()

    provider_ids = {
        dialog._provider_combo.itemData(index)
        for index in range(dialog._provider_combo.count())
    }

    assert provider_ids == {
        "cod",
        "materials-cloud-mc3d-pbe",
        "nomad",
    }

    nomad_index = dialog._provider_combo.findData("nomad")
    dialog._provider_combo.setCurrentIndex(nomad_index)
    application.processEvents()
    assert dialog._space_group_spin.isEnabled()
    assert dialog._site_count.isEnabled()
    assert not dialog._hide_duplicates.isEnabled()
    assert "NOMAD entry ID" in dialog._text_edit.placeholderText()
    assert dialog._query_mode.findData("anonymous") >= 0

    materials_cloud_index = dialog._provider_combo.findData(
        "materials-cloud-mc3d-pbe"
    )
    dialog._provider_combo.setCurrentIndex(materials_cloud_index)
    application.processEvents()
    assert not dialog._space_group_spin.isEnabled()
    assert dialog._site_count.isEnabled()
    assert "MC3D ID" in dialog._text_edit.placeholderText()
    dialog.close()
    application.processEvents()
