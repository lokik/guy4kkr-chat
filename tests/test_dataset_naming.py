from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.input_parameters.dataset import (
    apply_default_dataset,
    filename_component,
    generated_dataset,
)


class _Cancellation:
    requested = False

    def register(self, _runner):
        return True


def _execution(parameters) -> SprkkrExecution:
    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=parameters,
        directory=".",
        structure_id=1,
        state_id=1,
    )
    return SprkkrExecution(request, _Cancellation())


def test_dataset_setting_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)
    settings.dataset_default_mode = "uuid"

    assert settings.save()

    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.dataset_default_mode == "uuid"


def test_invalid_dataset_setting_uses_datetime_default(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"viewer": "ase", "dataset_default_mode": "something-else"}',
        encoding="utf-8",
    )

    settings = ApplicationSettings(path)
    settings.load()

    assert settings.dataset_default_mode == "datetime"


def test_generated_datetime_dataset_is_readable_and_filename_safe():
    value = generated_dataset(
        "datetime",
        Atoms("Fe2O3"),
        now=datetime(2026, 10, 11, 18, 7, 8, 123456),
    )

    assert value == "Fe2O3_20261011_180708_123"


def test_generated_uuid_dataset_uses_structure_name():
    value = generated_dataset(
        "uuid",
        Atoms("Fe"),
        uuid_hex="0123456789abcdef",
    )

    assert value == "Fe_0123456789ab"


def test_empty_dataset_mode_leaves_dataset_unset():
    assert generated_dataset("empty", Atoms("Fe")) is None


def test_apply_default_dataset_uses_injected_mode(monkeypatch):
    class Option:
        def __init__(self):
            self.value = None

        def is_set(self):
            return self.value is not None

        def set(self, value):
            self.value = value

    option = Option()
    parameters = SimpleNamespace(CONTROL=SimpleNamespace(DATASET=option))
    calls = []

    def generate(mode, atoms):
        calls.append((mode, atoms))
        return "injected"

    monkeypatch.setattr(
        "guy4ase.gui.input_parameters.dataset.generated_dataset",
        generate,
    )
    atoms = Atoms("Fe")

    apply_default_dataset(parameters, "uuid", atoms)

    assert calls == [("uuid", atoms)]
    assert option.value == "injected"


def test_dataset_is_used_as_run_file_namespace():
    class Option:
        def is_set(self):
            return True

        def __call__(self):
            return "Fe run/01"

    parameters = SimpleNamespace(CONTROL=SimpleNamespace(DATASET=Option()))

    assert _execution(parameters).file_names() == (
        "Fe_run_01_%T.inp",
        "Fe_run_01.pot",
        "Fe_run_01_%T.out",
    )
    assert filename_component("Fe run/01") == "Fe_run_01"


def test_unset_dataset_uses_conventional_names():
    class Option:
        def is_set(self):
            return False

    parameters = SimpleNamespace(CONTROL=SimpleNamespace(DATASET=Option()))

    assert _execution(parameters).file_names() == (
        "%a_%T.inp",
        "%a.pot",
        "%a_%T.out",
    )
