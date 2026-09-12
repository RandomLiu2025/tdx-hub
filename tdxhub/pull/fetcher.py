"""Paged adapters for the standard and extended TDX quote clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd

from tdxhub.pull.merge import merge_bars
from tdxhub.pull.trades import empty_trade_minutes, trades_to_minutes
from tdxhub.utils import _normalize_symbol, get_frequency, get_stock_market

_DEFAULT_TIMEZONE = "Asia/Shanghai"
_VOLUME_UNITS = {"shares", "lots"}


class QuoteFetcher:
    """Fetch and normalize a bounded bar interval from a quotes client.

    TDX bar offsets run from newest to oldest.  ``fetch`` therefore scans
    increasing offsets until it reaches the requested start, an incomplete
    page, or an empty page.  The returned interval is half-open: ``[start,
    end)``.
    """

    def __init__(
        self,
        quotes: Any,
        *,
        page_size: int = 800,
        max_pages: int = 82,
        extended: bool | None = None,
        timezone: str = _DEFAULT_TIMEZONE,
        source: str = "tdx",
        source_volume_unit: str = "shares",
    ) -> None:
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 800:
            raise ValueError("page_size must be an integer between 1 and 800")
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if source_volume_unit not in _VOLUME_UNITS:
            raise ValueError("source_volume_unit must be 'shares' or 'lots'")
        self.quotes = quotes
        self.page_size = page_size
        self.max_pages = max_pages
        self.extended = extended
        self.timezone = str(timezone)
        self.source = str(source)
        self.source_volume_unit = source_volume_unit

    def fetch(
        self,
        *,
        market: Any,
        code: str,
        frequency: Any,
        start: Any,
        end: Any,
        extended: bool | None = None,
    ) -> pd.DataFrame:
        """Fetch normalized bars in the half-open interval ``[start, end)``."""
        lower = _timestamp(start, self.timezone)
        upper = _timestamp(end, self.timezone)
        if lower >= upper:
            raise ValueError("start must be earlier than end")

        use_extended = self._is_extended() if extended is None else bool(extended)
        symbol = str(code) if use_extended else _standard_symbol(market, code)
        pages: list[pd.DataFrame] = []
        reached_boundary = False
        for page_number in range(self.max_pages):
            offset = page_number * self.page_size
            arguments = {
                "symbol": symbol,
                "frequency": frequency,
                "start": offset,
                "offset": self.page_size,
            }
            if use_extended:
                arguments["market"] = market
            raw = self.quotes.bars(**arguments)
            normalized = self._normalize_page(raw)
            if normalized.empty:
                reached_boundary = True
                break
            pages.append(normalized)
            oldest = normalized.index.min()
            if oldest <= lower or len(normalized) < self.page_size:
                reached_boundary = True
                break

        if not reached_boundary:
            raise RuntimeError("max_pages reached before the requested start")
        if not pages:
            return self._empty_frame()

        # Page zero contains the newest copy when pages overlap.
        result = merge_bars(*reversed(pages))
        result = result.loc[(result.index >= lower) & (result.index < upper)].copy()
        result.index = pd.DatetimeIndex(result.index, name="datetime")
        result.attrs = {
            "market": str(market),
            "code": str(code),
            "frequency": str(frequency),
            "timezone": self.timezone,
            "volume_unit": "shares",
            "source": self.source,
        }
        return result

    def _normalize_page(self, raw: Any) -> pd.DataFrame:
        if raw is None:
            return self._empty_frame()
        if not isinstance(raw, pd.DataFrame):
            raw = pd.DataFrame(raw)
        if raw.empty:
            return self._empty_frame()

        frame = raw.copy()
        if "datetime" in frame.columns:
            index = pd.DatetimeIndex(pd.to_datetime(frame.pop("datetime"), errors="raise"))
        elif "date" in frame.columns:
            index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date"), errors="raise"))
        elif isinstance(frame.index, pd.DatetimeIndex):
            index = pd.DatetimeIndex(frame.index)
        else:
            raise ValueError("quote page must have a datetime/date column or DatetimeIndex")
        if index.hasnans:
            raise ValueError("quote page datetime must not contain NaT")
        index = index.tz_localize(self.timezone) if index.tz is None else index.tz_convert(self.timezone)
        frame.index = pd.DatetimeIndex(index, name="datetime")

        if "volume" not in frame and "vol" in frame:
            frame = frame.rename(columns={"vol": "volume"})
        elif "vol" in frame:
            frame = frame.drop(columns="vol")
        if "volume" in frame and self.source_volume_unit == "lots":
            frame["volume"] = frame["volume"] * 100
        frame["source"] = self.source
        frame["volume_unit"] = "shares"
        frame["timezone"] = self.timezone
        frame["is_approximate"] = False
        return frame

    def _empty_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            columns=(
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "source",
                "volume_unit",
                "timezone",
                "is_approximate",
            ),
            index=pd.DatetimeIndex([], name="datetime", tz=self.timezone),
        )
        frame.attrs = {
            "timezone": self.timezone,
            "volume_unit": "shares",
            "source": self.source,
        }
        return frame

    def _is_extended(self) -> bool:
        if self.extended is not None:
            return self.extended
        try:
            from tdxhub.quotes import ExtQuotes

            return isinstance(self.quotes, ExtQuotes)
        except ImportError:
            return False


class TradeMinuteFetcher:
    """Fetch daily standard-market trades and synthesize minute bars."""

    def __init__(
        self,
        quotes: Any,
        *,
        timezone: str = _DEFAULT_TIMEZONE,
        today: Callable[[], Any] | Any | None = None,
    ) -> None:
        self.quotes = quotes
        self.timezone = str(timezone)
        self.today = today

    def fetch(
        self,
        *,
        market: Any,
        code: str,
        frequency: Any,
        start: Any,
        end: Any,
    ) -> pd.DataFrame:
        """Return synthesized bars in the half-open interval ``[start, end)``."""
        lower = _timestamp(start, self.timezone)
        upper = _timestamp(end, self.timezone)
        if lower >= upper:
            raise ValueError("start must be earlier than end")
        if get_frequency(frequency) != 8:
            raise ValueError("trade fallback frequency must be one minute ('1m' or 8)")
        symbol = _trade_symbol(market, code)
        today = self._today()

        frames: list[pd.DataFrame] = []
        last_day = (upper - pd.Timedelta(1, unit="ns")).normalize()
        for day in pd.date_range(lower.normalize(), last_day, freq="D"):
            if day.date() == today:
                raw = self.quotes.transaction_all(symbol=symbol)
            else:
                raw = self.quotes.transactions_all(symbol=symbol, date=day.strftime("%Y%m%d"))
            if raw is None:
                continue
            if not isinstance(raw, pd.DataFrame):
                raise TypeError("trade quote methods must return a pandas DataFrame")
            if raw.empty:
                continue
            frames.append(trades_to_minutes(raw, date=day.date(), timezone=self.timezone))

        if not frames:
            return empty_trade_minutes(self.timezone)
        result = pd.concat(frames).sort_index(kind="stable")
        result = result.loc[(result.index >= lower) & (result.index < upper)].copy()
        result.index = pd.DatetimeIndex(result.index, name="datetime")
        result.attrs = {
            "market": str(market),
            "code": str(code),
            "frequency": str(frequency),
            "timezone": self.timezone,
            "volume_unit": "shares",
            "source": "trade",
        }
        return result

    def _today(self) -> date:
        value = self.today() if callable(self.today) else self.today
        timestamp = pd.Timestamp.now(tz=self.timezone) if value is None else pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(self.timezone)
        else:
            timestamp = timestamp.tz_convert(self.timezone)
        return timestamp.date()


def _timestamp(value: Any, timezone: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(timezone)
    return timestamp.tz_convert(timezone)


def _standard_symbol(market: Any, code: str) -> str:
    """Encode explicit standard market identity for the symbol-only bars API."""
    if str(market).lower() == "std":
        return str(code)
    markets = {"0": "sz", "1": "sh", "2": "bj", "sz": "sz", "sh": "sh", "bj": "bj"}
    expected = markets.get(str(market).lower())
    if expected is None:
        raise ValueError("standard market must be 0/sz, 1/sh, 2/bj or std")
    prefix, bare_code = _normalize_symbol(str(code))
    if prefix is not None and prefix.lower() != expected:
        raise ValueError("symbol prefix conflicts with the requested market")
    return expected + bare_code


def _trade_symbol(market: Any, code: str) -> str:
    market_name = str(market).lower()
    prefix, _ = _normalize_symbol(str(code))
    inferred_market = get_stock_market(str(code), string=True) if market_name == "std" else None
    if market_name in {"2", "bj"} or (market_name == "std" and inferred_market == "bj"):
        raise ValueError("trade fallback market supports only Shanghai and Shenzhen")
    if market_name not in {"std", "0", "1", "sz", "sh"}:
        raise ValueError("trade fallback market must be 0/sz, 1/sh or std")
    return _standard_symbol(market, code)
