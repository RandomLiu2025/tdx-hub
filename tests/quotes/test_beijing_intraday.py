"""Beijing intraday APIs must reach the existing historical wire protocols."""

import struct
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from tdxhub.exceptions import TdxhubValidationException
from tdxhub.quotes import StdQuotes
from tests.tdx.test_price_decoding import encode_price
from tests.tdx.test_protocol import quote_api


@pytest.mark.parametrize('symbol', ['920026', 'bj920026', 'BJ.920026'])
@pytest.mark.parametrize('current', [False, True], ids=['minutes', 'minute'])
def test_beijing_minute_public_wire_routing_and_timeline(monkeypatch, symbol, current):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == 'Asia/Shanghai'
            return cls(2026, 9, 21, 21, 0, tzinfo=tz)

    monkeypatch.setattr('tdxhub.quotes.datetime', Clock)
    body = struct.pack('<HI', 240, 0)
    for i in range(240):
        body += b''.join(map(encode_price, [1750 if i == 0 else 1, 0, i]))
    q = object.__new__(StdQuotes)
    q.client = quote_api(body)
    data = q.minute(symbol) if current else q.minutes(symbol, date='20260918')
    day = '2026-09-21' if current else '2026-09-18'
    date = 20260921 if current else 20260918

    assert q.client.client.sent == [
        bytes.fromhex('0c01300001010d000d00b40f') + struct.pack('<IB6s', date, 2, b'920026')
    ]
    assert len(data) == 240
    assert data.index.is_unique and data.index.is_monotonic_increasing
    assert data.index[[0, 119, 120, 239]].tolist() == [
        pd.Timestamp(f'{day} {time}') for time in ['09:31', '11:30', '13:01', '15:00']
    ]
    assert pd.DatetimeIndex(data.datetime).equals(data.index)
    assert data.price.iloc[0] == pytest.approx(17.50)
    assert data.price.iloc[-1] == pytest.approx(19.89)
    assert data.vol.tolist() == list(range(240))


@pytest.mark.parametrize('symbol', ['920026', 'bj920026', 'BJ.920026'])
def test_beijing_historical_transactions_public_wire_routing(symbol):
    body = struct.pack('<HI', 2, 0)
    for delta, volume, side in [(1750, 10, 0), (-1, 20, 1)]:
        body += struct.pack('<H', 9 * 60 + 31)
        body += b''.join(map(encode_price, [delta, volume, side, 0]))
    q = object.__new__(StdQuotes)
    q.client = quote_api(body)
    data = q.transactions(symbol, start=5, offset=2, date='20260918')
    assert q.client.client.sent == [
        bytes.fromhex('0c013001000112001200b50f')
        + struct.pack('<IH6sHH', 20260918, 2, b'920026', 5, 2)
    ]
    assert data.price.tolist() == pytest.approx([17.50, 17.49])
    assert data.vol.tolist() == [10, 20]
    assert data.buyorsell.tolist() == [0, 1]


def test_beijing_historical_flow_uses_paginated_historical_trades():
    calls = []

    def load(market, code, start, size, date):
        calls.append((market, code, start, size, date))
        return [{'time': '09:31', 'price': 17.5, 'vol': 10, 'buyorsell': 0}] * size if start == 0 else []

    q = object.__new__(StdQuotes)
    q.client = SimpleNamespace(get_history_transaction_data=load, to_df=pd.DataFrame)
    data = q.capital_flow('bj920026', date='20260918')
    assert calls == [(2, '920026', 0, 2000, 20260918), (2, '920026', 2000, 2000, 20260918)]
    assert data.attrs['trade_count'] == 2000
    assert data.attrs['total_turnover'] == 35_000_000


@pytest.mark.parametrize('method', ['minutes', 'transactions'])
def test_beijing_intraday_does_not_hide_network_failures(method):
    def fail(*args, **kwargs):
        raise TimeoutError('upstream timeout')

    q = object.__new__(StdQuotes)
    q.client = SimpleNamespace(get_history_minute_time_data=fail, get_history_transaction_data=fail)
    with pytest.raises(TimeoutError, match='upstream timeout'):
        getattr(q, method)('bj920026', date='20260918')


@pytest.mark.parametrize('method', ['minute', 'minutes', 'transactions'])
def test_intraday_still_rejects_invalid_symbols(method):
    q = object.__new__(StdQuotes)
    q.client = SimpleNamespace()
    with pytest.raises(TdxhubValidationException, match='证券代码错误'):
        getattr(q, method)('../920026')


def test_beijing_empty_minutes_remain_empty():
    q = object.__new__(StdQuotes)
    q.client = quote_api(struct.pack('<HI', 0, 0))
    data = q.minutes('bj920026', date='20260920')
    assert data.empty
    assert isinstance(data.index, pd.DatetimeIndex)
