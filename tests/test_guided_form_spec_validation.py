from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QStackedWidget

from ase2sprkkr_gui.gui.input_parameters.specs.schema import (
    GroupSpec,
    PageSpec,
    TaskDialogSpec,
    field,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.form import GuidedFormRenderer


class _MissingOptionSession:
    def option(self, path):
        raise KeyError(path)


def test_missing_option_diagnostic_does_not_require_task_identity():
    _application = QApplication.instance() or QApplication([])
    spec = TaskDialogSpec(
        title="Broken layout",
        pages=(
            PageSpec(
                id="main",
                title="Main",
                groups=(
                    GroupSpec(
                        title="Broken group",
                        fields=(field("MISSING", "VALUE", "Missing"),),
                    ),
                ),
                color="#808080",
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"guided-dialog specification refers to missing parameter MISSING\.VALUE",
    ):
        GuidedFormRenderer(
            _MissingOptionSession(),
            spec,
            QStackedWidget(),
            select_page=lambda _page: None,
        )
