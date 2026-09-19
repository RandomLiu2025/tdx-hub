import pandas as pd
import pytest

from tdxhub.pull import TimeRange, missing_ranges, plan_incremental


def ts(value):
    return pd.Timestamp(value, tz="Asia/Shanghai")


def test_missing_ranges_merges_overlapping_and_adjacent_coverage():
    requested = TimeRange(ts("2026-01-01"), ts("2026-01-11"))
    covered = [
        TimeRange(ts("2026-01-03"), ts("2026-01-05")),
        TimeRange(ts("2026-01-04"), ts("2026-01-07")),
        TimeRange(ts("2026-01-09"), ts("2026-01-12")),
    ]

    assert missing_ranges(requested, covered) == [
        TimeRange(ts("2026-01-01"), ts("2026-01-03")),
        TimeRange(ts("2026-01-07"), ts("2026-01-09")),
    ]


def test_missing_ranges_clips_coverage_and_uses_half_open_ranges():
    requested = TimeRange(ts("2026-01-01"), ts("2026-01-02"))
    assert missing_ranges(requested, []) == [requested]
    assert missing_ranges(requested, [requested]) == []
    assert missing_ranges(requested, [TimeRange(ts("2025-01-01"), ts("2027-01-01"))]) == []


def test_plan_incremental_overlaps_latest_bar_for_refresh():
    result = plan_incremental(
        ts("2026-01-01"),
        ts("2026-01-10"),
        last=ts("2026-01-06"),
        overlap=pd.Timedelta(days=1),
    )
    assert result == TimeRange(ts("2026-01-05"), ts("2026-01-10"))
    assert plan_incremental(ts("2026-01-01"), ts("2026-01-10"), last=None) == TimeRange(
        ts("2026-01-01"), ts("2026-01-10")
    )


def test_invalid_ranges_are_rejected():
    with pytest.raises(ValueError, match="start"):
        TimeRange(ts("2026-01-02"), ts("2026-01-01"))
    with pytest.raises(ValueError, match="timezone"):
        TimeRange(pd.Timestamp("2026-01-01"), ts("2026-01-02"))
