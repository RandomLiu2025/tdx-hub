"""Recorded finance bodies cross-checked against TDX professional financial files."""

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from tdxhub.quotes import StdQuotes
from tdxhub.tdx.errors import ProtocolError
from tdxhub.tdx.protocol.std.get_finance_info import GetFinanceInfo

FIXTURES = Path(__file__).parent / "fixtures" / "finance"
REFERENCE = json.loads((FIXTURES / "reference.json").read_text())["expected"]
DEPRECATED = ("guojiagu", "faqirenfarengu", "farengu", "zhigonggu", "changqifuzhai", "zhuyinglirun")
MARKETS = {"600519": 1, "000001": 0, "920002": 2, "601318": 1}


def parse(code="600519"):
    parser = GetFinanceInfo(None)
    parser.setParams(MARKETS[code], code)
    return parser.parseResponse((FIXTURES / f"{code}.bin").read_bytes())


@pytest.mark.parametrize("code", MARKETS)
def test_recorded_finance_units_and_mappings(code):
    row = parse(code)
    assert row["finance_schema"] == "tdx_finance_v2"
    for name, value in REFERENCE[code].items():
        if name in ("meigushouyi", "meigujingzichan"):
            tolerance = dict(abs=0.0051)
        elif name in ("liutongguben", "zongguben", "bgu", "hgu", "gudongrenshu"):
            tolerance = dict(rel=2e-5, abs=0.01)
        else:
            tolerance = dict(rel=2e-6, abs=1000)
        assert row[name] == pytest.approx(value, **tolerance), name
    assert all(row[name] is None for name in DEPRECATED)
    assert row["raw_fields"]["guojiagu"] == {"600519": 1215, "000001": 1966, "920002": 1234, "601318": 1968}[code]
    assert row["zongzichan"] == row["raw_fields"]["zongzichan"] * 1000
    assert row["zongguben"] == row["raw_fields"]["zongguben"] * 10000
    assert row["meigushouyi"] == row["raw_fields"]["zhigonggu"]
    assert row["baoliu2"] == row["raw_fields"]["baoliu2"] == 6


@pytest.mark.parametrize("code", MARKETS)
def test_sdk_finance_does_not_scale_twice_or_misclassify_reused_slots(code):
    row = parse(code)
    q = object.__new__(StdQuotes)
    q.client = SimpleNamespace(get_finance_info=lambda **kwargs: row)
    result = q.finance({0: "sz", 1: "sh", 2: "bj"}[MARKETS[code]] + code).iloc[0]
    assert result["zongzichan"] == row["zongzichan"]
    assert result["raw_fields"] == row["raw_fields"]
    quality = result["data_quality"]
    assert quality["status"] == "normalized"
    assert quality["issues"] == []
    assert quality["unverified_fields"] == ["guojiagu", "baoliu2"]
    assert "data_quality" not in row
    if code == "000001":
        assert quality["net_assets_per_share_ratio"] == pytest.approx(1.170735, rel=1e-5)
        assert quality["warnings"] == ["net_assets_per_share_basis_difference"]
    else:
        assert quality["warnings"] == []


def test_zero_response_and_zero_values_are_distinct():
    parser = GetFinanceInfo(None)
    assert parser.parseResponse(b"\0\0") == {}
    body = struct.pack("<HB6sfHHII30f", 1, 1, b"600519", 0, 0, 0, 20260815, 20010827, *([0] * 30))
    row = parser.parseResponse(body)
    assert row["zongzichan"] == row["meigushouyi"] == 0
    assert row["guojiagu"] is None


@pytest.mark.parametrize("body", [b"", b"\1", b"\1\0", b"\0\0x", b"\2\0"])
def test_invalid_count_or_short_body_is_protocol_error(body):
    with pytest.raises(ProtocolError, match="finance"):
        GetFinanceInfo(None).parseResponse(body)


@pytest.mark.parametrize("delta", [-1, 1])
def test_exact_record_length_required(delta):
    body = (FIXTURES / "600519.bin").read_bytes()
    body = body[:-1] if delta < 0 else body + b"x"
    with pytest.raises(ProtocolError, match="finance"):
        GetFinanceInfo(None).parseResponse(body)


@pytest.mark.parametrize("offset,value", [(2, b"\3"), (3, b"XXXXXX"), (3, b"\xff00000")])
def test_invalid_market_or_security_code_is_protocol_error(offset, value):
    body = bytearray((FIXTURES / "600519.bin").read_bytes())
    body[offset : offset + len(value)] = value
    with pytest.raises(ProtocolError, match="finance"):
        GetFinanceInfo(None).parseResponse(body)


@pytest.mark.parametrize("market,code", [(0, "600519"), (1, "600000"), (1, b"600000")])
def test_response_must_match_request(market, code):
    parser = GetFinanceInfo(None)
    parser.setParams(market, code)
    with pytest.raises(ProtocolError, match="finance"):
        parser.parseResponse((FIXTURES / "600519.bin").read_bytes())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("offset", [9, 53, 137, 141])
def test_nonfinite_float_is_rejected(value, offset):
    body = bytearray((FIXTURES / "600519.bin").read_bytes())
    struct.pack_into("<f", body, offset, value)
    with pytest.raises(ProtocolError, match="finance"):
        GetFinanceInfo(None).parseResponse(body)


def test_real_share_inconsistency_still_flagged():
    from tdxhub.data_quality import finance_quality

    row = parse()
    row["liutongguben"] = row["zongguben"] * 2
    quality = finance_quality(row)
    assert quality["status"] == "inconsistent"
    assert quality["issues"] == ["share_components_exceed_total"]


@pytest.mark.parametrize("as_bytes", [False, True])
def test_finance_request_wire_is_unchanged(as_bytes):
    parser = GetFinanceInfo(None)
    parser.setParams(2, b"920002" if as_bytes else "920002")
    assert parser.send_pkg == bytes.fromhex("0c1f187600010b000b0010000100") + struct.pack("<B6s", 2, b"920002")
