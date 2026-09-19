from __future__ import annotations

import threading

import pandas as pd
import pytest

from tdxhub.cache import PersistentDataFrameCache


def test_persistent_dataframe_cache_shares_memory_and_returns_defensive_copies(tmp_path):
    cache = PersistentDataFrameCache()
    path = tmp_path / "frame.pkl"
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        frame = pd.DataFrame({"value": [[calls]]})
        frame.attrs["values"] = [calls]
        return frame

    first = cache.get(path, load, ttl=100)
    first.iloc[0, 0].append(99)
    first.attrs["values"].append(99)
    second = cache.get(path, load, ttl=100)

    assert calls == 1
    assert second.iloc[0, 0] == [1]
    assert second.attrs["values"] == [1]


def test_persistent_dataframe_cache_reuses_disk_after_memory_clear(tmp_path):
    cache = PersistentDataFrameCache()
    path = tmp_path / "frame.pkl"
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        return pd.DataFrame({"value": [calls]})

    cache.get(path, load, ttl=100)
    cache.clear_memory()
    result = cache.get(path, load, ttl=100)

    assert calls == 1
    assert result.iloc[0, 0] == 1


def test_persistent_dataframe_cache_refreshes_expired_or_explicit_cache(tmp_path, monkeypatch):
    cache = PersistentDataFrameCache()
    path = tmp_path / "frame.pkl"
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        return pd.DataFrame({"value": [calls]})

    first = cache.get(path, load, ttl=100)
    monkeypatch.setattr("tdxhub.cache.persistent.time.time", lambda: path.stat().st_mtime + 101)
    expired = cache.get(path, load, ttl=100)
    refreshed = cache.get(path, load, ttl=100, refresh=True)

    assert [first.iloc[0, 0], expired.iloc[0, 0], refreshed.iloc[0, 0]] == [1, 2, 3]


def test_persistent_dataframe_cache_returns_stale_data_when_scheduled_refresh_fails(tmp_path, monkeypatch):
    cache = PersistentDataFrameCache()
    path = tmp_path / "frame.pkl"
    cache.get(path, lambda: pd.DataFrame({"value": [1]}), ttl=100)
    monkeypatch.setattr("tdxhub.cache.persistent.time.time", lambda: path.stat().st_mtime + 101)

    def fail():
        raise RuntimeError("network unavailable")

    result = cache.get(path, fail, ttl=100)
    assert result.iloc[0, 0] == 1

    with pytest.raises(RuntimeError, match="network unavailable"):
        cache.get(path, fail, ttl=100, refresh=True)


def test_persistent_dataframe_cache_recovers_from_corrupt_file(tmp_path):
    cache = PersistentDataFrameCache()
    path = tmp_path / "frame.pkl"
    path.write_bytes(b"broken")

    result = cache.get(path, lambda: pd.DataFrame({"value": [42]}), ttl=100)

    assert result.iloc[0, 0] == 42
    assert pd.read_pickle(path).iloc[0, 0] == 42


def test_persistent_dataframe_cache_singleflights_concurrent_cold_loads(tmp_path):
    cache = PersistentDataFrameCache()
    path = tmp_path / "frame.pkl"
    calls = 0
    call_lock = threading.Lock()
    gate = threading.Barrier(5)
    results = []

    def load():
        nonlocal calls
        with call_lock:
            calls += 1
        return pd.DataFrame({"value": [42]})

    def run():
        gate.wait(timeout=2)
        results.append(cache.get(path, load, ttl=100))

    threads = [threading.Thread(target=run) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert calls == 1
    assert [result.iloc[0, 0] for result in results] == [42] * 5
    assert not list(tmp_path.glob("*.tmp"))


def test_persistent_dataframe_cache_clones_duplicate_object_columns(tmp_path):
    cache = PersistentDataFrameCache()
    path = tmp_path / "duplicate-columns.pkl"
    original = pd.DataFrame([[[1], [2]]], columns=["value", "value"])

    first = cache.get(path, lambda: original, ttl=100)
    first.iloc[0, 0].append(99)
    first.iloc[0, 1].append(98)
    second = cache.get(path, lambda: original, ttl=100)

    assert second.iloc[0, 0] == [1]
    assert second.iloc[0, 1] == [2]
