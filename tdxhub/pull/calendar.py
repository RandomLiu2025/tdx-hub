"""Calendar- and trading-session-aware bar aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from tdxhub.pull.merge import _aggregate_ohlcv

CalendarPeriod = Literal["week", "month", "quarter", "year"]


@dataclass(frozen=True)
class TradingSession:
    """A local exchange session, with an end before start meaning overnight."""

    start: int | str
    end: int | str

    def __post_init__(self) -> None:
        start = _minute_of_day(self.start, end=False)
        end = _minute_of_day(self.end, end=True)
        if start == end:
            raise ValueError("trading session start and end must differ")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


def day_to_calendar(
    data: pd.DataFrame,
    period: CalendarPeriod,
    *,
    timezone: str | None = None,
) -> pd.DataFrame:
    """Aggregate daily bars by local ISO week, month, quarter or year."""
    if period not in {"week", "month", "quarter", "year"}:
        raise ValueError(f"unsupported calendar period: {period!r}")
    frame = _normalize_frame(data, timezone)
    if frame.empty:
        return frame

    keys: list[tuple[int, ...]] = []
    for timestamp in frame.index:
        local = timestamp
        if period == "week":
            iso = local.isocalendar()
            keys.append((int(iso.year), int(iso.week)))
        elif period == "month":
            keys.append((local.year, local.month))
        elif period == "quarter":
            keys.append((local.year, (local.month - 1) // 3 + 1))
        else:
            keys.append((local.year,))
    return _aggregate_groups(frame, keys)


def minute_to_sessions(
    data: pd.DataFrame | list[Any],
    size: int,
    sessions: list[TradingSession],
    *,
    timezone: str | None = None,
) -> pd.DataFrame:
    """Aggregate minute bars into clock-aligned buckets without crossing sessions."""
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("minute period size must be a positive integer")
    normalized_sessions = [
        session if isinstance(session, TradingSession) else TradingSession(*session)
        for session in sessions
    ]
    if not normalized_sessions:
        raise ValueError("trading sessions must not be empty")
    _validate_sessions(normalized_sessions)
    if not isinstance(data, pd.DataFrame):
        if len(data) == 0:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="datetime"))
        raise TypeError("data must be a pandas DataFrame")
    frame = _normalize_frame(data, timezone)
    if frame.empty:
        return frame

    keys: list[tuple[int, int, int]] = []
    for timestamp in frame.index:
        current = _session_bucket(timestamp, size, normalized_sessions)
        if current is None:
            raise ValueError(f"bar {timestamp.isoformat()} is outside configured trading sessions")
        keys.append(current)
    return _aggregate_groups(frame, keys)


def _session_bucket(
    timestamp: pd.Timestamp,
    size: int,
    sessions: list[TradingSession],
) -> tuple[int, int, int] | None:
    day = timestamp.normalize()
    for session_index, session in enumerate(sessions):
        for back in (0, 1):
            anchor = day - pd.Timedelta(days=back)
            begin = anchor + pd.Timedelta(minutes=session.start)
            end_minute = session.end if session.end > session.start else session.end + 1440
            end = anchor + pd.Timedelta(minutes=end_minute)
            if not begin <= timestamp <= end:
                continue
            elapsed_seconds = int((timestamp - begin).total_seconds())
            bucket_index = -1 if elapsed_seconds == 0 else (elapsed_seconds - 1) // (size * 60)
            return int(begin.tz_convert("UTC").value), session_index, bucket_index
    return None


def _aggregate_groups(frame: pd.DataFrame, keys: list[tuple[int, ...]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    timestamps: list[pd.Timestamp] = []
    start = 0
    while start < len(frame):
        end = start + 1
        while end < len(frame) and keys[end] == keys[start]:
            end += 1
        group = frame.iloc[start:end]
        row = group.iloc[-1].to_dict()
        _aggregate_ohlcv(row, group)
        rows.append(row)
        timestamps.append(group.index[-1])
        start = end
    result = pd.DataFrame(rows, index=pd.DatetimeIndex(timestamps, name="datetime"))
    result.attrs = dict(frame.attrs)
    return result


def _normalize_frame(data: pd.DataFrame, timezone: str | None) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame")
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("bars must use a DatetimeIndex")
    frame = data.copy().sort_index(kind="stable")
    resolved_timezone = timezone or (str(frame.index.tz) if frame.index.tz is not None else "Asia/Shanghai")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(resolved_timezone)
    else:
        frame.index = frame.index.tz_convert(resolved_timezone)
    frame.index.name = "datetime"
    return frame


def _validate_sessions(sessions: list[TradingSession]) -> None:
    occupied = [False] * 1440
    for session in sessions:
        end = session.end if session.end > session.start else session.end + 1440
        for minute in range(session.start, end + 1):
            if minute == end and end - session.start == 1440:
                continue
            position = minute % 1440
            if occupied[position]:
                raise ValueError("trading sessions overlap")
            occupied[position] = True


def _minute_of_day(value: int | str, *, end: bool) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid trading session time: {value!r}")
    if isinstance(value, int):
        limit = 1440 if end else 1439
        if 0 <= value <= limit:
            return value
        raise ValueError(f"invalid trading session time: {value!r}")
    if isinstance(value, str):
        try:
            hour_text, minute_text = value.split(":", 1)
            hour, minute = int(hour_text), int(minute_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid trading session time: {value!r}") from exc
        if hour == 24 and minute == 0 and end:
            return 1440
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour * 60 + minute
    raise ValueError(f"invalid trading session time: {value!r}")
