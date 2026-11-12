from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_presentation import present_result_tree
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.workspace import EmptySpheresState
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Value:
    info = ""

    def __init__(self, name: str):
        self.display_name = name

    def value_label(self) -> str:
        return self.display_name

    @staticmethod
    def actions() -> tuple[str, ...]:
        return ()


def _result(task: str, name: str, *, produces_potential: bool | None = None):
    if produces_potential is None:
        produces_potential = task.lower() == "scf"
    return SimpleNamespace(
        task_name=task,
        produces_potential=produces_potential,
        output_file=f"{name}.out",
        output_values={"value": _Value(name)},
    )


def _widget() -> ResultActionsWidget:
    return ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )


def _set_store(widget: ResultActionsWidget, store: ResultStore) -> None:
    widget.set_model(
        present_result_tree(
            store,
            current_structure_id=None,
            current_state_id=None,
        )
    )


def test_empty_spheres_breaks_potential_source_provenance():
    store = ResultStore()
    structure_id, root = store.new_structure_state(Atoms("Fe"), potential_path=None)
    scf = store.add_result(
        _result("scf", "scf"),
        structure_id=structure_id,
        input_state_id=root,
        input_parameters=object(),
        directory="run",
        output_atoms=Atoms("Fe"),
        output_potential_path="Fe.pot",
    )
    scf_state = scf.output_state_id
    assert scf_state is not None
    assert store.potential_source_result(scf_state) is None

    empty_spheres_state = EmptySpheresState(count=1)
    empty_spheres = store.add_result(
        EmptySpheresResult(found=1),
        structure_id=structure_id,
        input_state_id=scf_state,
        input_parameters={},
        directory="run",
        output_atoms=Atoms("FeX"),
        output_potential_path=None,
        output_empty_spheres=empty_spheres_state,
    )
    empty_state = empty_spheres.output_state_id
    assert empty_state is not None
    assert store.state(empty_state).empty_spheres == empty_spheres_state
    assert store.potential_source_result(empty_state) is None

    dos = store.add_result(
        _result("dos", "dos"),
        structure_id=structure_id,
        input_state_id=empty_state,
        input_parameters=object(),
        directory="run",
    )

    _application = QApplication.instance() or QApplication([])
    widget = _widget()
    _set_store(widget, store)
    structure = widget._selector.topLevelItem(0)
    labels = [structure.child(i).text(0).split(" — ", 1)[0] for i in range(3)]
    assert labels == ["SCF", "Empty spheres", "DOS"]
    assert structure.child(0).childCount() == 0
    assert widget._find_result_item(dos.id).parent() is structure
    widget.close()


def test_explicit_potential_replacement_does_not_inherit_old_source(tmp_path):
    first = tmp_path / "first.pot"
    first.write_text("first")
    external = tmp_path / "external.pot"
    external.write_text("external")

    store = ResultStore()
    structure_id, root = store.new_structure_state(Atoms("Fe"), potential_path=None)
    scf = store.add_result(
        _result("scf", "scf"),
        structure_id=structure_id,
        input_state_id=root,
        input_parameters=object(),
        directory="run",
        output_atoms=Atoms("Fe"),
        output_potential_path=str(first),
    )
    scf_state = scf.output_state_id
    assert scf_state is not None
    assert store.potential_source_result(scf_state) is scf

    replacement = store.new_child_state(
        scf_state,
        potential_path=str(external),
    )

    assert store.state(replacement).potential_path == str(external)
    assert store.potential_source_result(replacement) is None


def test_native_result_using_imported_scf_stays_under_import_directory(tmp_path):
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    directory = str(tmp_path / "imported")
    potential = Path(directory) / "Fe.pot"
    potential.parent.mkdir()
    potential.write_text("potential")
    imported_scf = store.add_external_result(
        _result("scf", "imported"),
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=directory,
        output_path=Path(directory) / "scf.out",
        potential_path=potential,
    )
    state_id = imported_scf.output_state_id
    assert state_id is not None
    assert imported_scf.imported
    assert store.potential_source_result(state_id) is imported_scf

    dos = store.add_result(
        _result("dos", "native"),
        structure_id=imported_scf.structure_id,
        input_state_id=state_id,
        input_parameters=object(),
        directory="new-run",
    )

    widget = _widget()
    _set_store(widget, store)

    assert widget._selector.topLevelItemCount() == 1
    directory_item = widget._selector.topLevelItem(0)
    assert directory_item.text(0) == directory
    assert directory_item.childCount() == 1
    scf_item = directory_item.child(0)
    assert scf_item.text(0).startswith("SCF")
    assert scf_item.childCount() == 1
    assert scf_item.child(0).text(0).startswith("DOS")
    assert widget._find_result_item(dos.id).parent() is scf_item
    widget.close()


def test_hidden_import_only_structure_does_not_consume_formula_number(tmp_path):
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    directory = str(tmp_path / "imported")
    potential = Path(directory) / "Fe.pot"
    potential.parent.mkdir()
    potential.write_text("potential")
    imported_scf = store.add_external_result(
        _result("scf", "imported"),
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=directory,
        output_path=Path(directory) / "scf.out",
        potential_path=potential,
    )
    imported_state = imported_scf.output_state_id
    assert imported_state is not None
    store.add_result(
        _result("dos", "native-from-import"),
        structure_id=imported_scf.structure_id,
        input_state_id=imported_state,
        input_parameters=object(),
        directory="new-run",
    )

    visible_structure, visible_state = store.new_structure_state(
        Atoms("Fe"),
        potential_path=None,
    )
    store.add_result(
        _result("dos", "visible"),
        structure_id=visible_structure,
        input_state_id=visible_state,
        input_parameters=object(),
        directory="visible-run",
    )

    widget = _widget()
    _set_store(widget, store)

    assert widget._selector.topLevelItemCount() == 2
    assert widget._selector.topLevelItem(0).text(0) == "Fe"
    assert widget._selector.topLevelItem(1).text(0) == directory
    widget.close()
