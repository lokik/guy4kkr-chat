from guy4ase.gui.dialogs.profiles import RunIdentification
import pytest
from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def _controller(tmp_path):
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )


def test_run_flow_tracks_top_level_monitor_before_start(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    captured = {}
    events = []

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            events.append("show")

        def start(self):
            events.append("start")

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (True, "cluster", None, str(tmp_path), None),
    )
    monkeypatch.setattr(
        calculation_flow,
        "profile_description",
        lambda name: f"profile:{name}",
    )

    parent = object()

    def track(window):
        assert isinstance(window, Window)
        events.append("track")

    window = calculation_flow.run_calculation(
        controller,
        recent,
        parent,
        track_launch_monitor=track,
    )

    assert window is not None
    assert captured["profile_name"] == "cluster"
    assert captured["profile_description"] == "profile:cluster"
    assert captured["parent"] is None
    assert events == ["track", "show", "start"]


def test_monitor_is_closed_when_ownership_transfer_fails(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    events = []

    class Window:
        def __init__(self, **_kwargs):
            pass

        def show(self):
            raise AssertionError("show must not follow failed ownership transfer")

        def start(self):
            raise AssertionError("start must not follow failed ownership transfer")

        def close(self):
            events.append("close")

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (True, None, None, str(tmp_path), None),
    )
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)

    def fail_track(_window):
        events.append("track")
        raise RuntimeError("cannot transfer ownership")

    with pytest.raises(RuntimeError, match="cannot transfer ownership"):
        calculation_flow.run_calculation(
            controller,
            RecentFiles(tmp_path / "recent.json"),
            object(),
            track_launch_monitor=fail_track,
        )

    assert events == ["track", "close"]


def test_tracked_monitor_is_closed_and_start_error_propagates(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    events = []

    class Window:
        def __init__(self, **_kwargs):
            pass

        def show(self):
            events.append("show")

        def start(self):
            events.append("start")
            raise RuntimeError("worker creation failed")

        def close(self):
            events.append("close")

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (True, None, None, str(tmp_path), None),
    )
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)

    with pytest.raises(RuntimeError, match="worker creation failed"):
        calculation_flow.run_calculation(
            controller,
            RecentFiles(tmp_path / "recent.json"),
            object(),
            track_launch_monitor=lambda _window: events.append("track"),
        )

    assert events == ["track", "show", "start", "close"]


def test_tracked_monitor_is_closed_when_show_fails(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    events = []

    class Window:
        def __init__(self, **_kwargs):
            pass

        def show(self):
            events.append("show")
            raise RuntimeError("cannot show monitor")

        def start(self):
            raise AssertionError("start must not follow failed show")

        def close(self):
            events.append("close")

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (True, None, None, str(tmp_path), None),
    )
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)

    with pytest.raises(RuntimeError, match="cannot show monitor"):
        calculation_flow.run_calculation(
            controller,
            RecentFiles(tmp_path / "recent.json"),
            object(),
            track_launch_monitor=lambda _window: events.append("track"),
        )

    assert events == ["track", "show", "close"]


def test_standalone_run_keeps_parent_ownership(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (True, None, None, str(tmp_path), None),
    )
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)

    parent = object()
    assert calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        parent,
    ) is not None
    assert captured["parent"] is parent


def test_cancelled_profile_selection_does_not_construct_window(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    controller.set_active_project("existing-project")
    constructed = []

    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (False, None, None, None, None),
    )
    monkeypatch.setattr(
        calculation_flow,
        "SprkkrRunWindow",
        lambda **kwargs: constructed.append(kwargs),
    )

    assert calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
    ) is None
    assert constructed == []
    assert controller.active_project_id == "existing-project"


def test_automatic_profile_is_distinct_from_cancel(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (True, None, None, str(tmp_path), None),
    )
    monkeypatch.setattr(
        calculation_flow,
        "profile_description",
        lambda name: "automatic",
    )

    assert calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
    ) is not None
    assert captured["profile_name"] is None


def test_directory_is_chosen_with_execution_profile(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    controller.change_directory(None)
    assert controller.can_calculate()
    events = []

    class Window:
        def __init__(self, **kwargs):
            events.append(("launch", kwargs["request"].directory))

        def show(self):
            pass

        def start(self):
            pass

    def select(_parent, **kwargs):
        events.append(("settings", kwargs["directory"]))
        return True, None, None, str(tmp_path), None

    monkeypatch.setattr(calculation_flow, "_select_profile", select)
    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _: None)

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is not None
    assert events == [("settings", None), ("launch", str(tmp_path))]
    assert controller.directory == str(tmp_path)


def test_cancelling_execution_setup_with_no_directory_is_side_effect_free(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    controller.change_directory(None)
    old_generation = controller.directory_generation
    monkeypatch.setattr(
        calculation_flow, "_select_profile",
        lambda _parent, **_kwargs: (False, None, None, None, None),
    )
    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is None
    assert controller.directory is None
    assert controller.directory_generation == old_generation


def test_selected_project_becomes_active_and_is_bound_to_run(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    controller.set_active_project("active-project")
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    def select(_parent, **kwargs):
        assert kwargs["active_project_id"] == "active-project"
        return True, None, None, str(tmp_path), "selected-project"

    monkeypatch.setattr(calculation_flow, "_select_profile", select)
    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _: None)

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is not None
    assert captured["project_id"] == "selected-project"
    assert controller.active_project_id == "selected-project"


def test_unassigned_project_is_explicit_even_when_active_project_exists(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    controller.set_active_project("active-project")
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow, "_select_profile",
        lambda _parent, **_kwargs: (True, None, None, str(tmp_path), None),
    )
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _: None)
    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is not None
    assert captured["project_id"] is None
    assert controller.active_project_id is None


def test_stale_project_selection_does_not_change_directory_or_launch(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    controller.set_active_project("initial")
    directory = str(tmp_path / "selected-directory")
    created = []

    def select(_parent, **kwargs):
        assert kwargs["active_project_id"] == "initial"
        controller.set_active_project("concurrent")
        return True, None, None, directory, "selected"

    monkeypatch.setattr(calculation_flow, "_select_profile", select)
    monkeypatch.setattr(
        calculation_flow, "SprkkrRunWindow",
        lambda **kwargs: created.append(kwargs),
    )
    # Avoid showing a Qt message box for the expected stale selection.
    monkeypatch.setattr(
        calculation_flow, "document_change_applied",
        lambda _parent, change: change.name == "APPLIED",
    )

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is None
    assert created == []
    assert controller.active_project_id == "concurrent"
    assert controller.directory == str(tmp_path)


def test_back_from_conflict_reopens_run_picker_with_previous_settings(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    ident = RunIdentification("Fe_collision", "label-2")
    selected = []
    launched = []

    def select(_parent, **kwargs):
        selected.append(kwargs)
        if len(selected) == 1:
            return True, "remote-profile", ident, str(tmp_path), "project-1"
        # The new dialog starts with exactly the previous run setup.
        assert kwargs["selected_profile_name"] == "remote-profile"
        assert kwargs["initial_identification"] == ident
        assert kwargs["directory"] == str(tmp_path)
        assert kwargs["active_project_id"] == "project-1"
        assert kwargs["directory_is_explicit"] is True
        return False, None, None, None, None

    class Window:
        def __init__(self, **kwargs):
            launched.append(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "_select_profile", select)
    monkeypatch.setattr(calculation_flow, "_apply_run_identification", lambda _params, _ident: None)
    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _: None)

    assert calculation_flow.run_calculation(controller, recent, object()) is not None
    assert len(launched) == 1
    launched[0]["on_back_to_setup"]()
    assert len(selected) == 2
    # Declining a conflicting run does not start the second calculation.
    assert len(launched) == 1
