import pytest

from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree import ExpertInputTreeEditor
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_renderer import ExpertTreeRole


class _Item:
    def __init__(self, related_paths=()):
        self.related_paths = related_paths

    def data(self, _column, role):
        if role == ExpertTreeRole.RELATED_PATHS:
            return self.related_paths
        return None


class _EditorContext:
    def __init__(self, parameters=None):
        self.parameters = {} if parameters is None else parameters


class _UnchangedOption:
    def is_changed(self):
        return False


def test_changed_state_does_not_hide_option_error():
    class BrokenOption:
        def is_changed(self):
            raise RuntimeError("comparator bug")

    with pytest.raises(RuntimeError, match="comparator bug"):
        ExpertInputTreeEditor._update_changed_style(
            _EditorContext(),
            BrokenOption(),
            _Item(),
            refresh_filter=False,
        )


def test_changed_state_does_not_hide_related_path_error():
    with pytest.raises(KeyError):
        ExpertInputTreeEditor._update_changed_style(
            _EditorContext(),
            _UnchangedOption(),
            _Item((("missing",),)),
            refresh_filter=False,
        )
