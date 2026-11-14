from __future__ import annotations

import pytest

from ase2sprkkr_gui.gui.workflow.scf_status import (
    ScfProgress,
    classify_scf_progress,
    scf_progress_label,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (None, ScfProgress.NOT_STARTED),
        ("", ScfProgress.NOT_STARTED),
        ("START", ScfProgress.NOT_STARTED),
        ("itr", ScfProgress.ITERATING),
        ("ITR-BULK", ScfProgress.BULK),
        ("ITR-L-BULK", ScfProgress.LEFT_BULK),
        ("ITR-R-BULK", ScfProgress.RIGHT_BULK),
        ("ITR-I-ZONE", ScfProgress.INTERACTION_ZONE),
        ("future-status", ScfProgress.UNKNOWN),
    ),
)
def test_backend_scf_status_is_translated_once(status, expected):
    assert classify_scf_progress(status, converged=False) is expected


def test_explicit_convergence_overrides_backend_progress_string():
    assert classify_scf_progress("ITR", converged=True) is ScfProgress.CONVERGED


def test_unknown_backend_status_remains_visible_without_becoming_policy():
    progress = classify_scf_progress("future-status", converged=False)
    assert progress is ScfProgress.UNKNOWN
    assert scf_progress_label(progress, "future-status") == "FUTURE-STATUS"
