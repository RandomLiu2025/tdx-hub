from __future__ import annotations

import struct

import pytest

from tdxhub.quotes import StdQuotes
from tdxhub.tdxpy_compat import FixedGetSecurityList, normalize_security_quotes
from tdxhub.utils import get_stock_market


@pytest.mark.parametrize("code", ["520500", "560010", "588000", "589000"])
def test_shanghai_fund_prefixes_route_to_shanghai(code):
    assert get_stock_market(code) == 1


@pytest.mark.parametrize(
    "code, raw_price, expected",
    [
        ("588000", 16.39, 1.639),
        ("560010", 30.91, 3.091),
        ("520500", 13.34, 1.334),
    ],
)
def test_normalize_security_quotes_corrects_unsupported_fund_coefficients(monkeypatch, code, raw_price, expected):
    monkeypatch.setattr("tdxhub.tdxpy_compat.get_security_coefficient", lambda market, symbol: 0.01)
    row = {
        "market": 1,
        "code": code,
        "price": raw_price,
        "last_close": raw_price,
        "open": raw_price,
        "high": raw_price,
        "low": raw_price,
        "bid1": raw_price,
        "ask5": raw_price,
        "vol": 123,
        "amount": 456.0,
        "bid_vol1": 78,
    }

    result = normalize_security_quotes([row])

    for field in ("price", "last_close", "open", "high", "low", "bid1", "ask5"):
        assert result[0][field] == pytest.approx(expected)
    assert result[0]["vol"] == 123
    assert result[0]["amount"] == 456.0
    assert result[0]["bid_vol1"] == 78
    assert row["price"] == raw_price


def test_normalize_security_quotes_does_not_double_correct_fixed_dependency(monkeypatch):
    monkeypatch.setattr("tdxhub.tdxpy_compat.get_security_coefficient", lambda market, symbol: 0.001)
    row = {"market": 1, "code": "588000", "price": 1.639, "bid1": 1.638, "vol": 100}

    assert normalize_security_quotes([row]) == [row]


class _QuoteClient:
    def get_security_quotes(self, symbols):
        assert symbols == [[1, "588000"]]
        return [
            {
                "market": 1,
                "code": "588000",
                "price": 16.39,
                "last_close": 16.59,
                "vol": 100,
                "active1": 1,
                "reversed_bytes0": 2,
            }
        ]


def test_quotes_applies_compatibility_before_dataframe_conversion(monkeypatch):
    monkeypatch.setattr("tdxhub.tdxpy_compat.get_security_coefficient", lambda market, symbol: 0.01)
    quotes = object.__new__(StdQuotes)
    quotes.client = _QuoteClient()

    result = quotes.quotes("588000")

    assert result.loc[0, "price"] == pytest.approx(1.639)
    assert result.loc[0, "last_close"] == pytest.approx(1.659)
    assert result.loc[0, "vol"] == 100
    assert "active1" not in result
    assert "reversed_bytes0" not in result


@pytest.mark.parametrize(
    "code, raw_hex, expected",
    [
        ("159915", "79e95640", 3.358),
        ("510020", "96437b40", 3.926),
        ("510050", "25064140", 3.016),
        ("510300", "77be9340", 4.617),
        ("588000", "1d5ad43f", 1.659),
    ],
)
def test_security_list_decodes_pre_close_as_little_endian_float(code, raw_hex, expected):
    name = "ETF".encode("gbk").ljust(8, b"\x00")
    record = struct.pack(
        "<6sH8s4sB4s4s",
        code.encode("ascii"),
        100,
        name,
        b"\x00" * 4,
        3,
        bytes.fromhex(raw_hex),
        b"\x00" * 4,
    )
    body = struct.pack("<H", 1) + record

    rows = FixedGetSecurityList(client=None).parseResponse(body)

    assert rows[0]["code"] == code
    assert rows[0]["pre_close"] == pytest.approx(expected, abs=1e-6)
