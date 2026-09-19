import pandas as pd
import pytest

from tdxhub.http.service import MarketDataService


class FakeStandardQuotes:
    def __init__(self):
        self.calls = []

    def _result(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return pd.DataFrame([{"method": name}])

    def stock_count(self, market):
        self.calls.append(("stock_count", {"market": market}))
        return 321

    def stocks(self, market):
        return self._result("stocks", market=market)

    def stock_list(self, market, start):
        return self._result("stock_list", market=market, start=start)

    def quotes(self, symbol):
        return self._result("quotes", symbol=symbol)

    def stock_info(self, **kwargs):
        return self._result("stock_info", **kwargs)

    def call_auction(self, symbol):
        return self._result("call_auction", symbol=symbol)

    def bars(self, **kwargs):
        return self._result("bars", **kwargs)

    def minute(self, symbol):
        return self._result("minute", symbol=symbol)

    def minutes(self, **kwargs):
        return self._result("minutes", **kwargs)

    def transaction(self, **kwargs):
        return self._result("transaction", **kwargs)

    def transactions(self, **kwargs):
        return self._result("transactions", **kwargs)

    def transaction_all(self, **kwargs):
        return self._result("transaction_all", **kwargs)

    def transactions_all(self, **kwargs):
        return self._result("transactions_all", **kwargs)

    def bars_all(self, **kwargs):
        return self._result("bars_all", **kwargs)

    def minute_241(self, **kwargs):
        return self._result("minute_241", **kwargs)

    def index_all(self, **kwargs):
        return self._result("index_all", **kwargs)

    def xdxr(self, **kwargs):
        return self._result("xdxr", **kwargs)

    def finance(self, **kwargs):
        return self._result("finance", **kwargs)

    def F10C(self, **kwargs):  # noqa: N802
        return self._result("F10C", **kwargs)

    def company_content(self, **kwargs):
        return self._result("company_content", **kwargs)

    def statistics(self):
        return self._result("statistics")

    def money_flow(self):
        return self._result("money_flow")

    def xgsg(self):
        return self._result("xgsg")

    def index(self, **kwargs):
        return self._result("index", **kwargs)


class FakeExtendedQuotes:
    def __init__(self):
        self.calls = []

    def _result(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return pd.DataFrame([{"method": name}])

    def markets(self):
        return self._result("markets")

    def instrument_count(self):
        self.calls.append(("instrument_count", {}))
        return 99

    def instrument(self, **kwargs):
        return self._result("instrument", **kwargs)

    def quote(self, **kwargs):
        return self._result("quote", **kwargs)

    def quote_list(self, **kwargs):
        return self._result("quote_list", **kwargs)

    def bars(self, **kwargs):
        return self._result("bars", **kwargs)

    def minute(self, **kwargs):
        return self._result("minute", **kwargs)

    def minutes(self, **kwargs):
        return self._result("minutes", **kwargs)

    def transaction(self, **kwargs):
        return self._result("transaction", **kwargs)

    def transactions(self, **kwargs):
        return self._result("transactions", **kwargs)

    def bars_range(self, **kwargs):
        return self._result("bars_range", **kwargs)


def test_standard_service_maps_http_parameters_to_quotes_api():
    quotes = FakeStandardQuotes()
    service = MarketDataService(quotes)

    assert service.count("sh") == 321
    service.code_all("bj")
    service.quote("sz000001, sh600519")
    service.kline(category=9, code="600519", start=5, count=20)
    service.history_minute(date="20260910", code="600519")
    service.trade(code="600519", start=2, count=30)
    service.history_trade(date="20260910", code="600519", start=3, count=40)

    assert quotes.calls == [
        ("stock_count", {"market": 1}),
        ("stocks", {"market": 2}),
        ("quotes", {"symbol": ["sz000001", "sh600519"]}),
        ("bars", {"symbol": "600519", "frequency": 9, "start": 5, "offset": 20}),
        ("minutes", {"symbol": "600519", "date": "20260910"}),
        ("transaction", {"symbol": "600519", "start": 2, "offset": 30}),
        ("transactions", {"symbol": "600519", "date": "20260910", "start": 3, "offset": 40}),
    ]


def test_standard_service_maps_minute_241_and_validates_since():
    quotes = FakeStandardQuotes()
    service = MarketDataService(quotes)

    service.minute_241(code="600519", since="20260910")

    assert quotes.calls == [
        ("minute_241", {"symbol": "600519", "since": "20260910"}),
    ]
    with pytest.raises(ValueError, match="YYYYMMDD"):
        service.minute_241(code="600519", since="2026-09-10")
    with pytest.raises(ValueError, match="有效"):
        service.minute_241(code="600519", since="20260230")


def test_standard_service_maps_single_page_and_all_data_operations():
    quotes = FakeStandardQuotes()
    service = MarketDataService(quotes)

    service.code("bj", start=1000)
    service.trade_all(code="600519")
    service.history_trade_day(date="20260910", code="600519")
    service.kline_all(category=9, code="600519", since="20260101")
    service.index_all(category=5, code="000001")

    assert quotes.calls == [
        ("stock_list", {"market": 2, "start": 1000}),
        ("transaction_all", {"symbol": "600519"}),
        ("transactions_all", {"symbol": "600519", "date": "20260910"}),
        ("bars_all", {"symbol": "600519", "frequency": 9, "since": "20260101"}),
        ("index_all", {"symbol": "000001", "frequency": 5, "since": None}),
    ]


@pytest.mark.parametrize("since", ["2026-01-01", "20260230", "", "1234567"])
def test_all_kline_service_rejects_invalid_since(since):
    service = MarketDataService(FakeStandardQuotes())

    with pytest.raises(ValueError, match="YYYYMMDD"):
        service.kline_all(category=9, code="600519", since=since)


def test_extended_service_maps_all_core_operations():
    standard = FakeStandardQuotes()
    extended = FakeExtendedQuotes()
    service = MarketDataService(standard, extended_quotes=extended)

    service.ext_markets()
    assert service.ext_count() == 99
    service.ext_instruments(start=10, count=50)
    service.ext_quote(market=31, code="00700")
    service.ext_quote_list(market=31, category=2, start=5, count=20)
    service.ext_bars(category=9, market=31, code="00700", start=0, count=80)
    service.ext_minute(market=31, code="00700")
    service.ext_history_minute(market=31, code="00700", date=20260910)
    service.ext_trade(market=31, code="00700", start=1, count=10)
    service.ext_history_trade(market=31, code="00700", date=20260910, start=2, count=15)
    service.ext_bars_range(market=31, code="00700", start_date=20260901, end_date=20260910)

    assert extended.calls == [
        ("markets", {}),
        ("instrument_count", {}),
        ("instrument", {"start": 10, "offset": 50}),
        ("quote", {"market": 31, "symbol": "00700"}),
        ("quote_list", {"market": 31, "category": 2, "start": 5, "offset": 20}),
        ("bars", {"frequency": 9, "market": 31, "symbol": "00700", "start": 0, "offset": 80}),
        ("minute", {"market": 31, "symbol": "00700"}),
        ("minutes", {"market": 31, "symbol": "00700", "date": 20260910}),
        ("transaction", {"market": 31, "symbol": "00700", "start": 1, "offset": 10}),
        ("transactions", {"market": 31, "symbol": "00700", "date": 20260910, "start": 2, "offset": 15}),
        ("bars_range", {"market": 31, "symbol": "00700", "start_date": 20260901, "end_date": 20260910}),
    ]


def test_extended_service_fails_cleanly_when_not_configured():
    service = MarketDataService(FakeStandardQuotes())

    with pytest.raises(LookupError, match="扩展行情未启用"):
        service.ext_markets()


def test_service_rejects_invalid_exchange_and_empty_codes():
    service = MarketDataService(FakeStandardQuotes())

    with pytest.raises(ValueError, match="交易所"):
        service.count("hk")
    with pytest.raises(ValueError, match="codes"):
        service.quote(" , ")


def test_standard_service_maps_finance_company_statistics_and_index_operations():
    quotes = FakeStandardQuotes()
    service = MarketDataService(quotes)

    service.gbbq("600519")
    service.finance(exchange="sh", code="600519")
    service.company_category(exchange="sz", code="000001")
    service.company_content(
        exchange="sh",
        code="600519",
        filename="600519.txt",
        start=10,
        length=20,
    )
    service.statistics()
    service.money_flow()
    service.xgsg()
    service.index_kline(category=9, code="000001", start=2, count=30)

    assert quotes.calls == [
        ("xdxr", {"symbol": "600519"}),
        ("finance", {"symbol": "sh600519"}),
        ("F10C", {"symbol": "sz000001"}),
        (
            "company_content",
            {
                "symbol": "sh600519",
                "filename": "600519.txt",
                "start": 10,
                "length": 20,
            },
        ),
        ("statistics", {}),
        ("money_flow", {}),
        ("xgsg", {}),
        ("index", {"symbol": "000001", "frequency": 9, "start": 2, "offset": 30}),
    ]


def test_standard_service_rejects_blank_required_values():
    service = MarketDataService(FakeStandardQuotes())

    with pytest.raises(ValueError, match="code"):
        service.gbbq("   ")
    with pytest.raises(ValueError, match="filename"):
        service.company_content(exchange="sh", code="600519", filename=" ", start=0, length=1)


def test_kline_all_maps_and_validates_adjustment():
    quotes = FakeStandardQuotes()
    service = MarketDataService(quotes)

    service.kline_all(category=9, code="600519", since="20260101", adjust="QFQ")
    service.kline_all(category=9, code="600519", adjust="none")

    assert quotes.calls == [
        (
            "bars_all",
            {
                "symbol": "600519",
                "frequency": 9,
                "since": "20260101",
                "adjust": "qfq",
            },
        ),
        ("bars_all", {"symbol": "600519", "frequency": 9, "since": None}),
    ]

    with pytest.raises(ValueError, match="复权"):
        service.kline_all(category=9, code="600519", adjust="forward")


def test_stock_info_service_maps_codes_and_refresh_flag():
    quotes = FakeStandardQuotes()
    service = MarketDataService(quotes)

    service.stock_info("sz000001, sh600519", refresh_industries=True)

    assert quotes.calls == [
        (
            "stock_info",
            {"symbols": ["sz000001", "sh600519"], "refresh_industries": True},
        )
    ]
