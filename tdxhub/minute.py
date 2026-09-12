"""Helpers for A-share minute timelines and the 241st auction bar."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

import pandas as pd

_AUCTION_CUTOFF = time(9, 30)
_A_SHARE_MINUTE_COUNT = 240


def _a_share_minute_index(trade_date: date) -> pd.DatetimeIndex:
    """Build the standard 240-point A-share intraday time axis."""
    day = pd.Timestamp(trade_date)
    morning = pd.date_range(
        day.replace(hour=9, minute=31),
        day.replace(hour=11, minute=30),
        freq="min",
    )
    afternoon = pd.date_range(
        day.replace(hour=13, minute=1),
        day.replace(hour=15, minute=0),
        freq="min",
    )
    return pd.DatetimeIndex(morning.append(afternoon), name="datetime")


def attach_minute_timestamps(points: pd.DataFrame, trade_date: Any) -> pd.DataFrame:
    """Attach the implicit A-share trading time to minute-time protocol rows.

    TDX minute-time packets contain only ordered price and volume points. The
    first 120 rows represent 09:31-11:30 and the remaining rows represent
    13:01-15:00. Partial responses are mapped from the start of this schedule.
    """
    result = points.copy(deep=True)
    original_attrs = dict(points.attrs)
    if len(result) > _A_SHARE_MINUTE_COUNT:
        raise ValueError(f"分时数据不能超过 {_A_SHARE_MINUTE_COUNT} 条")

    schedule = _a_share_minute_index(_trade_date(trade_date))[: len(result)]
    result["datetime"] = schedule
    result.index = schedule
    result.attrs = original_attrs
    return result


def _timestamps(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if isinstance(frame.index, pd.DatetimeIndex):
        return pd.DatetimeIndex(frame.index)
    if "datetime" not in frame.columns:
        raise ValueError("分钟 K 线必须使用 DatetimeIndex 或包含 datetime 字段")
    values = pd.to_datetime(frame["datetime"], errors="raise")
    return pd.DatetimeIndex(values, name=frame.index.name or "datetime")


def _trade_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return datetime.strptime(text, "%Y%m%d").date()
    return pd.Timestamp(value).date()


def _trade_time(value: Any) -> time | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = str(value).strip()
    for pattern in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            pass
    return None


def _number(value: Any) -> int | float:
    if value is None or pd.isna(value):
        return 0
    return value


def _datetime_value_like(value: Any, timestamp: pd.Timestamp) -> Any:
    """Keep the existing datetime column representation when adding a row."""
    if isinstance(value, str):
        match = re.search(r"\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?", value)
        if match is None:
            return timestamp.strftime("%Y-%m-%d %H:%M")
        replacement = "09:30"
        if match.group(0).count(":") == 2:
            replacement += ":00"
        return f"{value[:match.start()]}{replacement}{value[match.end():]}"
    if isinstance(value, datetime):
        return timestamp.to_pydatetime()
    return timestamp


def minute_241_dates(bars: pd.DataFrame) -> list[date]:
    """Return sorted trading dates that contain a 09:31 minute bar."""
    if bars.empty:
        return []
    timestamps = _timestamps(bars)
    return sorted(
        {
            timestamp.date()
            for timestamp in timestamps
            if not pd.isna(timestamp) and timestamp.hour == 9 and timestamp.minute == 31
        }
    )


def select_latest_minute_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Return an independent frame containing only the latest trading date."""
    original_attrs = dict(bars.attrs)
    if bars.empty:
        result = bars.copy(deep=True)
    else:
        timestamps = _timestamps(bars)
        valid_timestamps = [timestamp for timestamp in timestamps if not pd.isna(timestamp)]
        if not valid_timestamps:
            result = bars.iloc[0:0].copy(deep=True)
        else:
            latest_date = max(timestamp.date() for timestamp in valid_timestamps)
            positions = [
                position
                for position, timestamp in enumerate(timestamps)
                if not pd.isna(timestamp) and timestamp.date() == latest_date
            ]
            result = bars.iloc[positions].copy(deep=True)
    result.attrs = original_attrs
    return result


def build_minute_241(
    bars: pd.DataFrame,
    trades_by_date: Mapping[object, pd.DataFrame],
) -> pd.DataFrame:
    """Insert a 09:30 call-auction bar before each trading day's 09:31 bar.

    This follows the Go client's compatibility behavior, including inserting a
    zero-valued 09:30 bar when no valid pre-09:30 trade exists.
    """
    result = bars.copy(deep=True)
    original_attrs = dict(bars.attrs)
    if result.empty:
        result.attrs = original_attrs
        return result

    timestamps = _timestamps(result)
    result.index = timestamps
    result = result.sort_index(kind="stable")
    timestamps = pd.DatetimeIndex(result.index)

    if "vol" not in result.columns and "volume" in result.columns:
        result["vol"] = result["volume"]
    if "volume" not in result.columns and "vol" in result.columns:
        result["volume"] = result["vol"]
    if "vol" not in result.columns:
        result["vol"] = 0
        result["volume"] = 0
    if "amount" not in result.columns:
        result["amount"] = 0
    if "order" not in result.columns:
        result["order"] = 0
    if "last" not in result.columns:
        if "close" not in result.columns:
            raise ValueError("分钟 K 线缺少 close 字段")
        result["last"] = result["close"].shift(1).fillna(0)

    normalized_trades = {_trade_date(key): value for key, value in trades_by_date.items()}
    inserted = []
    target_positions = [
        position
        for position, timestamp in enumerate(timestamps)
        if not pd.isna(timestamp) and timestamp.hour == 9 and timestamp.minute == 31
    ]

    for position in target_positions:
        timestamp = timestamps[position]
        trades = normalized_trades.get(timestamp.date())
        price = volume = amount = order = 0
        if isinstance(trades, pd.DataFrame) and not trades.empty:
            first = trades.iloc[0]
            first_time = _trade_time(first.get("time"))
            if first_time is not None and first_time < _AUCTION_CUTOFF:
                price = _number(first.get("price"))
                volume = _number(first.get("vol", first.get("volume")))
                order = _number(first.get("num"))
                amount = price * volume * 100

        auction_time = timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
        auction = result.iloc[position].copy()
        previous = _number(auction["last"])
        for column in ("open", "high", "low", "close"):
            if column not in result.columns:
                raise ValueError(f"分钟 K 线缺少 {column} 字段")
            auction[column] = price
        auction["vol"] = volume
        auction["volume"] = volume
        auction["amount"] = amount
        auction["order"] = order
        auction["last"] = previous
        if "datetime" in result.columns:
            auction["datetime"] = _datetime_value_like(auction["datetime"], auction_time)
        for column, value in (
            ("year", auction_time.year),
            ("month", auction_time.month),
            ("day", auction_time.day),
            ("hour", auction_time.hour),
            ("minute", auction_time.minute),
        ):
            if column in result.columns:
                auction[column] = value
        inserted.append(pd.DataFrame([auction], index=pd.DatetimeIndex([auction_time])))

        result.iloc[position, result.columns.get_loc("last")] = price
        for column, deduction in (("vol", volume), ("volume", volume), ("amount", amount), ("order", order)):
            column_position = result.columns.get_loc(column)
            current = _number(result.iloc[position, column_position])
            result.iloc[position, column_position] = max(0, current - deduction)

    if inserted:
        result = pd.concat([result, *inserted]).sort_index(kind="stable")
    result.index.name = bars.index.name
    result.attrs = original_attrs
    return result
