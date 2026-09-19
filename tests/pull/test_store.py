import sqlite3

import pandas as pd
import pytest

from tdxhub.pull import SQLiteStore, TimeRange

IDENTITY = {"market": "std", "code": "600000", "frequency": "1d", "adjustment": "none"}


def bars(dates, closes, *, source="tdx", approximate=False):
    values = [float(value) for value in closes]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "close": values,
            "volume": [100 * (index + 1) for index in range(len(values))],
            "amount": [1000.0 * (index + 1) for index in range(len(values))],
            "source": source,
            "is_approximate": approximate,
        },
        index=pd.DatetimeIndex(dates, name="datetime", tz="Asia/Shanghai"),
    )


def test_empty_write_and_read_do_not_create_database(tmp_path):
    path = tmp_path / "bars.db"
    store = SQLiteStore(path)

    assert store.upsert(pd.DataFrame(), **IDENTITY) == 0
    assert store.query(**IDENTITY).empty
    assert store.coverage(**IDENTITY) is None
    assert store.last_datetime(**IDENTITY) is None
    assert not path.exists()


def test_upsert_query_and_stream_isolation(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    original = bars(["2026-01-05 15:00", "2026-01-06 15:00"], [10, 11])

    assert store.upsert(original, **IDENTITY) == 2
    changed = bars(["2026-01-06 15:00", "2026-01-07 15:00"], [99, 12])
    assert store.upsert(changed, **IDENTITY) == 2
    store.upsert(changed, market="std", code="600000", frequency="1d", adjustment="qfq")

    result = store.query(
        **IDENTITY,
        start="2026-01-06 00:00",
        end="2026-01-07 23:59",
    )
    assert list(result["close"]) == [99.0, 12.0]
    assert str(result.index.tz) == "Asia/Shanghai"
    assert result.attrs == {
        **IDENTITY,
        "timezone": "Asia/Shanghai",
        "volume_unit": "shares",
    }
    assert len(store.query(**IDENTITY)) == 3
    assert len(store.query(**{**IDENTITY, "adjustment": "qfq"})) == 2

    coverage = store.coverage(**IDENTITY)
    assert coverage.count == 3
    assert coverage.start == pd.Timestamp("2026-01-05 15:00", tz="Asia/Shanghai")
    assert coverage.end == pd.Timestamp("2026-01-07 15:00", tz="Asia/Shanghai")
    assert store.last_datetime(**IDENTITY) == coverage.end


def test_replace_from_is_atomic_and_does_not_erode_on_empty_input(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    original = bars(
        ["2026-01-05 15:00", "2026-01-06 15:00", "2026-01-07 15:00"],
        [10, 11, 12],
    )
    store.upsert(original, **IDENTITY)

    assert store.upsert(pd.DataFrame(), **IDENTITY, replace_from="2026-01-06") == 0
    assert list(store.query(**IDENTITY)["close"]) == [10.0, 11.0, 12.0]

    replacement = bars(["2026-01-06 15:00", "2026-01-08 15:00"], [21, 23], source="refresh")
    store.upsert(replacement, **IDENTITY, replace_from="2026-01-06")
    result = store.query(**IDENTITY)
    assert list(result["close"]) == [10.0, 21.0, 23.0]
    assert list(result["source"]) == ["tdx", "refresh", "refresh"]


def test_failed_replace_rolls_back_deleted_tail(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    original = bars(["2026-01-05 15:00", "2026-01-06 15:00"], [10, 11])
    store.upsert(original, **IDENTITY)
    duplicate = bars(["2026-01-06 15:00", "2026-01-06 15:00"], [20, 21])

    with pytest.raises(sqlite3.IntegrityError):
        store.upsert(duplicate, **IDENTITY, replace_from="2026-01-06")

    result = store.query(**IDENTITY)
    assert list(result["close"]) == [10.0, 11.0]


def test_failed_replace_rolls_back_coverage_change(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    original_coverage = TimeRange(
        pd.Timestamp("2026-01-05", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-07", tz="Asia/Shanghai"),
    )
    original = bars(["2026-01-05 15:00", "2026-01-06 15:00"], [10, 11])
    store.upsert(original, **IDENTITY, coverage=original_coverage)
    duplicate = bars(["2026-01-06 15:00", "2026-01-06 15:00"], [20, 21])

    with pytest.raises(sqlite3.IntegrityError):
        store.upsert(
            duplicate,
            **IDENTITY,
            replace_from="2026-01-06",
            coverage=TimeRange(
                pd.Timestamp("2026-01-06", tz="Asia/Shanghai"),
                pd.Timestamp("2026-01-08", tz="Asia/Shanghai"),
            ),
        )

    assert list(store.query(**IDENTITY)["close"]) == [10.0, 11.0]
    assert store.covered_ranges(**IDENTITY) == [original_coverage]


def test_large_batch_metadata_and_context_manager(tmp_path):
    index = pd.date_range("2026-01-01 09:31", periods=300, freq="min", tz="Asia/Shanghai")
    frame = bars(index, range(300), source="trade", approximate=True)

    with SQLiteStore(tmp_path / "bars.db", batch_size=37) as store:
        assert store.upsert(frame, market="std", code="000001", frequency="1m") == 300
        result = store.query(market="std", code="000001", frequency="1m")

    assert len(result) == 300
    assert set(result["source"]) == {"trade"}
    assert set(result["volume_unit"]) == {"shares"}
    assert set(result["timezone"]) == {"Asia/Shanghai"}
    assert set(result["is_approximate"]) == {True}
