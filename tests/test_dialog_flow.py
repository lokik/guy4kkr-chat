from ase2sprkkr_gui.gui.misc.dialog_flow import DialogAction, chain_dialogs


def test_chain_dialogs_passes_previous_result_and_parent():
    parent = object()
    calls = []

    def first(*, parent):
        calls.append(("first", parent))
        return "first-result"

    def second(previous, *, parent, back):
        calls.append(("second", previous, parent, back))
        return "final-result"

    assert chain_dialogs(first, second, parent=parent) == "final-result"
    assert calls == [
        ("first", parent),
        ("second", "first-result", parent, True),
    ]


def test_chain_dialogs_back_reopens_previous_step():
    parent = object()
    first_results = iter(["first-result", "revised-result"])
    second_calls = 0

    def first(*, parent):
        return next(first_results)

    def second(previous, *, parent, back):
        nonlocal second_calls
        second_calls += 1
        if second_calls == 1:
            return DialogAction.BACK
        return f"{previous}-done"

    assert chain_dialogs(first, second, parent=parent) == "revised-result-done"
    assert second_calls == 2


def test_chain_dialogs_cancel_aborts_wizard():
    called = False

    def first(*, parent):
        return None

    def second(previous, *, parent, back):
        nonlocal called
        called = True
        return previous

    assert chain_dialogs(first, second) is None
    assert not called
