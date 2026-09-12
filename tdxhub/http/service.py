"""Service adapter between the HTTP API and tdxhub quote clients."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_EXCHANGES = {"sz": 0, "sh": 1, "bj": 2}


class MarketDataService:
    """Expose stable operations while keeping quote clients injectable."""

    def __init__(
        self,
        standard_quotes: Any,
        *,
        extended_quotes: Any | None = None,
        pull_service: Any | None = None,
    ) -> None:
        self.standard_quotes = standard_quotes
        self.extended_quotes = extended_quotes
        self.pull_service = pull_service

    def ready(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "standard": self.standard_quotes is not None,
            "extendedEnabled": self.extended_quotes is not None,
        }

    @staticmethod
    def _required_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"参数 {name} 不能为空")
        return value.strip()

    @classmethod
    def _market(cls, exchange: str) -> int:
        normalized = cls._required_text(exchange, "exchange").lower()
        try:
            return _EXCHANGES[normalized]
        except KeyError as exc:
            raise ValueError(f"不支持的交易所: {exchange} (可选: sh, sz, bj)") from exc

    @classmethod
    def _symbol(cls, exchange: str, code: str) -> str:
        normalized = cls._required_text(exchange, "exchange").lower()
        cls._market(normalized)
        return f"{normalized}{cls._required_text(code, 'code')}"

    @staticmethod
    def _codes(codes: str) -> list[str]:
        values = [code.strip() for code in codes.split(",") if code.strip()]
        if not values:
            raise ValueError("参数 codes 不能为空")
        return values

    @staticmethod
    def _since(since: str | None) -> str | None:
        if since is None:
            return None
        if not isinstance(since, str) or len(since) != 8 or not since.isdigit():
            raise ValueError("参数 since 必须使用 YYYYMMDD 格式")
        try:
            datetime.strptime(since, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("参数 since 必须使用有效的 YYYYMMDD 日期") from exc
        return since

    @staticmethod
    def _adjustment(adjust: str | None) -> str | None:
        if adjust is None:
            return None
        normalized = str(adjust).strip().lower()
        if normalized in {"", "none"}:
            return None
        if normalized not in {"qfq", "hfq"}:
            raise ValueError(f"不支持的复权类型: {adjust} (可选: none, qfq, hfq)")
        return normalized

    def _extended(self) -> Any:
        if self.extended_quotes is None:
            raise LookupError("扩展行情未启用")
        return self.extended_quotes

    def count(self, exchange: str) -> Any:
        return self.standard_quotes.stock_count(market=self._market(exchange))

    def code_all(self, exchange: str) -> Any:
        return self.standard_quotes.stocks(market=self._market(exchange))

    def code(self, exchange: str, start: int) -> Any:
        return self.standard_quotes.stock_list(market=self._market(exchange), start=start)

    def quote(self, codes: str) -> Any:
        return self.standard_quotes.quotes(symbol=self._codes(codes))

    def stock_info(self, codes: str, *, refresh_industries: bool = False) -> Any:
        if not isinstance(refresh_industries, bool):
            raise ValueError("参数 refresh_industries 必须是布尔值")
        return self.standard_quotes.stock_info(
            symbols=self._codes(codes),
            refresh_industries=refresh_industries,
        )

    def call_auction(self, code: str) -> Any:
        return self.standard_quotes.call_auction(symbol=self._required_text(code, "code"))

    def gbbq(self, code: str) -> Any:
        return self.standard_quotes.xdxr(symbol=self._required_text(code, "code"))

    def finance(self, *, exchange: str, code: str) -> Any:
        return self.standard_quotes.finance(symbol=self._symbol(exchange, code))

    def company_category(self, *, exchange: str, code: str) -> Any:
        return self.standard_quotes.F10C(symbol=self._symbol(exchange, code))

    def company_content(
        self,
        *,
        exchange: str,
        code: str,
        filename: str,
        start: int,
        length: int,
    ) -> Any:
        return self.standard_quotes.company_content(
            symbol=self._symbol(exchange, code),
            filename=self._required_text(filename, "filename"),
            start=start,
            length=length,
        )

    def statistics(self) -> Any:
        return self.standard_quotes.statistics()

    def money_flow(self) -> Any:
        return self.standard_quotes.money_flow()

    def xgsg(self) -> Any:
        return self.standard_quotes.xgsg()

    def index_kline(self, *, category: int, code: str, start: int, count: int) -> Any:
        return self.standard_quotes.index(
            symbol=self._required_text(code, "code"),
            frequency=category,
            start=start,
            offset=count,
        )

    def index_all(self, *, category: int, code: str, since: str | None = None) -> Any:
        return self.standard_quotes.index_all(
            symbol=self._required_text(code, "code"),
            frequency=category,
            since=self._since(since),
        )

    def kline(self, *, category: int, code: str, start: int, count: int) -> Any:
        return self.standard_quotes.bars(
            symbol=self._required_text(code, "code"),
            frequency=category,
            start=start,
            offset=count,
        )

    def kline_all(
        self,
        *,
        category: int,
        code: str,
        since: str | None = None,
        adjust: str | None = None,
    ) -> Any:
        kwargs = {
            "symbol": self._required_text(code, "code"),
            "frequency": category,
            "since": self._since(since),
        }
        adjustment = self._adjustment(adjust)
        if adjustment is not None:
            kwargs["adjust"] = adjustment
        return self.standard_quotes.bars_all(**kwargs)

    def minute_241(self, *, code: str, since: str | None = None) -> Any:
        return self.standard_quotes.minute_241(
            symbol=self._required_text(code, "code"),
            since=self._since(since),
        )

    def minute(self, code: str) -> Any:
        return self.standard_quotes.minute(symbol=self._required_text(code, "code"))

    def history_minute(self, *, date: str, code: str) -> Any:
        return self.standard_quotes.minutes(symbol=self._required_text(code, "code"), date=date)

    def trade(self, *, code: str, start: int, count: int) -> Any:
        return self.standard_quotes.transaction(
            symbol=self._required_text(code, "code"), start=start, offset=count
        )

    def history_trade(self, *, date: str, code: str, start: int, count: int) -> Any:
        return self.standard_quotes.transactions(
            symbol=self._required_text(code, "code"),
            date=self._required_text(date, "date"),
            start=start,
            offset=count,
        )

    def trade_all(self, *, code: str) -> Any:
        return self.standard_quotes.transaction_all(symbol=self._required_text(code, "code"))

    def history_trade_day(self, *, date: str, code: str) -> Any:
        return self.standard_quotes.transactions_all(
            symbol=self._required_text(code, "code"),
            date=self._required_text(date, "date"),
        )

    def ext_markets(self) -> Any:
        return self._extended().markets()

    def ext_count(self) -> Any:
        return self._extended().instrument_count()

    def ext_instruments(self, *, start: int, count: int) -> Any:
        return self._extended().instrument(start=start, offset=count)

    def ext_quote(self, *, market: int, code: str) -> Any:
        return self._extended().quote(
            market=market, symbol=self._required_text(code, "code")
        )

    def ext_quote_list(self, *, market: int, category: int, start: int, count: int) -> Any:
        return self._extended().quote_list(
            market=market,
            category=category,
            start=start,
            offset=count,
        )

    def ext_bars(self, *, category: int, market: int, code: str, start: int, count: int) -> Any:
        return self._extended().bars(
            frequency=category,
            market=market,
            symbol=self._required_text(code, "code"),
            start=start,
            offset=count,
        )

    def ext_minute(self, *, market: int, code: str) -> Any:
        return self._extended().minute(
            market=market, symbol=self._required_text(code, "code")
        )

    def ext_history_minute(self, *, market: int, code: str, date: int) -> Any:
        return self._extended().minutes(
            market=market, symbol=self._required_text(code, "code"), date=date
        )

    def ext_trade(self, *, market: int, code: str, start: int, count: int) -> Any:
        return self._extended().transaction(
            market=market,
            symbol=self._required_text(code, "code"),
            start=start,
            offset=count,
        )

    def ext_history_trade(
        self,
        *,
        market: int,
        code: str,
        date: int,
        start: int,
        count: int,
    ) -> Any:
        return self._extended().transactions(
            market=market,
            symbol=self._required_text(code, "code"),
            date=date,
            start=start,
            offset=count,
        )

    def ext_bars_range(
        self,
        *,
        market: int,
        code: str,
        start_date: int,
        end_date: int,
    ) -> Any:
        return self._extended().bars_range(
            market=market,
            symbol=self._required_text(code, "code"),
            start_date=start_date,
            end_date=end_date,
        )
