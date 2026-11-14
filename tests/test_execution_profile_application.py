from __future__ import annotations

from types import SimpleNamespace

import pytest

from ase2sprkkr_gui.gui.application import execution_profiles as profile_application
from ase2sprkkr_gui.gui.application.execution_profiles import (
    ExecutionProfileEditor,
    ExecutionProfileStore,
)


class _Option:
    def __init__(self, value=None):
        self.value = value

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = value


class _Profile:
    def __init__(self, values, *, read_only=False):
        self._values = dict(values)
        self.read_only = read_only

    def as_dict(self, *args, **kwargs):
        return dict(self._values)


class _Profiles:
    reserved_names = frozenset(("ase", "legacy"))

    def __init__(self):
        self.values = {
            "ase": _Profile({"command": "/opt/sprkkr/kkrscf"}, read_only=True),
            "local": _Profile({"executor": "local", "mpi": 4}, read_only=False),
        }
        self.saved = None

    def __iter__(self):
        return iter(self.values)

    def items(self):
        return self.values.items()

    def resolve_name(self, name):
        return name

    def set(self, values):
        self.saved = values


class _Config:
    def __init__(self, *, default_profile=None):
        self.profiles = _Profiles()
        self.default_profile = _Option(default_profile)
        self.saved = False

    def save_user_preferences(self):
        self.saved = True


def test_profile_description_explains_backend_and_mpi(monkeypatch):
    profile = SimpleNamespace(
        executor="ssh",
        backend_config=SimpleNamespace(name="psij"),
        host="cluster.example",
        psij_backend="slurm",
        psij_url=None,
        mpi=8,
        executable_dir="/opt/sprkkr",
        executable_suffix="_v8",
    )
    monkeypatch.setattr(
        profile_application,
        "resolve_sprkkr_profile",
        lambda name, *, configuration=None: profile,
    )

    text = profile_application.profile_description("cluster")

    assert "SSH to cluster.example + PSI/J (slurm)" in text
    assert "MPI: 8 processes" in text
    assert "/opt/sprkkr" in text
    assert "_v8" in text


def test_profile_store_uses_backend_read_only_contract():
    store = ExecutionProfileStore(_Config())

    drafts = store.drafts()

    assert drafts["ase"].read_only is True
    assert drafts["local"].read_only is False


def test_profile_store_saves_only_mutable_profiles():
    config = _Config()
    store = ExecutionProfileStore(config)
    drafts = store.drafts()
    drafts["local"].values["mpi"] = 12

    store.save(drafts)

    assert config.profiles.saved == {
        "local": {"executor": "local", "mpi": 12},
    }
    assert config.default_profile() is None
    assert config.saved


def test_profile_store_clears_default_when_that_profile_is_deleted():
    config = _Config(default_profile="local")
    store = ExecutionProfileStore(config)
    drafts = store.drafts()
    del drafts["local"]

    store.save(drafts)

    assert config.profiles.saved == {}
    assert config.default_profile() is None
    assert config.saved


def test_profile_store_description_uses_injected_configuration(monkeypatch):
    config = _Config()
    seen = []
    monkeypatch.setattr(
        profile_application,
        "profile_description",
        lambda name, *, configuration=None: seen.append((name, configuration)) or "ok",
    )

    assert ExecutionProfileStore(config).describe("local") == "ok"
    assert seen == [("local", config)]


def test_profile_editor_owns_creation_and_deletion_policy():
    editor = ExecutionProfileEditor(ExecutionProfileStore(_Config()))

    draft = editor.add("cluster")
    assert draft.values == {
        "executor": "local",
        "mpi": "auto",
        "mpi_warning": True,
    }

    with pytest.raises(ValueError, match="already exists or is reserved"):
        editor.add("cluster")
    with pytest.raises(ValueError, match="already exists or is reserved"):
        editor.add("ase")
    with pytest.raises(ValueError, match="read-only"):
        editor.delete("ase")

    editor.delete("cluster")
    assert "cluster" not in editor.drafts


def test_profile_description_distinguishes_direct_and_supervised(monkeypatch):
    from ase2sprkkr.sprkkr.profile import SPRKKRProfile

    for executor, backend in (("local", "direct"), ("ssh", "process")):
        profile = SPRKKRProfile(executor=executor, backend=backend, host="example.org")
        monkeypatch.setattr(
            profile_application,
            "resolve_sprkkr_profile",
            lambda name, *, configuration=None: profile,
        )
        assert backend.replace("process", "supervised") in (
            profile_application.profile_description("run")
        )
