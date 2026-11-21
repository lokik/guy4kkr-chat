"""SCF live INFO monitoring from the native ERR/EF output stream."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTabWidget

from ase2sprkkr_gui.gui.dialogs.run_calculation import SprkkrRunWindow
from ase2sprkkr_gui.gui.dialogs.run_monitor import RunMonitorWindow
from ase2sprkkr.outputs.readers.scf import ScfProgressParser
from ase2sprkkr_gui.gui.dialogs.scf_progress import (
    ScfProgressTracker,
    scf_tolerance_from_parameters,
    ScfProgressPage,
)


def _native_line(
    number=6, fermi="0.76199", field="0.208E-01", potential="0.211E-02"
):
    return (
        f" {number} ERR {potential} {field} EF {fermi} "
        "0.00307 D 14.537 M 2.1740 0.0536\n"
    )


def _completed_line(*args, **kwargs):
    return _native_line(*args, **kwargs) + (
        " ETOT -42.5 SCF - cycle not converged - continue\n"
    )



def test_native_scf_error_is_worst_of_two_convergence_components():
    events = []
    parser = ScfProgressParser(on_info=lambda **event: events.append(event))
    parser.feed(_completed_line())
    assert len(events) == 1
    item = events[0]["data"]
    assert events[0]["kind"] == "scf_iteration"
    assert item.iteration == 6
    assert item.fermi_energy == 0.76199
    assert item.convergence_error == 0.0208
    assert item.error == 0.00211
    assert item.b_error == 0.0208
    parser.feed("normal stdout\n6 ERR ******* 0.02 EF 0.7\n")
    assert len(events) == 1


def test_scf_parser_supports_fortran_exponents_and_stream_fragments():
    tracker = ScfProgressTracker()
    line = _native_line(1, "0.76199D+00", "0.208D-01")
    assert not tracker.feed(line[:12], "out")
    assert not tracker.feed(line[12:], "out")
    assert not tracker.iterations
    assert tracker.feed(" ETOT -42.5 SCF - cycle not converged - continue\n", "out")
    assert tracker.iterations[0].iteration == 1
    assert tracker.iterations[0].fermi_energy == 0.76199
    assert tracker.iterations[0].convergence_error == 0.0208
    assert tracker.last_info_line.startswith("Iteration")


def test_scf_parser_ignores_stderr_and_replaces_replayed_iteration():
    tracker = ScfProgressTracker()
    assert not tracker.feed(_completed_line(1), "stderr")
    assert not tracker.iterations
    assert tracker.feed(_completed_line(1), "out")
    assert tracker.feed(_completed_line(1, "0.9"), "out")
    assert [(x.iteration, x.fermi_energy) for x in tracker.iterations] == [(1, 0.9)]
    assert tracker.feed(_completed_line(2, "0.8"), "out")
    assert [x.iteration for x in tracker.iterations] == [1, 2]
    assert tracker.feed(_completed_line(1, "0.7"), "out")
    assert [x.iteration for x in tracker.iterations] == [1]


def test_info_text_is_formatted_by_parser_not_reparsed():
    tracker = ScfProgressTracker()
    tracker.feed(_completed_line(3), "out")
    assert not tracker.feed("Iteration     3 error 2.11e-3 spin moment: 0.1\n", "info")
    assert tracker.last_info_line.startswith("Iteration")
    assert len(tracker.iterations) == 1


def test_scf_run_has_info_page_and_raw_output_is_preserved():
    app = QApplication.instance() or QApplication([])
    window = RunMonitorWindow(
        lambda cancellation: object(), task_name="SCF", autostart=False
    )
    assert isinstance(window._tabs, QTabWidget)
    assert [window._tabs.tabText(i) for i in range(2)] == ["INFO", "Output"]
    assert window._tabs.currentIndex() == 0

    window._append_output(_completed_line(6), "out")
    assert window._output.toPlainText().strip() == _completed_line(6).strip()
    progress = window._scf_progress
    assert progress.tracker.iterations[0].fermi_energy == 0.76199
    assert "Iteration" in progress.last_info.text()
    assert "RMS(V)" in progress.last_info.text()
    assert "RMS(B)" in progress.last_info.text()
    progress._redraw()
    assert list(progress.fermi_line.get_xdata()) == [6]
    assert list(progress.error_line.get_ydata()) == [0.00211]
    assert list(progress.b_error_line.get_ydata()) == [0.0208]
    legend = [text.get_text() for text in progress.error_axis.get_legend().get_texts()]
    assert "Potential RMS (V)" in legend
    assert "Field RMS (B)" in legend
    window.close()

def test_non_scf_run_keeps_original_output_only_layout():
    app = QApplication.instance() or QApplication([])
    window = RunMonitorWindow(lambda cancellation: object(), autostart=False)
    assert window._scf_progress is None
    assert not hasattr(window, "_tabs")
    window.close()


def test_new_scf_calculation_enables_info_page_before_start():
    app = QApplication.instance() or QApplication([])
    request = SimpleNamespace(
        directory="/tmp/scf", input_parameters=SimpleNamespace(
            task_name="SCF", SCF=SimpleNamespace(TOL=lambda: 1e-7)
        )
    )
    window = SprkkrRunWindow(request)
    assert window._scf_progress is not None
    assert window._scf_progress.tracker.target_error == 1e-7
    assert window._scf_progress.last_info.text() == "Preparing first iteration..."
    lower, upper = window._scf_progress.error_axis.get_ylim()
    assert lower < 1e-7 < upper
    window.close()


def test_scf_tolerance_helper_uses_effective_value_and_ignores_missing():
    parameters = SimpleNamespace(SCF=SimpleNamespace(TOL=lambda: 3e-7))
    assert scf_tolerance_from_parameters(parameters) == 3e-7
    assert scf_tolerance_from_parameters(None) is None
    assert scf_tolerance_from_parameters(
        SimpleNamespace(SCF=SimpleNamespace(TOL=lambda: 0))
    ) is None



def test_target_is_visible_before_first_iteration_and_remains_in_view():
    app = QApplication.instance() or QApplication([])
    page = ScfProgressPage(target_error=1e-6)
    assert page.last_info.text() == "Preparing first iteration..."
    assert list(page.target_line.get_ydata()) == [1e-6, 1e-6]
    low, high = page.error_axis.get_ylim()
    assert low < 1e-6 < high

    page.consume(_completed_line(1, field="0.208E-01"), "out")
    page._redraw()
    low, high = page.error_axis.get_ylim()
    assert low < 1e-6 < high and high > 2.08e-2

    page.consume(_completed_line(2, field="0.3E-09", potential="0.3E-09"), "out")
    page._redraw()
    assert list(page.error_line.get_ydata()) == [0.00211, 3e-10]
    assert list(page.b_error_line.get_ydata()) == [0.0208, 3e-10]
    low, high = page.error_axis.get_ylim()
    assert low < 3e-10 < 1e-6 < high
    page.close()

def test_stdout_header_supplies_target_for_reattached_run():
    app = QApplication.instance() or QApplication([])
    page = ScfProgressPage()
    assert page.target_line is None
    page.consume("          SCF-tol   : ", "out")
    page.consume("0.0000100000\n", "out")
    page._redraw()

    assert page.tracker.target_error == 1e-5
    assert page.last_info.text() == "Preparing first iteration..."
    assert list(page.target_line.get_ydata()) == [1e-5, 1e-5]
    low, high = page.error_axis.get_ylim()
    assert low < 1e-5 < high
    page.close()
