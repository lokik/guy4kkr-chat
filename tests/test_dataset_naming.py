from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import pytest

from ase import Atoms

from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.application.sprkkr_execution import SprkkrExecution
from ase2sprkkr_gui.gui.application.workspace_controller import CalculationRequest
from ase2sprkkr_gui.gui.input_parameters.dataset import (
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
        "ase2sprkkr_gui.gui.input_parameters.dataset.generated_dataset",
        generate,
    )
    atoms = Atoms("Fe")

    apply_default_dataset(parameters, "uuid", atoms)

    assert calls == [("uuid", atoms)]
    assert option.value == "injected"


@pytest.mark.parametrize("dataset", ["runs/Fe-01", ".Fe", "../Fe", "Železo", "Fe%T%c"])
def test_dataset_is_used_as_run_file_namespace(dataset):
    from ase2sprkkr.sprkkr._preparation import FilenameTemplator

    class Option:
        def is_set(self):
            return True

        def __call__(self):
            return dataset

    parameters = SimpleNamespace(CONTROL=SimpleNamespace(DATASET=Option()))

    templator = FilenameTemplator(None, 0, lambda: "SCF", lambda: "Fe")
    assert tuple(templator(name) for name in _execution(parameters).file_names()) == (
        f"{dataset}_SCF.inp",
        f"{dataset}.pot",
        f"{dataset}_SCF.out",
    )


def test_generated_structure_name_is_a_filename_component():
    assert filename_component("Fe run/01") == "Fe_run_01"


@pytest.mark.parametrize("prefix", ["runs/Fe-01", "Železo/Fe%T%c", ".Fe", "absolute"])
@pytest.mark.parametrize("operation", ["save", "run"])
def test_preparation_preserves_native_dataset_paths(tmp_path, prefix, operation):
    from pathlib import Path
    from ase.build import bulk
    from ase2sprkkr.input_parameters.input_parameters import InputParameters

    dataset = str(tmp_path / "nested/Fe") if prefix == "absolute" else prefix
    parameters = InputParameters.create("SCF")
    parameters.CONTROL.DATASET = dataset
    request = CalculationRequest(
        atoms=bulk("Fe"), input_parameters=parameters, directory=str(tmp_path),
        structure_id=1, state_id=1,
    )
    execution = SprkkrExecution(request, _Cancellation())
    expected = tmp_path / dataset
    input_path = expected.with_name(f"{expected.name}_SCF.inp")
    potential_path = expected.with_name(f"{expected.name}.pot")
    if operation == "run":
        runner = execution._create_runner(execution._calculator())
        try:
            output_path = expected.with_name(f"{expected.name}_SCF.out")
            assert Path(runner.spec.output_file.name) == output_path
            assert output_path.is_file()
        finally:
            runner.close()
    else:
        _written, actual_input, actual_potential, _output = execution.prepare_files()
        assert Path(actual_input) == input_path
        assert Path(actual_potential) == potential_path
    saved = InputParameters.from_file(input_path)
    assert saved.CONTROL.DATASET() == str(expected.relative_to(tmp_path))
    assert (tmp_path / saved.CONTROL.POTFIL()).resolve() == potential_path
    assert potential_path.is_file()
    assert parameters.CONTROL.DATASET() == dataset


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
