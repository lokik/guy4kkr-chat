"""Live BSF INFO tab uses native parser events in both calculation modes."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTabWidget

from ase2sprkkr_gui.gui.dialogs.run_monitor import RunMonitorWindow


def test_bsf_ek_info_reports_energy_indices_without_fabricated_progress():
    app = QApplication.instance() or QApplication([])
    window = RunMonitorWindow(
        lambda cancellation: object(), task_name="BSFEK", autostart=False
    )
    assert isinstance(window._tabs, QTabWidget)
    assert [window._tabs.tabText(i) for i in range(2)] == ["INFO", "Output"]
    assert window._bsf_progress is not None
    assert window._bsf_progress.progress.isHidden()

    stdout = (
        "MPI calculation with NPROCS = 4\n"
        "E(k)-relation mode for:\n"
        "with  NE =  200  NK =  297\n"
        "IE= 151 E= -0.8079 0.0010 all matrices set up - enter k-loop\n"
        "IE= 175 E= -0.9020 0.0010 all matrices set up - enter k-loop\n"
    )
    window._append_output(stdout[:51], "out")
    window._append_output(stdout[51:], "out")
    assert "energy loop 25/50" in window._bsf_progress.last_info.text()
    assert "NE=200" in window._bsf_progress.events.toPlainText()
    assert window._bsf_progress.progress.maximum() == 50
    assert window._bsf_progress.progress.value() == 24
    assert not window._bsf_progress.progress.isHidden()
    assert window._output.toPlainText().strip() == stdout.strip()
    window.close()


def test_bsf_kk_info_shows_mesh_and_aggregates_native_warnings():
    app = QApplication.instance() or QApplication([])
    window = RunMonitorWindow(
        lambda cancellation: object(), task_name="BSFKK", autostart=False
    )
    stdout = (
        "constant E mode for:\n"
        "fixed energy 0.125439 0.000000\n"
        "NK1 = 60 K1 = (1 0 0)\n"
        "NK2 = 60 K2 = (0 1 0)\n"
        "IE= 1 E= 0.1254 0.0000 all matrices set up - enter k-loop\n"
        + "WARNING <BLOCHBSF>: Spectral function negative\n" * 101
        + "finished in subroutine <BLOCHSF>\n"
    )
    window._append_output(stdout, "out")
    progress = window._bsf_progress
    assert progress.parser.mode == "KK"
    assert progress.progress.isHidden()
    assert progress.parser.negative_warnings == 101
    assert "101" in progress.last_info.text()
    assert "60 × 60" in progress.events.toPlainText()
    assert len(progress.events.toPlainText().split("Negative spectral-function warnings:")) == 4
    assert "finished" in progress.last_info.text()
    assert window._output.toPlainText().strip().endswith("finished in subroutine <BLOCHSF>")
    window.close()
