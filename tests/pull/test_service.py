import pandas as pd
import pytest

from tdxhub.pull import PullService, SQLiteStore, TimeRange

TZ = "Asia/Shanghai"
IDENTITY = {"market": "std", "code": "600000", "frequency": "1d", "adjustment": "none"}


def ts(value):
    return pd.Timestamp(value, tz=TZ)


def bars(*dates, closes=None):
    closes = closes or list(range(1, len(dates) + 1))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100] * len(dates),
            "amount": [1000] * len(dates),
            "source": ["tdx"] * len(dates),
            "volume_unit": ["shares"] * len(dates),
            "timezone": [TZ] * len(dates),
            "is_approximate": [False] * len(dates),
        },
        index=pd.DatetimeIndex(dates, tz=TZ, name="datetime"),
    )


class FakeFetcher:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def fetch(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response.copy()


def test_store_coverage_ranges_merge_and_remain_stream_isolated(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    store.mark_coverage(TimeRange(ts("2026-01-01"), ts("2026-01-03")), **IDENTITY)
    store.mark_coverage(TimeRange(ts("2026-01-03"), ts("2026-01-05")), **IDENTITY)
    store.mark_coverage(
        TimeRange(ts("2026-01-10"), ts("2026-01-11")),
        **{**IDENTITY, "adjustment": "qfq"},
    )

    assert store.covered_ranges(**IDENTITY) == [TimeRange(ts("2026-01-01"), ts("2026-01-05"))]
    assert store.covered_ranges(**{**IDENTITY, "adjustment": "qfq"}) == [
        TimeRange(ts("2026-01-10"), ts("2026-01-11"))
    ]


def test_sync_fetches_missing_ranges_in_order_and_marks_coverage(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    store.mark_coverage(TimeRange(ts("2026-01-03"), ts("2026-01-05")), **IDENTITY)
    fetcher = FakeFetcher([bars("2026-01-01"), bars("2026-01-05")])
    service = PullService(store, fetcher)

    result = service.sync(**IDENTITY, start=ts("2026-01-01"), end=ts("2026-01-07"))

    assert [(call["start"], call["end"]) for call in fetcher.calls] == [
        (ts("2026-01-01"), ts("2026-01-03")),
        (ts("2026-01-05"), ts("2026-01-07")),
    ]
    assert list(result.index) == [ts("2026-01-01"), ts("2026-01-05")]
    assert store.covered_ranges(**IDENTITY) == [TimeRange(ts("2026-01-01"), ts("2026-01-07"))]


def test_sync_refreshes_tail_with_overlap_without_eroding_on_empty(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    initial = bars("2026-01-01", "2026-01-02", "2026-01-03", closes=[1, 2, 3])
    store.upsert(
        initial,
        **IDENTITY,
        coverage=TimeRange(ts("2026-01-01"), ts("2026-01-04")),
    )
    empty_fetcher = FakeFetcher([pd.DataFrame()])

    result = PullService(store, empty_fetcher).sync(
        **IDENTITY,
        start=ts("2026-01-01"),
        end=ts("2026-01-04"),
        overlap="1D",
    )

    assert empty_fetcher.calls[0]["start"] == ts("2026-01-02")
    assert list(result["close"]) == [1, 2, 3]
    assert store.covered_ranges(**IDENTITY) == [TimeRange(ts("2026-01-01"), ts("2026-01-04"))]


def test_sync_fetch_failure_does_not_write_earlier_successful_gap(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    store.mark_coverage(TimeRange(ts("2026-01-03"), ts("2026-01-05")), **IDENTITY)
    fetcher = FakeFetcher([bars("2026-01-01"), ConnectionError("boom")])

    with pytest.raises(ConnectionError, match="boom"):
        PullService(store, fetcher).sync(**IDENTITY, start=ts("2026-01-01"), end=ts("2026-01-07"))

    assert store.query(**IDENTITY).empty
    assert store.covered_ranges(**IDENTITY) == [TimeRange(ts("2026-01-03"), ts("2026-01-05"))]


def test_sync_can_fill_missing_native_rows_with_approximate_fallback(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    native = FakeFetcher([bars("2026-01-01", closes=[10])])
    fallback = FakeFetcher([bars("2026-01-02", closes=[20])])

    result = PullService(store, native, fallback_fetcher=fallback).sync(
        **IDENTITY, start=ts("2026-01-01"), end=ts("2026-01-03")
    )

    assert list(result["close"]) == [10, 20]
    assert list(result["source"]) == ["tdx", "trade"]
    assert list(result["is_approximate"]) == [False, True]


def test_sync_replaces_revised_tail_bars(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    store.upsert(
        bars("2026-01-01", "2026-01-02", "2026-01-03", closes=[1, 2, 3]),
        **IDENTITY,
        coverage=TimeRange(ts("2026-01-01"), ts("2026-01-04")),
    )
    fetcher = FakeFetcher([bars("2026-01-02", "2026-01-03", closes=[20, 30])])

    result = PullService(store, fetcher).sync(
        **IDENTITY,
        start=ts("2026-01-01"),
        end=ts("2026-01-04"),
        overlap="1D",
    )

    assert list(result["close"]) == [1, 20, 30]
    assert fetcher.calls[0]["start"] == ts("2026-01-02")


def test_sync_historical_gap_does_not_delete_newer_bars(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    store.upsert(
        bars(
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
            closes=[1, 2, 3, 4, 5],
        ),
        **IDENTITY,
        coverage=TimeRange(ts("2026-01-01"), ts("2026-01-02")),
    )
    fetcher = FakeFetcher([bars("2026-01-02", "2026-01-03", closes=[20, 30])])

    result = PullService(store, fetcher).sync(
        **IDENTITY, start=ts("2026-01-01"), end=ts("2026-01-04")
    )

    assert list(result["close"]) == [1, 20, 30]
    assert list(store.query(**IDENTITY)["close"]) == [1, 20, 30, 4, 5]


@pytest.mark.parametrize("adjustment", ["qfq", "hfq", "invalid"])
def test_sync_rejects_adjusted_stream_before_fetching(tmp_path, adjustment):
    store = SQLiteStore(tmp_path / "bars.db")
    fetcher = FakeFetcher([bars("2026-01-01")])
    with pytest.raises(ValueError, match="adjustment"):
        PullService(store, fetcher).sync(
            **{**IDENTITY, "adjustment": adjustment}, start="2026-01-01", end="2026-01-03"
        )
    assert fetcher.calls == []
    assert not store.path.exists()


def test_sync_write_failure_rolls_back_every_gap_and_coverage(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    original = TimeRange(ts("2026-01-03"), ts("2026-01-05"))
    store.mark_coverage(original, **IDENTITY)
    malformed = bars("2026-01-05")
    malformed["close"] = [[1, 2]]  # Cannot bind this value to SQLite.
    fetcher = FakeFetcher([bars("2026-01-01"), malformed])
    with pytest.raises((ValueError, TypeError)):
        PullService(store, fetcher).sync(**IDENTITY, start="2026-01-01", end="2026-01-07")
    assert store.query(**IDENTITY).empty
    assert store.covered_ranges(**IDENTITY) == [original]


def test_sync_rejects_out_of_range_rows_without_marking_coverage(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    fetcher = FakeFetcher([bars("2026-01-09")])
    with pytest.raises(ValueError, match="range"):
        PullService(store, fetcher).sync(**IDENTITY, start="2026-01-01", end="2026-01-03")
    assert store.query(**IDENTITY).empty
    assert store.covered_ranges(**IDENTITY) == []


def test_sync_partial_tail_response_does_not_erase_existing_bars(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    store.upsert(bars("2026-01-01", "2026-01-02", "2026-01-03"), **IDENTITY)
    fetcher = FakeFetcher([bars("2026-01-02", closes=[20])])
    PullService(store, fetcher).sync(**IDENTITY, start="2026-01-02", end="2026-01-05")
    assert list(store.query(**IDENTITY)["close"]) == [1, 20, 3]


def test_sync_coverage_write_failure_rolls_back_rows_and_prior_interval(tmp_path, monkeypatch):
    import tdxhub.pull.store as store_module

    store = SQLiteStore(tmp_path / "bars.db")
    original = TimeRange(ts("2026-01-03"), ts("2026-01-05"))
    store.mark_coverage(original, **IDENTITY)
    mark_coverage = store_module._mark_coverage
    writes = []
    def fail_second(connection, identity, interval, **kwargs):
        writes.append(interval)
        if len(writes) == 2:
            raise RuntimeError("coverage write failed")
        return mark_coverage(connection, identity, interval, **kwargs)
    monkeypatch.setattr(store_module, "_mark_coverage", fail_second)
    fetcher = FakeFetcher([bars("2026-01-01"), bars("2026-01-05")])
    with pytest.raises(RuntimeError, match="coverage write failed"):
        PullService(store, fetcher).sync(**IDENTITY, start="2026-01-01", end="2026-01-07")
    assert len(writes) == 2
    assert store.query(**IDENTITY).empty
    assert store.covered_ranges(**IDENTITY) == [original]


def test_sync_native_rows_override_trade_fallback_and_persist_fallback_metadata(tmp_path):
    identity = {**IDENTITY, "frequency": "1m"}
    store = SQLiteStore(tmp_path / "bars.db")
    native = FakeFetcher([bars("2026-01-01 09:31", closes=[99])])
    fallback_rows = bars("2026-01-01 09:30", "2026-01-01 09:31", closes=[10, 11])
    fallback_rows["source"] = "trade"
    fallback_rows["is_approximate"] = True
    fallback = FakeFetcher([fallback_rows])

    result = PullService(store, native, fallback_fetcher=fallback).sync(
        **identity, start=ts("2026-01-01 09:30"), end=ts("2026-01-01 09:32")
    )

    assert list(result["close"]) == [10, 99]
    assert list(result["source"]) == ["trade", "tdx"]
    assert list(result["is_approximate"]) == [True, False]
    assert list(result["volume_unit"]) == ["shares", "shares"]


def test_sync_fallback_failure_does_not_write_primary_or_mark_coverage(tmp_path):
    store = SQLiteStore(tmp_path / "bars.db")
    original = TimeRange(ts("2026-01-03"), ts("2026-01-05"))
    store.mark_coverage(original, **IDENTITY)
    native = FakeFetcher([bars("2026-01-01"), bars("2026-01-05")])
    fallback = FakeFetcher([bars("2026-01-02"), ConnectionError("fallback failed")])

    with pytest.raises(ConnectionError, match="fallback failed"):
        PullService(store, native, fallback_fetcher=fallback).sync(
            **IDENTITY, start=ts("2026-01-01"), end=ts("2026-01-07")
        )

    assert store.query(**IDENTITY).empty
    assert store.covered_ranges(**IDENTITY) == [original]
