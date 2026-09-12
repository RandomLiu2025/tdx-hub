"""Convert standard-market transaction records into approximate minute bars."""

from __future__ import annotations

import math
import re
from datetime import date as date_type
from datetime import datetime, time
from typing import Any

import pandas as pd

_DEFAULT_TIMEZONE = "Asia/Shanghai"
_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "order",
    "source",
    "volume_unit",
    "timezone",
    "is_approximate",
)
_TIME_ONLY = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$")


def trades_to_minutes(
    trades: pd.DataFrame,
    *,
    date: object,
    timezone: str = _DEFAULT_TIMEZONE,
) -> pd.DataFrame:
    """Build the Go-compatible 241 one-minute bars for one transaction day.

    Transaction volume is expressed in lots and converted to shares. Trades are
    assigned to the next compatible minute, with call-auction, midday, and close
    boundary clamping matching the Go implementation.
    """
    if not isinstance(trades, pd.DataFrame):
        raise TypeError("trades must be a pandas DataFrame")
    if trades.empty:
        raise ValueError("trades must not be empty")
    for column in ("time", "price"):
        if column not in trades:
            raise ValueError(f"trades must contain {column}")
    volume_column = "volume" if "volume" in trades else "vol" if "vol" in trades else None
    if volume_column is None:
        raise ValueError("trades must contain volume or vol")

    target_date = _date_value(date, timezone)
    frame = trades.copy(deep=True)
    timestamps = [_trade_timestamp(value, target_date, timezone) for value in frame["time"]]
    frame["_timestamp"] = pd.DatetimeIndex(timestamps)

    prices = _finite_numbers(frame["price"], "price")
    volumes = _finite_numbers(frame[volume_column], "volume")
    if (prices <= 0).any():
        raise ValueError("trade price must be positive")
    if (volumes < 0).any():
        raise ValueError("trade volume must be non-negative")
    if volumes.sum() <= 0:
        raise ValueError("trade volume total must be positive")
    if "num" in frame:
        orders = _finite_numbers(frame["num"], "num")
        if (orders < 0).any():
            raise ValueError("trade num must be non-negative")
    else:
        orders = pd.Series(0, index=frame.index, dtype="int64")

    frame["_price"] = prices
    frame["_volume"] = volumes
    frame["_order"] = orders
    frame = frame.sort_values("_timestamp", kind="stable")
    frame["_minute"] = [_minute_bucket(value) for value in frame["_timestamp"]]

    first_price = frame.iloc[0]["_price"]
    grouped = {minute: group for minute, group in frame.groupby("_minute", sort=False)}
    rows: list[dict[str, object]] = []
    index: list[pd.Timestamp] = []
    previous_close = first_price
    for minute in _minute_keys():
        group = grouped.get(minute)
        if group is None:
            open_price = high = low = close = previous_close
            volume = amount = order = 0
        else:
            values = group["_price"]
            open_price = values.iloc[0]
            high = values.max()
            low = values.min()
            close = values.iloc[-1]
            lot_volume = group["_volume"]
            volume = lot_volume.sum() * 100
            amount = (values * lot_volume * 100).sum()
            order = group["_order"].sum()
            previous_close = close
        rows.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
                "order": order,
                "source": "trade",
                "volume_unit": "shares",
                "timezone": str(timezone),
                "is_approximate": True,
            }
        )
        index.append(
            pd.Timestamp(
                datetime.combine(target_date, time(hour=minute // 60, minute=minute % 60)),
                tz=timezone,
            )
        )

    result = pd.DataFrame(rows, columns=_COLUMNS, index=pd.DatetimeIndex(index, name="datetime"))
    result.attrs = {"timezone": str(timezone), "volume_unit": "shares", "source": "trade"}
    return result


def empty_trade_minutes(timezone: str = _DEFAULT_TIMEZONE) -> pd.DataFrame:
    """Return an empty frame with the transaction-minute output schema."""
    result = pd.DataFrame(columns=_COLUMNS, index=pd.DatetimeIndex([], name="datetime", tz=timezone))
    result.attrs = {"timezone": str(timezone), "volume_unit": "shares", "source": "trade"}
    return result


def _date_value(value: Any, timezone: str) -> date_type:
    if isinstance(value, datetime):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(timezone)
        return timestamp.date()
    if isinstance(value, date_type):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return datetime.strptime(text, "%Y%m%d").date()
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid trade date") from exc
    if pd.isna(timestamp):
        raise ValueError("invalid trade date")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(timezone)
    return timestamp.date()


def _trade_timestamp(value: Any, target_date: date_type, timezone: str) -> pd.Timestamp:
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        raise ValueError("trade time must not be empty")

    clock: time
    supplied_date: date_type | None = None
    if isinstance(value, time):
        clock = value.replace(tzinfo=None)
    else:
        text = str(value).strip()
        match = _TIME_ONLY.fullmatch(text)
        if match is not None:
            try:
                clock = time(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
            except ValueError as exc:
                raise ValueError("invalid trade time") from exc
        else:
            try:
                timestamp = pd.Timestamp(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid trade time") from exc
            if pd.isna(timestamp):
                raise ValueError("invalid trade time")
            # Protocol timestamps can be tagged UTC while their wall-clock value
            # belongs to the requested Chinese trading day. Preserve that clock.
            supplied_date = timestamp.date()
            clock = timestamp.time().replace(tzinfo=None)

    if supplied_date is not None and supplied_date != target_date:
        raise ValueError("trade date does not match requested date")
    minute = clock.hour * 60 + clock.minute
    if not (565 <= minute <= 690 or 780 <= minute <= 900):
        raise ValueError("trade time is outside supported trading sessions")
    return pd.Timestamp(datetime.combine(target_date, clock), tz=timezone)


def _finite_numbers(values: pd.Series, name: str) -> pd.Series:
    try:
        numbers = pd.to_numeric(values, errors="raise")
        finite = not numbers.isna().any() and all(math.isfinite(float(value)) for value in numbers)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"trade {name} must be numeric") from exc
    if not finite:
        raise ValueError(f"trade {name} must be finite")
    return numbers


def _minute_bucket(timestamp: pd.Timestamp) -> int:
    minute = timestamp.hour * 60 + timestamp.minute
    minute = max(minute, 569) + 1
    if 690 < minute <= 780:
        minute = 690
    return min(minute, 900)


def _minute_keys() -> list[int]:
    return [*range(570, 691), *range(781, 901)]
