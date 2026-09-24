import pytest

from tdxhub.quotes import ExtQuotes


class _ExtClient:
    def __init__(self):
        self.calls = []

    def get_instrument_quote_list(self, *args, **kwargs):
        self.calls.append(("quote_list", args, kwargs))
        return [{"code": "00700", "price": 600.0}]

    def get_history_instrument_bars_range(self, *args, **kwargs):
        self.calls.append(("bars_range", args, kwargs))
        return [{"datetime": "2026-09-10 00:00", "close": 600.0}]


def test_ext_quote_list_wraps_tdxpy_api():
    quotes = object.__new__(ExtQuotes)
    quotes.client = _ExtClient()

    result = quotes.quote_list(market=31, category=2, start=5, offset=20)

    assert result.to_dict("records") == [{"code": "00700", "price": 600.0}]
    assert quotes.client.calls == [("quote_list", (), {"market": 31, "category": 2, "start": 5, "count": 20})]


def test_ext_bars_range_accepts_prefixed_symbol_and_integer_dates():
    quotes = object.__new__(ExtQuotes)
    quotes.client = _ExtClient()

    result = quotes.bars_range(market=None, symbol="31#00700", start_date="20260901", end_date=20260910)

    assert result.iloc[0]["close"] == 600.0
    assert quotes.client.calls == [
        (
            "bars_range",
            (),
            {"market": 31, "code": "00700", "start": 20260901, "end": 20260910},
        )
    ]


def _disable_retry_wait(monkeypatch, method):
    from tenacity import wait_none

    while hasattr(method, "retry"):
        monkeypatch.setattr(method.retry, "wait", wait_none())
        method = method.__wrapped__


def test_ext_quote_list_failure_has_one_three_attempt_budget(monkeypatch):
    from unittest.mock import Mock

    quotes = object.__new__(ExtQuotes)
    quotes.client = Mock()
    quotes.client.get_instrument_quote_list.side_effect = ConnectionError("offline fixture")
    _disable_retry_wait(monkeypatch, ExtQuotes.quote_list)

    with pytest.raises(ConnectionError, match="offline fixture"):
        quotes.quote_list(market=31)
    assert quotes.client.get_instrument_quote_list.call_count == 3


def test_ext_quote_keeps_existing_retry_for_transient_failure(monkeypatch):
    from unittest.mock import Mock

    quotes = object.__new__(ExtQuotes)
    quotes.client = Mock()
    quotes.client.get_instrument_quote.side_effect = [ConnectionError("transient fixture"), [{"price": 600.0}]]
    _disable_retry_wait(monkeypatch, ExtQuotes.quote)

    assert quotes.quote(market=31, symbol="00700").iloc[0]["price"] == 600.0
    assert quotes.client.get_instrument_quote.call_count == 2


class _FailoverExtApi:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.endpoint = None
        self.client = None

    def connect(self, ip, port, time_out):
        self.endpoint = (ip, port)
        self.client = object()
        return self

    def close(self):
        self.client = None

    def get_instrument_count(self):
        if getattr(self, "heartbeat_runner", None) is not None and self.endpoint == ("127.0.0.1", 7727):
            from tdxhub.tdx.errors import TdxFunctionCallError

            raise TdxFunctionCallError("primary offline")
        return 1


def test_extended_quote_updates_public_server_after_runtime_switch(monkeypatch):
    from tdxhub import config

    values = {
        "BESTIP.EX": ("127.0.0.2", 7727),
        "SERVER.EX": [("backup", "127.0.0.2", 7727)],
    }
    monkeypatch.setattr(config, "setup", lambda **kwargs: True)
    monkeypatch.setattr(config, "get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(config, "set", lambda key, value: values.__setitem__(key, value))
    monkeypatch.setattr("tdxhub.quotes.ExtendedClient", _FailoverExtApi)

    quotes = ExtQuotes(
        server=("127.0.0.1", 7727),
        fallback_servers=True,
        max_candidates=2,
        max_failovers=1,
        raise_exception=True,
    )

    assert quotes.client.get_instrument_count() == 1
    assert quotes.server == ("127.0.0.2", 7727)
