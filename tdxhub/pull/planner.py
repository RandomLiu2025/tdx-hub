"""Pure helpers for planning incremental and missing time ranges."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, order=True)
class TimeRange:
    """A timezone-aware, half-open interval ``[start, end)``."""

    start: pd.Timestamp
    end: pd.Timestamp

    def __post_init__(self) -> None:
        start = pd.Timestamp(self.start)
        end = pd.Timestamp(self.end)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("TimeRange endpoints must include a timezone")
        if str(start.tzinfo) != str(end.tzinfo):
            raise ValueError("TimeRange endpoints must use the same timezone")
        if start >= end:
            raise ValueError("TimeRange start must be earlier than end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


def missing_ranges(requested: TimeRange, covered: Iterable[TimeRange]) -> list[TimeRange]:
    """Subtract covered intervals from a requested interval."""
    clipped: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for interval in covered:
        _ensure_compatible(requested, interval)
        start = max(requested.start, interval.start)
        end = min(requested.end, interval.end)
        if start < end:
            clipped.append((start, end))
    clipped.sort(key=lambda item: item[0])

    merged: list[list[pd.Timestamp]] = []
    for start, end in clipped:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    result: list[TimeRange] = []
    cursor = requested.start
    for start, end in merged:
        if cursor < start:
            result.append(TimeRange(cursor, start))
        cursor = max(cursor, end)
    if cursor < requested.end:
        result.append(TimeRange(cursor, requested.end))
    return result


def plan_incremental(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    last: pd.Timestamp | None,
    overlap: pd.Timedelta | str = "0s",
) -> TimeRange | None:
    """Plan a tail refresh, optionally overlapping the latest stored bar."""
    requested = TimeRange(pd.Timestamp(start), pd.Timestamp(end))
    if last is None:
        return requested
    latest = pd.Timestamp(last)
    if latest.tzinfo is None or str(latest.tzinfo) != str(requested.start.tzinfo):
        raise ValueError("last must use the requested timezone")
    duration = pd.Timedelta(overlap)
    if duration < pd.Timedelta(0):
        raise ValueError("overlap must not be negative")
    refresh_start = max(requested.start, latest - duration)
    if refresh_start >= requested.end:
        return None
    return TimeRange(refresh_start, requested.end)


def _ensure_compatible(left: TimeRange, right: TimeRange) -> None:
    if str(left.start.tzinfo) != str(right.start.tzinfo):
        raise ValueError("covered ranges must use the requested timezone")
