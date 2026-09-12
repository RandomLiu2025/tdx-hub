"""SQLite-backed normalized market bar storage."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from tdxhub.pull.planner import TimeRange

DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_ADJUSTMENT = "none"
DEFAULT_VOLUME_UNIT = "shares"

_DATA_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
    "float_stock",
    "total_stock",
    "source",
    "volume_unit",
    "timezone",
    "is_approximate",
)
_NUMERIC_COLUMNS = _DATA_COLUMNS[:9]
_IDENTITY_COLUMNS = ("market", "code", "frequency", "adjustment")


@dataclass(frozen=True)
class Coverage:
    """The first, last and number of stored bars for one logical stream."""

    start: pd.Timestamp
    end: pd.Timestamp
    count: int


class SQLiteStore:
    """Store normalized bars in one SQLite database.

    A stream is identified by market, code, frequency and adjustment. Datetimes
    are persisted as UTC nanoseconds while their display timezone is retained.
    Empty writes and reads against a missing path do not create a database.
    """

    def __init__(self, path: str | Path, *, batch_size: int = 100) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be greater than zero")
        self.path = Path(path).expanduser()
        self.batch_size = int(batch_size)
        self._closed = False

    def __enter__(self) -> SQLiteStore:
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True

    def upsert(
        self,
        data: pd.DataFrame,
        *,
        market: str,
        code: str,
        frequency: str,
        adjustment: str = DEFAULT_ADJUSTMENT,
        replace_from: Any | None = None,
        timezone: str | None = None,
        source: str = "",
        volume_unit: str = DEFAULT_VOLUME_UNIT,
        is_approximate: bool = False,
        coverage: TimeRange | list[TimeRange] | None = None,
    ) -> int:
        """Insert or update bars and return the number of input rows.

        When ``replace_from`` is set, the tail of this stream is deleted and
        the new rows are inserted in the same transaction. Duplicate input
        datetimes then fail the insert and roll the deletion back. Empty input
        is always a no-op, including when ``replace_from`` is provided.
        Coverage intervals are committed atomically with all rows.
        """
        self._ensure_open()
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data must be a pandas DataFrame")
        if data.empty:
            return 0

        identity = _normalize_identity(market, code, frequency, adjustment)
        rows, resolved_timezone = _frame_rows(
            data,
            timezone=timezone,
            source=source,
            volume_unit=volume_unit,
            is_approximate=is_approximate,
        )
        intervals = [] if coverage is None else [coverage] if isinstance(coverage, TimeRange) else list(coverage)
        delete_from = None
        if replace_from is not None:
            delete_from = _timestamp_ns(replace_from, resolved_timezone)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            _initialize(connection)
            with connection:
                if delete_from is not None:
                    connection.execute(
                        """
                        DELETE FROM bars
                        WHERE market = ? AND code = ? AND frequency = ?
                          AND adjustment = ? AND datetime_ns >= ?
                        """,
                        (*identity, delete_from),
                    )
                statement = _INSERT if delete_from is not None else _UPSERT
                values = [(*identity, *row) for row in rows]
                for start in range(0, len(values), self.batch_size):
                    connection.executemany(statement, values[start : start + self.batch_size])
                for interval in intervals:
                    _mark_coverage(
                        connection,
                        identity,
                        interval,
                        timezone=resolved_timezone,
                        source=source,
                        is_approximate=is_approximate,
                    )
        finally:
            connection.close()
        return len(rows)

    def query(
        self,
        *,
        market: str,
        code: str,
        frequency: str,
        adjustment: str = DEFAULT_ADJUSTMENT,
        start: Any | None = None,
        end: Any | None = None,
        timezone: str | None = None,
    ) -> pd.DataFrame:
        """Return one stream in ascending datetime order; bounds are inclusive."""
        self._ensure_open()
        identity = _normalize_identity(market, code, frequency, adjustment)
        if not self.path.is_file():
            return _empty_frame(identity, timezone or DEFAULT_TIMEZONE)

        clauses = [f"{name} = ?" for name in _IDENTITY_COLUMNS]
        parameters: list[Any] = list(identity)
        query_timezone = timezone or self._stream_timezone(identity) or DEFAULT_TIMEZONE
        if start is not None:
            clauses.append("datetime_ns >= ?")
            parameters.append(_timestamp_ns(start, query_timezone))
        if end is not None:
            clauses.append("datetime_ns <= ?")
            parameters.append(_timestamp_ns(end, query_timezone))

        connection = sqlite3.connect(self.path)
        try:
            cursor = connection.execute(
                f"""
                SELECT datetime_ns, {", ".join(_DATA_COLUMNS)}
                FROM bars
                WHERE {" AND ".join(clauses)}
                ORDER BY datetime_ns ASC
                """,
                parameters,
            )
            records = cursor.fetchall()
        finally:
            connection.close()
        if not records:
            return _empty_frame(identity, query_timezone)

        result = pd.DataFrame.from_records(records, columns=("datetime_ns", *_DATA_COLUMNS))
        utc_index = pd.to_datetime(result.pop("datetime_ns"), unit="ns", utc=True)
        result.index = pd.DatetimeIndex(utc_index).tz_convert(query_timezone)
        result.index.name = "datetime"
        result["is_approximate"] = result["is_approximate"].astype(bool)
        result.attrs = _attrs(identity, query_timezone, _single_value(result["volume_unit"], DEFAULT_VOLUME_UNIT))
        return result

    def coverage(
        self,
        *,
        market: str,
        code: str,
        frequency: str,
        adjustment: str = DEFAULT_ADJUSTMENT,
        timezone: str | None = None,
    ) -> Coverage | None:
        """Return min/max/count for a stream without materializing its bars."""
        self._ensure_open()
        identity = _normalize_identity(market, code, frequency, adjustment)
        if not self.path.is_file():
            return None
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                """
                SELECT MIN(datetime_ns), MAX(datetime_ns), COUNT(*), MIN(timezone)
                FROM bars
                WHERE market = ? AND code = ? AND frequency = ? AND adjustment = ?
                """,
                identity,
            ).fetchone()
        finally:
            connection.close()
        if row is None or not row[2]:
            return None
        output_timezone = timezone or row[3] or DEFAULT_TIMEZONE
        return Coverage(
            start=_ns_timestamp(row[0], output_timezone),
            end=_ns_timestamp(row[1], output_timezone),
            count=int(row[2]),
        )

    def last_datetime(self, **identity: Any) -> pd.Timestamp | None:
        """Return the latest datetime for a stream, or ``None`` when empty."""
        coverage = self.coverage(**identity)
        return None if coverage is None else coverage.end

    def mark_coverage(
        self,
        interval: TimeRange,
        *,
        market: str,
        code: str,
        frequency: str,
        adjustment: str = DEFAULT_ADJUSTMENT,
        source: str = "",
        is_approximate: bool = False,
    ) -> None:
        """Record a successfully checked half-open interval.

        Adjacent or overlapping ranges with the same provenance are merged.
        Empty fetches should not call this method.
        """
        self._ensure_open()
        identity = _normalize_identity(market, code, frequency, adjustment)
        timezone = _timezone_name(interval.start.tz) or DEFAULT_TIMEZONE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            _initialize(connection)
            with connection:
                _mark_coverage(
                    connection,
                    identity,
                    interval,
                    timezone=timezone,
                    source=source,
                    is_approximate=is_approximate,
                )
        finally:
            connection.close()

    def covered_ranges(
        self,
        *,
        market: str,
        code: str,
        frequency: str,
        adjustment: str = DEFAULT_ADJUSTMENT,
        timezone: str | None = None,
    ) -> list[TimeRange]:
        """Return merged successfully checked intervals for one stream."""
        self._ensure_open()
        identity = _normalize_identity(market, code, frequency, adjustment)
        if not self.path.is_file():
            return []
        connection = sqlite3.connect(self.path)
        try:
            _initialize(connection)
            records = connection.execute(
                """
                SELECT start_ns, end_ns, timezone
                FROM coverage_ranges
                WHERE market = ? AND code = ? AND frequency = ? AND adjustment = ?
                ORDER BY start_ns, end_ns
                """,
                identity,
            ).fetchall()
        finally:
            connection.close()
        if not records:
            return []
        output_timezone = timezone or records[0][2] or DEFAULT_TIMEZONE
        ranges = [
            TimeRange(_ns_timestamp(start, output_timezone), _ns_timestamp(end, output_timezone))
            for start, end, _ in records
        ]
        return _merge_ranges(ranges)

    def _stream_timezone(self, identity: tuple[str, str, str, str]) -> str | None:
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                """
                SELECT timezone FROM bars
                WHERE market = ? AND code = ? AND frequency = ? AND adjustment = ?
                ORDER BY datetime_ns LIMIT 1
                """,
                identity,
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else str(row[0])

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SQLiteStore is closed")


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bars (
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            frequency TEXT NOT NULL,
            datetime_ns INTEGER NOT NULL,
            adjustment TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            turnover REAL,
            float_stock REAL,
            total_stock REAL,
            source TEXT NOT NULL DEFAULT '',
            volume_unit TEXT NOT NULL DEFAULT 'shares',
            timezone TEXT NOT NULL,
            is_approximate INTEGER NOT NULL DEFAULT 0 CHECK (is_approximate IN (0, 1)),
            PRIMARY KEY (market, code, frequency, datetime_ns, adjustment)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS coverage_ranges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            frequency TEXT NOT NULL,
            adjustment TEXT NOT NULL,
            start_ns INTEGER NOT NULL,
            end_ns INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            is_approximate INTEGER NOT NULL DEFAULT 0 CHECK (is_approximate IN (0, 1)),
            timezone TEXT NOT NULL,
            CHECK (start_ns < end_ns)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS bars_stream_range
        ON bars (market, code, frequency, adjustment, datetime_ns)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS coverage_stream_range
        ON coverage_ranges (market, code, frequency, adjustment, start_ns, end_ns)
        """
    )


def _mark_coverage(
    connection: sqlite3.Connection,
    identity: tuple[str, str, str, str],
    interval: TimeRange,
    *,
    timezone: str,
    source: str,
    is_approximate: bool,
) -> None:
    start_ns = _timestamp_ns(interval.start, timezone)
    end_ns = _timestamp_ns(interval.end, timezone)
    approximate = int(bool(is_approximate))
    matches = connection.execute(
        """
        SELECT id, start_ns, end_ns
        FROM coverage_ranges
        WHERE market = ? AND code = ? AND frequency = ? AND adjustment = ?
          AND source = ? AND is_approximate = ?
          AND end_ns >= ? AND start_ns <= ?
        """,
        (*identity, str(source), approximate, start_ns, end_ns),
    ).fetchall()
    if matches:
        start_ns = min(start_ns, *(row[1] for row in matches))
        end_ns = max(end_ns, *(row[2] for row in matches))
        connection.executemany("DELETE FROM coverage_ranges WHERE id = ?", [(row[0],) for row in matches])
    connection.execute(
        """
        INSERT INTO coverage_ranges (
            market, code, frequency, adjustment, start_ns, end_ns,
            source, is_approximate, timezone
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*identity, start_ns, end_ns, str(source), approximate, timezone),
    )


def _merge_ranges(ranges: list[TimeRange]) -> list[TimeRange]:
    merged: list[TimeRange] = []
    for interval in ranges:
        if not merged or interval.start > merged[-1].end:
            merged.append(interval)
            continue
        merged[-1] = TimeRange(merged[-1].start, max(merged[-1].end, interval.end))
    return merged


def _normalize_identity(market: Any, code: Any, frequency: Any, adjustment: Any) -> tuple[str, str, str, str]:
    values = tuple(str(value).strip() for value in (market, code, frequency, adjustment))
    if any(not value for value in values):
        raise ValueError("market, code, frequency and adjustment must not be empty")
    return values


def _frame_rows(
    data: pd.DataFrame,
    *,
    timezone: str | None,
    source: str,
    volume_unit: str,
    is_approximate: bool,
) -> tuple[list[tuple[Any, ...]], str]:
    frame = data.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(frame.index)
    elif "datetime" in frame:
        index = pd.DatetimeIndex(pd.to_datetime(frame.pop("datetime"), errors="raise"))
    elif "date" in frame:
        index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date"), errors="raise"))
    else:
        raise ValueError("data must have a DatetimeIndex or datetime/date column")

    if index.hasnans:
        raise ValueError("datetime must not contain NaT")
    resolved_timezone = timezone or _timezone_name(index.tz) or DEFAULT_TIMEZONE
    index = index.tz_localize(resolved_timezone) if index.tz is None else index.tz_convert(resolved_timezone)

    defaults: dict[str, Any] = {
        **{name: None for name in _NUMERIC_COLUMNS},
        "source": source,
        "volume_unit": volume_unit,
        "timezone": resolved_timezone,
        "is_approximate": is_approximate,
    }
    for name, default in defaults.items():
        if name not in frame:
            frame[name] = default
    frame["source"] = frame["source"].fillna(source).astype(str)
    frame["volume_unit"] = frame["volume_unit"].fillna(volume_unit).astype(str)
    frame["timezone"] = resolved_timezone
    frame["is_approximate"] = frame["is_approximate"].fillna(is_approximate).astype(bool)

    rows: list[tuple[Any, ...]] = []
    for position, timestamp in enumerate(index):
        values: list[Any] = [_timestamp_ns(timestamp, resolved_timezone)]
        for name in _DATA_COLUMNS:
            value = frame.iloc[position][name]
            if name in _NUMERIC_COLUMNS:
                value = _sqlite_number(value)
            elif name == "is_approximate":
                value = int(bool(value))
            else:
                value = str(value)
            values.append(value)
        rows.append(tuple(values))
    return rows, resolved_timezone


def _sqlite_number(value: Any) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return int(value)
    number = value.item() if hasattr(value, "item") else value
    if isinstance(number, float) and not math.isfinite(number):
        return None
    return number


def _timezone_name(tz: Any) -> str | None:
    if tz is None:
        return None
    return getattr(tz, "key", None) or getattr(tz, "zone", None) or str(tz)


def _timestamp_ns(value: Any, timezone: str) -> int:
    timestamp = pd.Timestamp(value)
    timestamp = timestamp.tz_localize(timezone) if timestamp.tzinfo is None else timestamp.tz_convert(timezone)
    return int(timestamp.tz_convert("UTC").value)


def _ns_timestamp(value: int, timezone: str) -> pd.Timestamp:
    return pd.Timestamp(value, unit="ns", tz="UTC").tz_convert(timezone)


def _single_value(series: pd.Series, default: str) -> str:
    return default if series.empty else str(series.iloc[0])


def _attrs(identity: tuple[str, str, str, str], timezone: str, volume_unit: str) -> dict[str, str]:
    return {
        **dict(zip(_IDENTITY_COLUMNS, identity, strict=True)),
        "timezone": timezone,
        "volume_unit": volume_unit,
    }


def _empty_frame(identity: tuple[str, str, str, str], timezone: str) -> pd.DataFrame:
    frame = pd.DataFrame(columns=_DATA_COLUMNS, index=pd.DatetimeIndex([], name="datetime", tz=timezone))
    frame.attrs = _attrs(identity, timezone, DEFAULT_VOLUME_UNIT)
    return frame


_COLUMNS_SQL = """
market, code, frequency, adjustment, datetime_ns,
open, high, low, close, volume, amount, turnover, float_stock, total_stock,
source, volume_unit, timezone, is_approximate
"""
_PLACEHOLDERS = ", ".join("?" for _ in range(18))
_INSERT = f"INSERT INTO bars ({_COLUMNS_SQL}) VALUES ({_PLACEHOLDERS})"
_UPSERT = _INSERT + """
ON CONFLICT (market, code, frequency, datetime_ns, adjustment) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    volume = excluded.volume,
    amount = excluded.amount,
    turnover = excluded.turnover,
    float_stock = excluded.float_stock,
    total_stock = excluded.total_stock,
    source = excluded.source,
    volume_unit = excluded.volume_unit,
    timezone = excluded.timezone,
    is_approximate = excluded.is_approximate
"""
