from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from ase2sprkkr_gui.gui.application.result_loading import LoadedResult
from ase2sprkkr_gui.gui.widgets.result_actions import ResultActionsWidget
from ase2sprkkr_gui.main import GuiApplication


def _loaded(name: str) -> LoadedResult:
    return LoadedResult(
        result=SimpleNamespace(
            task_name="dos",
            produces_potential=False,
            output_file=f"{name}.out",
            output_values={},
        ),
        output_path=None,
        potential_path=None,
        atoms=None,
        potential_error=None,
        directory=None,
        input_parameters=None,
    )


def test_explicit_import_selects_new_result_but_background_update_does_not(tmp_path):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    window = QWidget()
    window.result_actions_widget = widget
    gui._wire_result_actions(window)

    first = gui.controller.adopt_external_result(_loaded("first"), select_result=True)
    assert first.record is not None
    assert widget.selected_result_id == first.record.id

    background = gui.controller.adopt_external_result(_loaded("background"))
    assert background.record is not None
    assert widget.selected_result_id == first.record.id

    explicit = gui.controller.adopt_external_result(_loaded("explicit"), select_result=True)
    assert explicit.record is not None
    assert widget.selected_result_id == explicit.record.id

    window.close()
    widget.close()
