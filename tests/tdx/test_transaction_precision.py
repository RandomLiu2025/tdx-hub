"""Recorded instrument precision: transactions do not share bond quote scaling."""

import struct

import pytest

from tdxhub.tdx.protocol.std.get_history_transaction_data import GetHistoryTransactionData
from tdxhub.tdx.protocol.std.get_transaction_data import GetTransactionData
from tests.tdx.test_price_decoding import encode_price


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("as_bytes", [False, True])
@pytest.mark.parametrize(
    "market,code,raw,expected",
    [
        (1, "600519", 125712, 1257.12),
        (0, "000001", 1170, 11.7),
        (2, "920002", 5002, 50.02),
        (1, "510300", 4582, 4.582),
        (0, "159915", 3391, 3.391),
        (1, "113052", 112637, 112.637),
        (0, "127045", 112637, 112.637),
        (1, "900901", 1234, 1.234),
    ],
)
def test_transaction_precision(historical, as_bytes, market, code, raw, expected):
    parser = (GetHistoryTransactionData if historical else GetTransactionData)(client=None)
    args = [market, code.encode() if as_bytes else code, 0, 2]
    if historical:
        args.append("20260918")
    parser.setParams(*args)
    body = struct.pack("<H", 2) + (b"\0" * 4 if historical else b"")
    for price in [raw, -1]:
        fields = [price, 10] + ([] if historical else [2]) + [0, 0]
        body += struct.pack("<H", 9 * 60 + 31) + b"".join(map(encode_price, fields))
    ticks = parser.parseResponse(body)
    assert ticks[0]["price"] == pytest.approx(expected)
    assert ticks[1]["price"] == pytest.approx(expected * (raw - 1) / raw)
    assert ticks[0]["vol"] == 10
