import numpy as np

from ase2sprkkr.common.grammar_types import Array, Integer, Real, Sequence, Table

from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_structure import (
    ValueShape,
    describe_repeated,
    describe_value,
)


def test_scalar_value_does_not_affect_shape():
    grammar = Real()

    assert describe_value(grammar, 1.0) is None
    assert describe_value(grammar, 2.0) is None
    assert describe_value(grammar, 1.0, editor="text") == ValueShape("leaf", "text")


def test_fixed_array_shape_tracks_missing_children_not_scalar_values():
    grammar = Array(Real(), length=3)

    incomplete = describe_value(grammar, [1.0, 2.0])
    other_incomplete = describe_value(grammar, [4.0, 5.0])
    complete = describe_value(grammar, [1.0, 2.0, 3.0])

    assert incomplete == other_incomplete
    assert incomplete != complete
    assert incomplete.kind == "array"
    assert incomplete.contains_draft
    assert not complete.contains_draft


def test_nested_shape_propagates_presentation_drafts():
    grammar = Sequence(Integer(), Array(Real(), length=2))

    complete = grammar.convert([1, [2.0, 3.0]])
    nested = describe_value(grammar.types[1], [2.0])

    assert not describe_value(grammar, complete).contains_draft
    assert nested.contains_draft


def test_sequence_shape_is_recursive():
    grammar = Sequence(Integer(), Array(Real(), length=2))

    first = grammar.convert([1, [2.0, 3.0]])
    second = grammar.convert([9, [8.0, 7.0]])

    assert describe_value(grammar, first) == describe_value(grammar, second)
    assert describe_value(grammar, None) == ValueShape("sequence-leaf")


def test_table_shape_tracks_rows_and_cell_shapes():
    grammar = Table(columns=[Integer(), Real()], header=False)

    one_row = np.array([[1.0, 2.0]])
    same_shape = np.array([[8.0, 9.0]])
    two_rows = np.array([[1.0, 2.0], [3.0, 4.0]])

    assert describe_value(grammar, one_row) == describe_value(grammar, same_shape)
    assert describe_value(grammar, one_row) != describe_value(grammar, two_rows)


def test_repeated_dict_shape_tracks_keys_without_promoting_append_draft():
    grammar = Array(Real(), length=2)

    first = describe_repeated(
        grammar,
        {"def": [1.0, 2.0], 2: [3.0, 4.0]},
        is_dict=True,
        default_value=[0.0, 0.0],
    )
    scalar_change = describe_repeated(
        grammar,
        {"def": [9.0, 8.0], 2: [7.0, 6.0]},
        is_dict=True,
        default_value=[0.0, 0.0],
    )
    extra_key = describe_repeated(
        grammar,
        {"def": [9.0, 8.0], 2: [7.0, 6.0], 3: [5.0, 4.0]},
        is_dict=True,
        default_value=[0.0, 0.0],
    )

    assert first == scalar_change
    assert first != extra_key
    # The empty append occurrence is presentation-only.  It must not mark the
    # represented model subtree as draft and force stable existing editors to
    # be rebuilt after scalar value changes.
    assert not first.contains_draft


def test_repeated_sequence_fixed_array_has_no_append_component_draft():
    grammar = Array(Real(), length=2)

    shape = describe_repeated(
        grammar,
        [[1.0, 2.0], [3.0, 4.0]],
        is_dict=False,
        default_value=None,
    )
    incomplete = describe_repeated(
        grammar,
        [[1.0], [3.0, 4.0]],
        is_dict=False,
        default_value=None,
    )

    assert not shape.contains_draft
    assert incomplete.contains_draft


def test_repeated_array_shape_ignores_whole_value_editor_for_children():
    grammar = Array(Real(), length=2)

    complete = describe_repeated(
        grammar,
        {"def": [1.0, 2.0]},
        is_dict=True,
        default_value=[0.0, 0.0],
        editor="text",
    )
    incomplete = describe_repeated(
        grammar,
        {"def": [1.0]},
        is_dict=True,
        default_value=[0.0, 0.0],
        editor="text",
    )

    assert complete != incomplete
    assert incomplete.contains_draft
