import pandas as pd
import pytest

from tdxhub.pull import QuoteFetcher
from tdxhub.quotes import ExtQuotes, StdQuotes

TZ = "Asia/Shanghai"


def page(*times, base=1, volume_column="vol"):
    size = len(times)
    return pd.DataFrame(
        {
            "datetime": list(times),
            "open": [base + value for value in range(size)],
            "high": [base + value + 1 for value in range(size)],
            "low": [base + value - 1 for value in range(size)],
            "close": [base + value + 0.5 for value in range(size)],
            volume_column: [value + 1 for value in range(size)],
            "amount": [1000 * (value + 1) for value in range(size)],
        }
    )


class FakeStdQuotes:
    def __init__(self, pages, *, fail_at=None):
        self.pages = pages
        self.fail_at = fail_at
        self.calls = []

    def bars(self, **kwargs):
        self.calls.append(kwargs)
        page_number = kwargs["start"] // kwargs["offset"]
        if page_number == self.fail_at:
            raise ConnectionError("fetch failed")
        return self.pages[page_number] if page_number < len(self.pages) else pd.DataFrame()


class FakeExtQuotes(FakeStdQuotes):
    pass


def test_standard_fetch_pages_backwards_normalizes_and_filters():
    quotes = FakeStdQuotes(
        [
            page("2026-01-05 09:35", "2026-01-05 09:34", base=20),
            page("2026-01-05 09:34", "2026-01-05 09:33", base=10),
        ]
    )
    fetcher = QuoteFetcher(quotes, page_size=2, max_pages=4, source_volume_unit="lots")

    result = fetcher.fetch(
        market="std",
        code="600000",
        frequency="1m",
        start=pd.Timestamp("2026-01-05 09:33", tz=TZ),
        end=pd.Timestamp("2026-01-05 09:36", tz=TZ),
    )

    assert [call["start"] for call in quotes.calls] == [0, 2]
    assert all(call["symbol"] == "600000" for call in quotes.calls)
    assert all("market" not in call for call in quotes.calls)
    assert list(result.index) == list(pd.date_range("2026-01-05 09:33", periods=3, freq="min", tz=TZ))
    # The newest page wins its overlap at 09:34.
    assert result.loc[pd.Timestamp("2026-01-05 09:34", tz=TZ), "open"] == 21
    assert list(result["volume"]) == [200, 200, 100]
    assert set(result["source"]) == {"tdx"}
    assert set(result["volume_unit"]) == {"shares"}
    assert set(result["timezone"]) == {TZ}
    assert set(result["is_approximate"]) == {False}
    assert "vol" not in result


def test_extended_fetch_passes_market_and_stops_on_short_page():
    quotes = FakeExtQuotes([page("2026-01-05 15:00", volume_column="volume")])
    fetcher = QuoteFetcher(quotes, extended=True, page_size=2, source_volume_unit="shares")

    result = fetcher.fetch(
        market=31,
        code="00020",
        frequency=9,
        start="2026-01-01",
        end="2026-01-06",
    )

    assert quotes.calls == [{"market": 31, "symbol": "00020", "frequency": 9, "start": 0, "offset": 2}]
    assert result.iloc[0]["volume"] == 1


def test_fetch_rejects_bad_pages_and_protects_page_limit():
    invalid = FakeStdQuotes([pd.DataFrame({"open": [1]})])
    with pytest.raises(ValueError, match="datetime"):
        QuoteFetcher(invalid, page_size=1).fetch(
            market="std", code="1", frequency="1m", start="2026-01-01", end="2026-01-02"
        )

    quotes = FakeStdQuotes([page("2026-01-05 09:35"), page("2026-01-05 09:34")])
    with pytest.raises(RuntimeError, match="max_pages"):
        QuoteFetcher(quotes, page_size=1, max_pages=2).fetch(
            market="std", code="1", frequency="1m", start="2026-01-01", end="2026-01-06"
        )


def test_fetch_propagates_client_error_without_returning_partial_data():
    quotes = FakeStdQuotes([page("2026-01-05 09:35"), page("2026-01-05 09:34")], fail_at=1)
    with pytest.raises(ConnectionError, match="fetch failed"):
        QuoteFetcher(quotes, page_size=1).fetch(
            market="std", code="1", frequency="1m", start="2026-01-01", end="2026-01-06"
        )


@pytest.mark.parametrize(
    ("quotes_class", "expects_market"),
    [(StdQuotes, False), (ExtQuotes, True)],
)
def test_fetch_auto_detects_real_quote_client_classes(quotes_class, expects_market):
    quotes = object.__new__(quotes_class)
    calls = []

    def bars_call(**kwargs):
        calls.append(kwargs)
        return page("2026-01-05 15:00")

    quotes.bars = bars_call
    result = QuoteFetcher(quotes, page_size=2).fetch(
        market=31 if expects_market else 1, code="00020", frequency=9, start="2026-01-01", end="2026-01-06"
    )

    assert not result.empty
    assert ("market" in calls[0]) is expects_market


@pytest.mark.parametrize(("market", "symbol"), [(1, "sh000001"), ("sh", "sh000001"), (0, "sz000001"), (2, "bj000001")])
def test_standard_fetch_respects_explicit_market(market, symbol):
    quotes = FakeStdQuotes([page("2026-01-05 15:00")])
    QuoteFetcher(quotes).fetch(
        market=market, code="000001", frequency=9, start="2026-01-01", end="2026-01-06"
    )
    assert quotes.calls[0]["symbol"] == symbol


def test_standard_fetch_rejects_conflicting_symbol_market_before_io():
    quotes = FakeStdQuotes([])
    with pytest.raises(ValueError, match="market"):
        QuoteFetcher(quotes).fetch(
            market=1, code="sz000001", frequency=9, start="2026-01-01", end="2026-01-06"
        )
    assert quotes.calls == []


class FakeTradeQuotes:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def transaction_all(self, **kwargs):
        self.calls.append(("current", kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response.copy()

    def transactions_all(self, **kwargs):
        self.calls.append(("history", kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response.copy()


def trade_page(clock="09:25", price=10, volume=1):
    return pd.DataFrame({"time": [clock], "price": [price], "vol": [volume], "num": [1]})


def test_trade_minute_fetcher_uses_history_and_current_endpoints_and_filters_half_open_range():
    from tdxhub.pull import TradeMinuteFetcher

    quotes = FakeTradeQuotes([trade_page(price=10), trade_page(price=20)])
    fetcher = TradeMinuteFetcher(quotes, today=lambda: pd.Timestamp("2025-01-07 12:00", tz=TZ))

    result = fetcher.fetch(
        market="std",
        code="600519",
        frequency="1m",
        start=pd.Timestamp("2025-01-06 14:59", tz=TZ),
        end=pd.Timestamp("2025-01-07 09:31", tz=TZ),
    )

    assert quotes.calls == [
        ("history", {"symbol": "600519", "date": "20250106"}),
        ("current", {"symbol": "600519"}),
    ]
    assert list(result.index) == [
        pd.Timestamp("2025-01-06 14:59", tz=TZ),
        pd.Timestamp("2025-01-06 15:00", tz=TZ),
        pd.Timestamp("2025-01-07 09:30", tz=TZ),
    ]
    assert list(result["close"]) == [10, 10, 20]


@pytest.mark.parametrize(
    ("market", "code", "frequency"),
    [
        (2, "000001", "1m"),
        ("bj", "000001", 8),
        ("std", "bj000001", "1m"),
        ("std", "920001", "1m"),
        (1, "sz000001", "1m"),
        (0, "sh600519", "1m"),
        ("std", "600519", "5m"),
        ("std", "600519", 9),
    ],
)
def test_trade_minute_fetcher_rejects_unsupported_market_or_frequency_before_io(market, code, frequency):
    from tdxhub.pull import TradeMinuteFetcher

    quotes = FakeTradeQuotes([])
    fetcher = TradeMinuteFetcher(quotes, today=lambda: "2025-01-07")

    with pytest.raises(ValueError, match="market|frequency"):
        fetcher.fetch(
            market=market,
            code=code,
            frequency=frequency,
            start="2025-01-06",
            end="2025-01-07",
        )
    assert quotes.calls == []


def test_trade_minute_fetcher_skips_empty_days_and_propagates_later_failure():
    from tdxhub.pull import TradeMinuteFetcher

    empty_quotes = FakeTradeQuotes([pd.DataFrame(), trade_page(price=11)])
    result = TradeMinuteFetcher(empty_quotes, today=lambda: "2025-01-10").fetch(
        market=1, code="600519", frequency=8, start="2025-01-05", end="2025-01-07"
    )
    assert len(result) == 241
    assert empty_quotes.calls == [
        ("history", {"symbol": "sh600519", "date": "20250105"}),
        ("history", {"symbol": "sh600519", "date": "20250106"}),
    ]

    failing_quotes = FakeTradeQuotes([trade_page(), ConnectionError("trade page failed")])
    with pytest.raises(ConnectionError, match="trade page failed"):
        TradeMinuteFetcher(failing_quotes, today=lambda: "2025-01-10").fetch(
            market="std", code="600519", frequency="1m", start="2025-01-05", end="2025-01-07"
        )


def test_trade_minute_fetcher_returns_schema_without_fabricating_bars_for_empty_days():
    from tdxhub.pull import TradeMinuteFetcher

    quotes = FakeTradeQuotes([pd.DataFrame()])
    result = TradeMinuteFetcher(quotes, today=lambda: "2025-01-10").fetch(
        market="std", code="600519", frequency="1m", start="2025-01-05", end="2025-01-06"
    )

    assert result.empty
    assert result.index.name == "datetime"
    assert str(result.index.tz) == TZ
    assert {"open", "close", "volume", "amount", "source", "is_approximate"} <= set(result.columns)
    assert result.attrs == {"timezone": TZ, "volume_unit": "shares", "source": "trade"}
