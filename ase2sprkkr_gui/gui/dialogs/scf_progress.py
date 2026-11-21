"""SCF INFO page driven by ase2sprkkr structured parser events."""
from __future__ import annotations

from math import isfinite

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ase2sprkkr.outputs.readers.scf import ScfIterationInfo, ScfProgressParser

_MAX_ITERATIONS = 2000


def _positive_tolerance(value: object) -> float | None:
    try:
        result = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) and result > 0 else None


def scf_tolerance_from_parameters(parameters: object) -> float | None:
    """Use effective input threshold until the running program reports it."""
    try:
        value = parameters.SCF.TOL()
    except (AttributeError, TypeError, ValueError):
        return None
    return _positive_tolerance(value)


class ScfProgressTracker:
    """Display SCF parser events without interpreting SPR-KKR stdout in Qt."""

    def __init__(self, target_error: float | None = None) -> None:
        self.iterations: list[ScfIterationInfo] = []
        self.target_error = _positive_tolerance(target_error)
        self.last_info_line = "Preparing first iteration..."
        self.parser = ScfProgressParser(on_info=self._on_info)
        self._changed = False

    def _on_info(self, *, kind: str, data: object) -> None:
        if kind == "scf_tolerance":
            if data.tolerance != self.target_error:
                self.target_error = data.tolerance
                self._changed = True
        elif kind == "scf_iteration":
            if self.iterations and data.iteration < self.iterations[-1].iteration:
                self.iterations.clear()
            if self.iterations and data.iteration == self.iterations[-1].iteration:
                self.iterations[-1] = data
            else:
                self.iterations.append(data)
                if len(self.iterations) > _MAX_ITERATIONS:
                    del self.iterations[: len(self.iterations) - _MAX_ITERATIONS]
            self.last_info_line = self.parser.format_info(kind, data)
            self._changed = True
        elif kind == "scf_finished":
            self.last_info_line = self.parser.format_info(kind, data)
            self._changed = True

    def feed(self, text: str, kind: str = "out") -> bool:
        if kind.lower() in {"err", "stderr"} or not text:
            return False
        self._changed = False
        self.parser.feed(text)
        return self._changed


class ScfProgressPage(QWidget):
    """Qt INFO page: latest iteration and two live, automatically scaled plots."""

    def __init__(
        self, parent: QWidget | None = None, *, target_error: float | None = None
    ) -> None:
        super().__init__(parent)
        # Import only for an SCF monitor; non-SCF runs need no plotting canvas.
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.tracker = ScfProgressTracker(target_error)
        layout = QVBoxLayout(self)
        title = QLabel("Latest INFO line", self)
        layout.addWidget(title)

        self.last_info = QLabel(self.tracker.last_info_line, self)
        self.last_info.setWordWrap(True)
        self.last_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.last_info)

        self.figure = Figure(figsize=(8, 5), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)

        self.fermi_axis, self.error_axis = self.figure.subplots(2, 1, sharex=True)
        self.fermi_line, = self.fermi_axis.plot([], [], marker="o", markersize=3)
        self.error_line, = self.error_axis.plot(
            [], [], marker="o", markersize=3, label="Potential RMS (V)"
        )
        self.b_error_line, = self.error_axis.plot(
            [], [], marker="s", markersize=3, label="Field RMS (B)"
        )
        self.fermi_axis.set_ylabel("Fermi energy (Ry)")
        self.error_axis.set_ylabel("Convergence errors (RMS)")
        self.error_axis.set_xlabel("SCF iteration")
        self.error_axis.set_yscale("log")
        self.target_line = None
        for axis in (self.fermi_axis, self.error_axis):
            axis.grid(True, alpha=0.3)
        # Show the convergence target before the first iteration if known.
        self._sync_target()
        self.error_axis.legend(loc="upper right")
        self._set_error_limits()

        # Coalesce potentially frequent output callbacks into a single redraw.
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(120)
        self._redraw_timer.timeout.connect(self._redraw)

    def consume(self, text: str, kind: str) -> None:
        if self.tracker.feed(text, kind):
            self.last_info.setText(self.tracker.last_info_line)
            if not self._redraw_timer.isActive():
                self._redraw_timer.start()

    def _sync_target(self) -> None:
        target = self.tracker.target_error
        if target is None:
            return
        if self.target_line is None:
            self.target_line = self.error_axis.axhline(
                target, linestyle="--", linewidth=1.2, color="tab:red",
                label=f"Target {target:.2g}",
            )
        else:
            self.target_line.set_ydata([target, target])
            self.target_line.set_label(f"Target {target:.2g}")
        self.error_axis.legend(loc="upper right")

    def _set_error_limits(self) -> None:
        """Keep the target and every measured error visible on the log axis."""
        values = [
            max(abs(value), 1e-16)
            for item in self.tracker.iterations
            for value in (item.error, item.b_error)
        ]
        if self.tracker.target_error is not None:
            values.append(self.tracker.target_error)
        if values:
            self.error_axis.set_ylim(min(values) / 2, max(values) * 2)

    def _redraw(self) -> None:
        self._sync_target()
        iterations = self.tracker.iterations
        if iterations:
            x = [item.iteration for item in iterations]
            self.fermi_line.set_data(x, [item.fermi_energy for item in iterations])
            # Zero RMS errors are clamped only for the logarithmic display.
            self.error_line.set_data(
                x, [max(abs(item.error), 1e-16) for item in iterations]
            )
            self.b_error_line.set_data(
                x, [max(abs(item.b_error), 1e-16) for item in iterations]
            )
            for axis in (self.fermi_axis, self.error_axis):
                axis.relim()
                axis.autoscale_view()
        self._set_error_limits()
        self.canvas.draw_idle()
