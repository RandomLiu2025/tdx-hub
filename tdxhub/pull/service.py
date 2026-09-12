"""Incremental pull orchestration."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tdxhub.pull.merge import merge_fallback
from tdxhub.pull.planner import TimeRange, missing_ranges, plan_incremental
from tdxhub.pull.store import DEFAULT_ADJUSTMENT, DEFAULT_TIMEZONE, SQLiteStore


class PullService:
    """Coordinate range planning, fetching and transactional range writes."""

    def __init__(self, store: SQLiteStore, fetcher: Any, *, fallback_fetcher: Any | None = None) -> None:
        self.store = store
        self.fetcher = fetcher
        self.fallback_fetcher = fallback_fetcher

    def sync(
        self,
        *,
        market: Any,
        code: str,
        frequency: Any,
        start: Any,
        end: Any,
        adjustment: str = DEFAULT_ADJUSTMENT,
        overlap: pd.Timedelta | str = "0s",
        timezone: str = DEFAULT_TIMEZONE,
    ) -> pd.DataFrame:
        """Synchronize and return bars in the half-open interval ``[start, end)``."""
        if adjustment != DEFAULT_ADJUSTMENT:
            raise ValueError("adjustment must be 'none'; adjusted incremental sync is not supported")
        requested = TimeRange(_timestamp(start, timezone), _timestamp(end, timezone))
        identity = {
            "market": str(market),
            "code": str(code),
            "frequency": str(frequency),
            "adjustment": adjustment,
        }
        covered = self.store.covered_ranges(**identity, timezone=timezone)
        ranges = missing_ranges(requested, covered)

        last = self.store.last_datetime(**identity, timezone=timezone)
        if last is not None:
            tail = plan_incremental(
                requested.start,
                requested.end,
                last=last,
                overlap=overlap,
            )
            if tail is not None:
                ranges.append(tail)
        ranges = _merge_ranges(ranges)

        # Fetch every planned interval before writing any of them.  A network
        # failure in a later gap therefore cannot leave an earlier gap stored.
        staged: list[tuple[TimeRange, pd.DataFrame]] = []
        for interval in ranges:
            arguments = {
                "market": market,
                "code": code,
                "frequency": frequency,
                "start": interval.start,
                "end": interval.end,
            }
            primary = _as_frame(self.fetcher.fetch(**arguments))
            if self.fallback_fetcher is None:
                combined = primary
            else:
                fallback = _as_frame(self.fallback_fetcher.fetch(**arguments))
                combined = merge_fallback(primary, fallback)
            if not combined.empty:
                staged.append((interval, _range_frame(combined, interval, timezone)))

        # Validate and persist the entire batch in one transaction. A partial
        # response may revise matching timestamps, never erase other tail rows.
        if staged:
            self.store.upsert(
                pd.concat([frame for _, frame in staged]),
                **identity,
                timezone=timezone,
                coverage=[interval for interval, _ in staged],
            )

        return self.store.query(
            **identity,
            start=requested.start,
            end=requested.end - pd.Timedelta(1, unit="ns"),
            timezone=timezone,
        )


def _as_frame(value: Any) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if not isinstance(value, pd.DataFrame):
        raise TypeError("fetcher.fetch must return a pandas DataFrame")
    return value


def _timestamp(value: Any, timezone: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(timezone)
    return timestamp.tz_convert(timezone)


def _merge_ranges(ranges: list[TimeRange]) -> list[TimeRange]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda interval: interval.start)
    merged = [ordered[0]]
    for interval in ordered[1:]:
        current = merged[-1]
        if interval.start > current.end:
            merged.append(interval)
        else:
            merged[-1] = TimeRange(current.start, max(current.end, interval.end))
    return merged


def _range_frame(frame: pd.DataFrame, interval: TimeRange, timezone: str) -> pd.DataFrame:
    result = frame.copy()
    if isinstance(result.index, pd.DatetimeIndex):
        index = result.index
    elif "datetime" in result:
        index = pd.DatetimeIndex(pd.to_datetime(result.pop("datetime"), errors="raise"))
    elif "date" in result:
        index = pd.DatetimeIndex(pd.to_datetime(result.pop("date"), errors="raise"))
    else:
        raise ValueError("fetched bars must have a datetime index or column")
    index = index.tz_localize(timezone) if index.tz is None else index.tz_convert(timezone)
    if index.hasnans or ((index < interval.start) | (index >= interval.end)).any():
        raise ValueError("fetched bars must be within the requested half-open range")
    result.index = pd.DatetimeIndex(index, name="datetime")
    return result
