"""Synthetic extended-minute wire checks, not live market-accuracy evidence."""

import struct
import zlib

import pytest

from tdxhub.quotes import ExtQuotes
from tdxhub.tdx.errors import ProtocolError, TdxFunctionCallError
from tdxhub.tdx.extended import ExtendedClient
from tests.tdx.test_protocol import SocketFixture, response_header


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    from tenacity import wait_none

    for method in (ExtQuotes.minute, ExtQuotes.minutes):
        while hasattr(method, "retry"):
            monkeypatch.setattr(method.retry, "wait", wait_none())
            method = method.__wrapped__


# Intentionally cross midnight and use non-stock prices / large unsigned counts.
# Values describe the current wire contract, not exchange-verified field units.
ROWS = [
    (23 * 60 + 59, 1234.125, 1230.25, 17, 100000),
    (0, 1234.5, 1231.75, 0, 100000),
    (1, 1235.0, 1232.5, 2**31 + 3, 2**31 + 9),
]


def minute_body(historical, rows):
    if historical:
        header = struct.pack('<B9s8sH', 47, b'IF2610', bytes(8), len(rows))
    else:
        header = struct.pack('<B9sH', 47, b'IF2610', len(rows))
    return header + b''.join(struct.pack('<HffII', *row) for row in rows)


def minute_client(body, compressed=False, repeats=1):
    wire = zlib.compress(body) if compressed else body
    api = ExtendedClient(auto_retry=False, raise_exception=True)
    api.client = SocketFixture([response_header(body, wire), wire] * repeats)
    return api


def expected_request(historical):
    if historical:
        return bytes.fromhex('01 01 30 00 01 01 10 00 10 00 0c 24') + struct.pack(
            '<IB9s', 20260921, 47, b'IF2610'
        )
    return bytes.fromhex('01 07 08 00 01 01 0c 00 0c 00 0b 24') + struct.pack('<B9s', 47, b'IF2610')


@pytest.mark.parametrize('historical', [False, True])
@pytest.mark.parametrize('compressed', [False, True])
@pytest.mark.parametrize('rows', [[], ROWS])
def test_extended_public_minute_routes_and_preserves_wire_values(historical, compressed, rows):
    quotes = object.__new__(ExtQuotes)
    attempts = 1 if rows else 3  # Legacy raw-client wrapper retries empty frames.
    quotes.client = minute_client(minute_body(historical, rows), compressed, repeats=attempts)

    if historical:
        frame = quotes.minutes(symbol='47#IF2610', date=20260921)
    else:
        frame = quotes.minute(symbol='47#IF2610')

    assert quotes.client.client.sent == [expected_request(historical)] * attempts
    assert len(frame) == len(rows)
    if not rows:
        assert frame.empty
        return
    assert list(frame.columns) == ['hour', 'minute', 'price', 'avg_price', 'volume', 'open_interest']
    assert frame['hour'].tolist() == [23, 0, 0]
    assert frame['minute'].tolist() == [59, 0, 1]
    assert frame['price'].tolist() == pytest.approx([row[1] for row in rows])
    assert frame['avg_price'].tolist() == pytest.approx([row[2] for row in rows])
    assert frame['volume'].tolist() == [row[3] for row in rows]
    assert frame['open_interest'].tolist() == [row[4] for row in rows]
    # The API does not invent a date, reorder the night session or scale volume.
    assert frame.index.tolist() == [0, 1, 2]


@pytest.mark.parametrize('historical', [False, True])
@pytest.mark.parametrize('cut', [1, 18, 19])
def test_extended_minute_truncated_payload_is_not_a_partial_success(historical, cut):
    api = minute_client(minute_body(historical, ROWS)[:-cut])
    with pytest.raises(TdxFunctionCallError) as caught:
        if historical:
            api.get_history_minute_time_data(47, 'IF2610', 20260921)
        else:
            api.get_minute_time_data(47, 'IF2610')
    assert isinstance(caught.value.original_exception, ProtocolError)
    assert 'body_length=' in str(caught.value)
