"""Exercise the real Matplotlib/Qt editor in an isolated GUI process."""
import os
import subprocess
import sys
import textwrap


def test_kpath_waits_for_its_own_window_with_and_without_running_application():
    script = textwrap.dedent('''
        import numpy as np
        from PyQt6.QtWidgets import QApplication, QWidget
        from PyQt6.QtCore import QTimer, Qt, qInstallMessageHandler
        import matplotlib
        matplotlib.use("qtagg")
        import matplotlib.pyplot as plt
        from matplotlib.backend_bases import MouseEvent, PickEvent
        from ase.build import bulk
        from ase2sprkkr.gui.k_path import k_path_gui

        app = QApplication([])
        parent = QWidget()
        parent.show()
        messages = []
        previous_handler = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
        atoms = bulk("Fe", "bcc", a=2.8)
        original_cell = atoms.cell.array.copy()
        unrelated = plt.figure()
        unrelated.show()
        failures = []

        def check(indices, with_parent, action="close"):
            figures_before = set(plt.get_fignums())
            completed = []
            timed_out = []
            interaction = QTimer()
            interaction.setSingleShot(True)
            watchdog = QTimer()
            watchdog.setSingleShot(True)

            def interact():
                try:
                    figure = plt.gcf()
                    assert figure is not unrelated
                    canvas = figure.canvas
                    window = canvas.manager.window
                    assert window.isVisible()
                    ok_axes = next(ax for ax in figure.axes if any(t.get_text() == "OK" for t in ax.texts))

                    def click_button(label):
                        canvas.draw()
                        axes = next(ax for ax in figure.axes if any(t.get_text() == label for t in ax.texts))
                        x, y = axes.transAxes.transform((0.5, 0.5))
                        for name in ("button_press_event", "button_release_event"):
                            canvas.callbacks.process(name, MouseEvent(name, canvas, x, y, button=1))

                    # OK must not accept an empty selection.
                    click_button("OK")
                    assert window.isVisible()
                    if with_parent:
                        assert window.parentWidget() is parent
                        assert window.windowModality() == Qt.WindowModality.WindowModal
                        assert app.activeModalWidget() is window
                    artist = next(c for c in figure.axes[0].collections if c.get_picker())
                    mouse = MouseEvent("button_press_event", canvas, 0, 0, button=1)
                    for index in indices:
                        event = PickEvent("pick_event", canvas, mouse, artist, ind=[index])
                        canvas.callbacks.process("pick_event", event)
                    if action == "ok":
                        # Exercise the real Matplotlib button via mouse events.
                        click_button("OK")
                        if len(indices) == 2:
                            assert not window.isVisible()
                        else:
                            # A single point (including undoing the last pick)
                            # must leave OK inactive.
                            assert window.isVisible()
                            window.close()
                    elif action == "cancel":
                        click_button("Cancel")
                        assert not window.isVisible()
                    else:
                        # Keep covering the original window-close workflow.
                        window.close()
                    completed.append(True)
                except BaseException as exc:
                    failures.append(exc)
                    plt.gcf().canvas.stop_event_loop()

            def timeout():
                timed_out.append(True)
                plt.gcf().canvas.stop_event_loop()

            interaction.timeout.connect(interact)
            watchdog.timeout.connect(timeout)
            interaction.start(50)
            watchdog.start(5000)
            try:
                result = k_path_gui(atoms, parent=parent if with_parent else None)
                assert not failures, failures
                assert not timed_out, "Editor did not return after its window closed"
                assert completed, "Editor returned before the user finished selecting"
                if action == "ok" and len(indices) == 2:
                    assert result["NKDIR"] == 1 and result["NK"] > 0
                    assert result["KA"].shape == result["KE"].shape == (1, 3)
                else:
                    assert result is None
                assert set(plt.get_fignums()) == figures_before
                assert unrelated.canvas.manager.window.isVisible()
                np.testing.assert_array_equal(atoms.cell.array, original_cell)
            finally:
                interaction.stop()
                watchdog.stop()

        # Standalone: no QApplication.exec() running yet.
        check([0, 1], False, action="ok")

        def inside_application():
            try:
                for with_parent in (False, True):
                    for indices in ([], [0], [0, 1], [0, 1, 1]):
                        check(indices, with_parent)
                        check(indices, with_parent, action="ok")
                        check(indices, with_parent, action="cancel")
            except BaseException as exc:
                failures.append(exc)
            finally:
                app.quit()

        QTimer.singleShot(0, inside_application)
        app.exec()
        qInstallMessageHandler(previous_handler)
        plt.close("all")
        assert not failures, failures
        assert not any("already running" in message for message in messages), messages
    ''')
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                            text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
