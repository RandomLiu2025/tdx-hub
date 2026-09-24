"""Real minute-bar zero fields and independent float32 nonzero controls."""

import json
import struct
from pathlib import Path

import pytest

from tdxhub.tdx.codec import get_volume
from tdxhub.tdx.protocol.std.get_security_bars import GetSecurityBarsCmd


def test_captured_beijing_minute_zero_volume():
    fixture = json.loads((Path(__file__).parent / "fixtures/beijing_minute_zero.json").read_text(encoding="utf-8"))
    parser = GetSecurityBarsCmd(None)
    parser.setParams(8, 2, "920001", 0, 5)
    rows = parser.parseResponse(bytes.fromhex(fixture["body_hex"]))
    assert len(rows) == 5
    for row, expected in zip(rows, fixture["records"], strict=True):
        assert row["vol"] == expected["vol"]
        assert row["amount"] == expected["amount"]
    assert rows[3]["datetime"] == "2026-09-18 14:59"
    assert rows[3]["vol"] == rows[3]["amount"] == 0.0


@pytest.mark.parametrize("value", [0.0, 0.125, 1.0, 7873.0, 48940.0, 39435964.0, 57288340.0])
def test_volume_matches_float32_for_known_nonnegative_normal_values(value):
    raw = struct.unpack("<I", struct.pack("<f", value))[0]
    assert get_volume(raw) == struct.unpack("<f", struct.pack("<I", raw))[0]


def test_nonzero_small_encoding_is_not_rounded_to_zero():
    assert get_volume(1) > 0


@pytest.mark.parametrize(
    "raw", [0, 1, 0x7FFFFF, 0x800000, 0x3F7FFFFF, 0x3F800000, 0x3F800001, 0x40000000, 0x4B800000, 0x7F7FFFFF]
)
def test_volume_ieee754_boundaries(raw):
    assert get_volume(raw) == struct.unpack("<f", struct.pack("<I", raw))[0]
