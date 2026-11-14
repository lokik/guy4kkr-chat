"""Memory-bounded LRU behavior independent of the Qt interface."""
from __future__ import annotations

from ase2sprkkr_gui.gui.application.result_cache import ResultLRU


def test_result_cache_evicts_least_recently_used_and_checks_versions():
    cache = ResultLRU(max_entries=2, max_bytes=100000)
    first, second, third = object(), object(), object()
    assert cache.store("first", ("v1",), first)
    assert cache.store("second", ("v1",), second)
    assert cache.lookup("first", ("v1",)) == (True, first)
    assert cache.store("third", ("v1",), third)
    assert cache.lookup("second", ("v1",)) == (False, None)
    assert cache.lookup("first", ("v2",)) == (False, None)
    assert cache.lookup("third", ("v1",)) == (True, third)


def test_result_cache_rejects_oversized_results_and_respects_byte_budget():
    cache = ResultLRU(max_entries=5, max_bytes=1000)
    assert cache.store("a", (1,), bytearray(500))
    assert cache.store("b", (1,), bytearray(500))
    assert cache.lookup("a", (1,)) == (False, None)
    assert cache.lookup("b", (1,))[0]
    assert not cache.store("too-big", (1,), bytearray(2000))
    assert cache.lookup("too-big", (1,)) == (False, None)


def test_result_cache_does_not_call_lazy_properties():
    class LazyResult:
        @property
        def data(self):
            raise AssertionError("Caching must not parse result properties")

    cache = ResultLRU()
    result = LazyResult()
    assert cache.store("result", (1,), result)
    assert cache.lookup("result", (1,)) == (True, result)


def test_result_cache_default_limits():
    cache = ResultLRU()
    assert cache.max_entries == 1024
    assert cache.max_bytes == 512 * 1024 * 1024
