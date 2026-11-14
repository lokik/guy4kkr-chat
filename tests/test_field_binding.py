"""Regressions for the Qt-independent guided field/session adapter."""
import numpy as np
import pytest
from ase2sprkkr.common.grammar_types import Array, Integer, Keyword, Real, Sequence, Table
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.input_parameters.field_binding import (
    ProjectedFieldBinding,
    array_item_binding,
    create_field_binding,
    mapping_value_binding,
    sequence_item_binding,
    table_cell_binding,
)
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.single_site_contour import SingleSiteContourPlugin
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement, field


def _secondary_ne_binding(session):
    placement = field(
        "ENERGY",
        "NE",
        "Single-site energy points",
        "integer",
        index=1,
    )
    return create_field_binding(session, placement, "energy")


def _contour_session():
    return InputParametersSession(
        InputParameters.create("scf"),
        plugins=(SingleSiteContourPlugin(),),
    )


def test_indexed_field_binding_replaces_only_its_component():
    session = _contour_session()
    session.set_value(("ENERGY", "SPLITSS"), True)
    before = list(session.value(("ENERGY", "NE")))
    binding = _secondary_ne_binding(session)

    binding.set_value(87)

    assert list(session.value(("ENERGY", "NE"))) == [before[0], 87]


def test_field_binding_displays_dormant_mesh_without_storing_it():
    session = _contour_session()
    session.set_value(("ENERGY", "SPLITSS"), True)
    binding = _secondary_ne_binding(session)
    binding.set_value(87)
    session.set_value(("ENERGY", "SPLITSS"), False)
    history_count = session.undo_stack.count()

    state = binding.read()

    assert state.value == 87
    assert len(session.result().ENERGY.NE()) == 1
    assert session.undo_stack.count() == history_count


def test_binding_reads_plugin_result_and_tracks_undo_redo_and_other_editors():
    path = ("SCF", "NITER")

    class NormalizeIterationsPlugin:
        def apply(self, _before, candidate, _dormant):
            if candidate.SCF.NITER() == 17:
                candidate.SCF.NITER.set(23)

    session = InputParametersSession(
        InputParameters.create("scf"),
        plugins=(NormalizeIterationsPlugin(),),
    )
    placement = field("SCF", "NITER", "Iterations")
    binding = create_field_binding(session, placement, "expert")

    binding.set_value(17)
    assert binding.read().value == 23

    session.undo_stack.undo()
    assert binding.read().value == InputParameters.create("scf").SCF.NITER()
    session.undo_stack.redo()
    assert binding.read().value == 23

    session.set_value(path, 31, source_page="guided")
    assert binding.read().value == 31


def test_projected_binding_keeps_plugin_failure_atomic():
    path = ("SCF", "NITER")

    class RejectIterationsPlugin:
        def apply(self, _before, candidate, _dormant):
            if candidate.SCF.NITER() == 19:
                raise RuntimeError("plugin rejected candidate")

    session = InputParametersSession(
        InputParameters.create("scf"),
        plugins=(RejectIterationsPlugin(),),
    )
    placement = field("SCF", "NITER", "Iterations")
    root = create_field_binding(session, placement, "expert")
    binding = ProjectedFieldBinding(
        root,
        placement,
        project_value=lambda value: value,
        replace_value=lambda _old, value: value,
        value_type=session.option(path)._definition.type,
        allows_unset=False,
    )
    before = session.value(path)

    with pytest.raises(RuntimeError, match="plugin rejected candidate"):
        binding.set_value(19)

    assert session.value(path) == before
    assert session.undo_stack.count() == 0


def test_array_type_without_explicit_index_exposes_the_whole_value():
    session = InputParametersSession(InputParameters.create("scf"))
    path = ("SCF", "MSPIN")
    placement = field(*path, "Spin moments", "literal")

    binding = create_field_binding(session, placement, "initial")

    np.testing.assert_array_equal(binding.read().value, session.value(path))


def test_dormant_only_plugin_state_is_generic_and_undoable():
    path = ("ENERGY", "NE")

    class DormantValuePlugin:
        def apply(self, _before, _candidate, dormant):
            dormant[(path, 1)] = 87

    session = InputParametersSession(
        InputParameters.create("scf"),
        plugins=(DormantValuePlugin(),),
    )
    binding = _secondary_ne_binding(session)

    assert session.mutate(lambda _candidate: None, text="Remember draft")
    assert binding.read().value == 87
    assert session.undo_stack.count() == 1

    session.undo_stack.undo()
    assert binding.read().value is None
    session.undo_stack.redo()
    assert binding.read().value == 87


def test_array_item_projection_preserves_siblings_and_numpy_type():
    session = InputParametersSession(InputParameters.create("scf"))
    path = ("ENERGY", "NE")
    root = create_field_binding(session, field(*path, "Energy points"), "expert")
    binding = array_item_binding(
        root,
        0,
        FieldPlacement(path, "First energy point"),
        allows_unset=False,
    )
    before = session.value(path).copy()

    assert binding.model_value_from(session.working_parameters) == before[0]
    assert binding.value_type is root.value_type.type
    candidate = session.result()
    binding.replace_in(candidate, 41)
    assert candidate.ENERGY.NE()[0] == 41
    assert np.array_equal(session.value(path), before)
    assert session.undo_stack.count() == 0
    binding.set_value(41)

    after = session.value(path)
    assert isinstance(after, np.ndarray)
    assert after.dtype == before.dtype
    assert after[0] == 41
    assert np.array_equal(after[1:], before[1:])


def test_array_item_projection_appends_numpy_backed_values():
    parameters = InputParameters.create("scf")
    option = parameters.TAU.CLURAD
    array_type = Array(Real(), min_length=1, max_length=4)
    option._definition.type = array_type
    option._definition.grammar_type = array_type
    option.set(np.array([1.5, 2.5]))
    session = InputParametersSession(parameters)
    path = ("TAU", "CLURAD")
    root = create_field_binding(session, field(*path, "Values"), "expert")
    append_binding = array_item_binding(
        root,
        2,
        FieldPlacement(path, "[2]"),
        append=True,
        allow_empty=True,
    )

    append_binding.set_value(3.5)

    result = session.value(path)
    assert isinstance(result, np.ndarray)
    np.testing.assert_array_equal(result, [1.5, 2.5, 3.5])
    assert session.undo_stack.count() == 1


def test_sequence_projection_reconstructs_named_sequence(monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    sequence_type = Sequence(
        Integer(),
        Real(),
        Keyword("A", "B"),
        names=("count", "energy", "mode"),
    )
    monkeypatch.setattr(option._definition, "type", sequence_type)
    monkeypatch.setattr(option._definition, "grammar_type", sequence_type)
    initial = sequence_type.convert([3, 2.5, "A"])
    option.set(initial)
    session = InputParametersSession(parameters)
    path = ("SCF", "NITER")
    root = create_field_binding(session, field(*path, "Sequence"), "expert")
    binding = sequence_item_binding(
        root,
        1,
        FieldPlacement(path, "Energy"),
        value_type=sequence_type.types[1],
    )

    assert binding.value_type is sequence_type.types[1]
    assert binding.model_value_from(session.working_parameters) == 2.5
    children = [
        sequence_item_binding(
            root,
            index,
            FieldPlacement(path, name),
            value_type=child_type,
        )
        for index, (name, child_type) in enumerate(zip(
            ("Count", "Energy", "Mode"), sequence_type.types
        ))
    ]
    assert [child.value_type for child in children] == sequence_type.types
    with pytest.raises(TypeError, match="does not support structural item access"):
        array_item_binding(root, 0, FieldPlacement(path, "Invalid array view"))
    binding.set_value(8.25)

    result = session.value(path)
    assert isinstance(result, sequence_type.value_type)
    assert result.count == 3
    assert result.energy == 8.25
    assert result.mode == "A"


def test_sequence_projection_preserves_plain_tuple_parent_type(monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    sequence_type = Sequence(Integer(), Real(), Keyword("A", "B"))
    monkeypatch.setattr(option._definition, "type", sequence_type)
    monkeypatch.setattr(option._definition, "grammar_type", sequence_type)
    option.set((3, 2.5, "A"))
    session = InputParametersSession(parameters)
    path = ("SCF", "NITER")
    root = create_field_binding(session, field(*path, "Sequence"), "expert")
    binding = sequence_item_binding(
        root,
        1,
        FieldPlacement(path, "Energy"),
        value_type=sequence_type.types[1],
    )

    binding.set_value(6.5)

    result = session.value(path)
    assert type(result) is tuple
    assert result == (3, 6.5, "A")


def test_table_cell_projection_preserves_supported_structured_rows(monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    table_type = Table(columns=[Integer(), Real()], header=False)
    monkeypatch.setattr(option._definition, "type", table_type)
    monkeypatch.setattr(option._definition, "grammar_type", table_type)
    initial = table_type.convert([(1, 2.5), (3, 4.5)])
    option.set(initial)
    session = InputParametersSession(parameters)
    path = ("SCF", "NITER")
    root = create_field_binding(session, field(*path, "Table"), "expert")
    binding = table_cell_binding(
        root,
        1,
        "f1",
        FieldPlacement(path, "Second row value"),
        value_type=table_type.sequence.types[1],
    )

    assert binding.model_value_from(session.working_parameters) == 4.5
    binding.set_value(9.25)

    result = session.value(path)
    assert isinstance(result, np.ndarray)
    assert result.dtype == initial.dtype
    assert result[0]["f0"] == initial[0]["f0"]
    assert result[0]["f1"] == initial[0]["f1"]
    assert result[1]["f0"] == initial[1]["f0"]
    assert result[1]["f1"] == 9.25


def test_defaultdict_projection_tracks_explicit_occurrences_and_actions():
    parameters = InputParameters.create("xas")
    path = ("MODE", "MDIR")
    default_value = np.array([0.0, 0.0, 1.0])
    override_value = np.array([1.0, 0.0, 0.0])
    parameters.MODE.MDIR.set({"def": default_value, 2: override_value})
    session = InputParametersSession(parameters)
    root = create_field_binding(session, field(*path, "Directions"), "expert")
    placement = FieldPlacement(path, "Occurrence")
    default_binding = mapping_value_binding(
        root,
        "def",
        placement,
        value_type=root.value_type,
        default=root.option.default_value,
    )
    override_binding = mapping_value_binding(
        root,
        2,
        placement,
        value_type=root.value_type,
        default=root.option.default_value,
    )
    missing_binding = mapping_value_binding(
        root,
        3,
        placement,
        value_type=root.value_type,
        default=root.option.default_value,
    )

    assert default_binding.read().explicit is True
    assert override_binding.read().explicit is True
    assert missing_binding.read().explicit is False
    missing_binding.set_value(np.array([0.0, 1.0, 0.0]))
    assert missing_binding.read().explicit is True
    missing_binding.update_value(lambda _value: None, text="Remove override")
    assert missing_binding.read().explicit is False
    assert 3 not in session.value(path)
    np.testing.assert_array_equal(session.value(path)["def"], default_value)
    np.testing.assert_array_equal(session.value(path)[2], override_value)


def test_defaultdict_projection_distinguishes_implicit_and_explicit_default():
    session = InputParametersSession(InputParameters.create("scf"))
    path = ("MODE", "SOC")
    root = create_field_binding(session, field(*path, "SOC"), "expert")
    binding = mapping_value_binding(
        root,
        "def",
        FieldPlacement(path, "Default SOC"),
        value_type=root.value_type,
        default=root.option.default_value,
    )

    state = binding.read()
    assert state.value == 1.0
    assert state.implicit_default
    assert state.explicit is False

    binding.set_value(0.8)
    state = binding.read()
    assert state.value == 0.8
    assert not state.implicit_default
    assert state.explicit is True


def _repeated_array_component(session, key, index):
    path = ("MODE", "MDIR")
    root = create_field_binding(session, field(*path, "Directions"), "expert")
    occurrence = mapping_value_binding(
        root,
        key,
        FieldPlacement(path, f"Occurrence {key}"),
        value_type=root.value_type,
        default=root.option.default_value,
    )
    return array_item_binding(
        occurrence,
        index,
        FieldPlacement(path, f"Component {index}"),
        allows_unset=False,
    )


def _directions_session(*, plugins=()):
    parameters = InputParameters.create("xas")
    parameters.MODE.MDIR.set({
        "def": [0.0, 0.0, 1.0],
        2: [1.0, 0.0, 0.0],
        3: [0.0, 1.0, 0.0],
    })
    return InputParametersSession(parameters, plugins=plugins)


def test_deep_repeated_array_projection_is_one_undoable_composition():
    session = _directions_session()
    binding = _repeated_array_component(session, 2, 1)

    binding.set_value(0.25)

    result = session.value(("MODE", "MDIR"))
    np.testing.assert_array_equal(result["def"], [0.0, 0.0, 1.0])
    np.testing.assert_array_equal(result[2], [1.0, 0.25, 0.0])
    np.testing.assert_array_equal(result[3], [0.0, 1.0, 0.0])
    assert session.undo_stack.count() == 1

    session.undo_stack.undo()
    np.testing.assert_array_equal(session.value(("MODE", "MDIR"))[2], [1.0, 0.0, 0.0])
    session.undo_stack.redo()
    np.testing.assert_array_equal(session.value(("MODE", "MDIR"))[2], [1.0, 0.25, 0.0])


def test_deep_projection_plugin_failure_changes_neither_session_nor_history():
    class RejectDirectionPlugin:
        def apply(self, _before, candidate, _dormant):
            if candidate.MODE.MDIR(all_values=True)[2][1] == 0.75:
                raise RuntimeError("reject projected candidate")

    session = _directions_session(plugins=(RejectDirectionPlugin(),))
    binding = _repeated_array_component(session, 2, 1)
    before = session.result().MODE.MDIR(all_values=True)

    with pytest.raises(RuntimeError, match="reject projected candidate"):
        binding.set_value(0.75)

    after = session.result().MODE.MDIR(all_values=True)
    np.testing.assert_array_equal(after[2], before[2])
    assert session.undo_stack.count() == 0
