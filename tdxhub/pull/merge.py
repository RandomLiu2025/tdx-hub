"""Merge and aggregate normalized market bar frames."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def merge_bars(*frames: pd.DataFrame) -> pd.DataFrame:
    """Merge frames by datetime; a row from a later frame wins."""
    nonempty = [frame.copy() for frame in frames if frame is not None and not frame.empty]
    if not nonempty:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="datetime"))
    timezone = _validate_frames(nonempty)
    combined = pd.concat(nonempty, axis=0)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index(kind="stable")
    combined.index = pd.DatetimeIndex(combined.index, name="datetime")
    if timezone is not None and combined.index.tz is None:
        combined.index = combined.index.tz_localize(timezone)
    combined.attrs = dict(nonempty[-1].attrs)
    return combined


def merge_fallback(primary: pd.DataFrame, fallback: pd.DataFrame, *, source: str = "trade") -> pd.DataFrame:
    """Fill timestamps absent from primary with explicitly marked fallback bars."""
    if fallback is None or fallback.empty:
        return primary.copy()
    fallback_rows = fallback.copy()
    fallback_rows["source"] = source
    fallback_rows["is_approximate"] = True
    if primary is None or primary.empty:
        return merge_bars(fallback_rows)
    missing = fallback_rows.loc[~fallback_rows.index.isin(primary.index)]
    return merge_bars(missing, primary)


def to_period(data: pd.DataFrame, size: int) -> pd.DataFrame:
    """Aggregate each fixed group of ``size`` rows without calendar alignment."""
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("period size must be a positive integer")
    if data is None or data.empty or size == 1:
        return data.copy()
    _validate_frames([data])
    ordered = data.sort_index(kind="stable")
    rows: list[dict[str, object]] = []
    index: list[pd.Timestamp] = []
    for start in range(0, len(ordered), size):
        group = ordered.iloc[start : start + size]
        row = group.iloc[-1].to_dict()
        _aggregate_ohlcv(row, group)
        rows.append(row)
        index.append(group.index[-1])
    result = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name="datetime"))
    result.attrs = dict(data.attrs)
    return result


def _aggregate_ohlcv(row: dict[str, object], group: pd.DataFrame) -> None:
    operations = {
        "open": lambda values: values.iloc[0],
        "high": lambda values: values.max(),
        "low": lambda values: values.min(),
        "close": lambda values: values.iloc[-1],
        "volume": lambda values: values.sum(min_count=1),
        "amount": lambda values: values.sum(min_count=1),
        "turnover": lambda values: values.sum(min_count=1),
    }
    for column, operation in operations.items():
        if column in group:
            row[column] = operation(group[column])
    approximate = None
    if "is_approximate" in group:
        approximate = group["is_approximate"].fillna(False).astype(bool)
        row["is_approximate"] = bool(approximate.any())
    if "source" in group:
        sources = group["source"]
        if approximate is not None and approximate.any():
            sources = sources.loc[approximate]
        sources = [str(value) for value in sources if pd.notna(value) and str(value)]
        row["source"] = sources[-1] if sources else ""


def _validate_frames(frames: Iterable[pd.DataFrame]) -> str | None:
    timezone: str | None = None
    initialized = False
    for frame in frames:
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError("bars must use a DatetimeIndex")
        current = None if frame.index.tz is None else str(frame.index.tz)
        if not initialized:
            timezone = current
            initialized = True
        elif current != timezone:
            raise ValueError("all bars must use the same timezone")
    return timezone
