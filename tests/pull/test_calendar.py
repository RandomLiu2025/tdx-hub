import pandas as pd
import pytest

from tdxhub.pull import TradingSession, day_to_calendar, minute_to_sessions


def day_frame(times):
    size = len(times)
    return pd.DataFrame(
        {
            "open": range(1, size + 1),
            "high": range(2, size + 2),
            "low": range(0, size),
            "close": [value + 0.5 for value in range(1, size + 1)],
            "volume": [100] * size,
            "amount": [1000] * size,
            "turnover": [1.0] * size,
            "float_stock": range(1000, 1000 + size),
            "total_stock": range(2000, 2000 + size),
        },
        index=pd.DatetimeIndex(times, name="datetime", tz="Asia/Shanghai"),
    )


def test_day_to_calendar_handles_iso_week_and_last_metadata():
    data = day_frame(["2026-01-05 15:00", "2025-12-29 15:00", "2026-01-02 15:00"])
    original = data.copy()

    result = day_to_calendar(data, "week")

    assert len(result) == 2
    assert result.iloc[0]["volume"] == 200
    assert result.iloc[0]["turnover"] == 2
    assert result.iloc[0]["float_stock"] == data.loc[
        pd.Timestamp("2026-01-02 15:00", tz="Asia/Shanghai"), "float_stock"
    ]
    assert result.index[0] == pd.Timestamp("2026-01-02 15:00", tz="Asia/Shanghai")
    pd.testing.assert_frame_equal(data, original)
    for period in ("month", "quarter", "year"):
        assert len(day_to_calendar(data, period)) == 2


def minute_frame(times, volumes=None):
    volumes = volumes or [1] * len(times)
    return pd.DataFrame(
        {
            "open": [1.0] * len(times),
            "high": [1.0] * len(times),
            "low": [1.0] * len(times),
            "close": [1.0] * len(times),
            "volume": volumes,
            "amount": volumes,
            "source": [""] * len(times),
            "is_approximate": [False] * len(times),
        },
        index=pd.DatetimeIndex(times, name="datetime", tz="Asia/Shanghai"),
    )


def test_minute_sessions_aligns_by_clock_not_row_count():
    data = minute_frame(["2026-01-05 09:31", "2026-01-05 09:35", "2026-01-05 09:36"], [1, 2, 3])

    result = minute_to_sessions(data, 5, [TradingSession("09:30", "11:30")])

    assert list(result["volume"]) == [3, 3]
    assert list(result.index) == [
        pd.Timestamp("2026-01-05 09:35", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-05 09:36", tz="Asia/Shanghai"),
    ]


def test_minute_sessions_preserves_opening_record_and_resets_after_break():
    data = minute_frame(
        [
            "2026-01-05 09:30",
            "2026-01-05 09:31",
            "2026-01-05 09:35",
            "2026-01-05 13:01",
            "2026-01-05 13:05",
        ],
        [10, 1, 1, 2, 2],
    )
    sessions = [TradingSession("09:30", "11:30"), TradingSession("13:00", "15:00")]

    result = minute_to_sessions(data, 5, sessions)

    assert list(result["volume"]) == [10, 2, 4]
    assert list(result.index.strftime("%H:%M")) == ["09:30", "09:35", "13:05"]


def test_minute_sessions_supports_overnight_and_rejects_invalid_data():
    data = minute_frame(["2026-01-05 21:01", "2026-01-06 00:00", "2026-01-06 00:01"], [1, 2, 3])
    result = minute_to_sessions(data, 240, [TradingSession("21:00", "02:30")])
    assert len(result) == 1
    assert result.iloc[0]["volume"] == 6

    with pytest.raises(ValueError, match="outside"):
        minute_to_sessions(data, 5, [TradingSession("09:30", "11:30")])
    with pytest.raises(ValueError, match="overlap"):
        minute_to_sessions([], 5, [TradingSession("09:30", "11:30"), TradingSession("10:00", "15:00")])
    with pytest.raises(ValueError, match="period"):
        day_to_calendar(day_frame([]), "bad")
