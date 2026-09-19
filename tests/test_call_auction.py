from datetime import UTC, date, datetime
from struct import pack
from zoneinfo import ZoneInfo

import pytest

from tdxhub.call_auction import build_call_auction_request, decode_call_auction
from tdxhub.exceptions import TdxhubValidationException
from tdxhub.quotes import StdQuotes


def _record(minute, price, matched, unmatched, second):
    return pack("<HfIiBB", minute, price, matched, unmatched, 0, second)


def _payload():
    return pack("<H", 3) + b"".join(
        [
            _record(9 * 60 + 15, 11.75, 725, -78604, 0),
            _record(9 * 60 + 15, 11.70, 920, 414, 9),
            _record(9 * 60 + 24, 16.34, 5401, 109912, 57),
        ]
    )


def test_build_call_auction_request_matches_go_protocol_frame():
    request = build_call_auction_request(0, "000001")

    assert request.hex() == (
        "0c00000000011e001e006a05"
        "0000303030303031"
        "00000000030000000000000000000000f4010000"
    )


@pytest.mark.parametrize(
    ("market", "code"),
    [(-1, "000001"), (256, "000001"), (0, "12345"), (0, "股票01")],
)
def test_build_call_auction_request_rejects_invalid_market_or_code(market, code):
    with pytest.raises(ValueError):
        build_call_auction_request(market, code)


def test_decode_call_auction_preserves_signed_int32_direction_and_timestamp():
    rows = decode_call_auction(_payload(), trade_date=date(2026, 9, 10))

    assert rows == [
        {
            "datetime": datetime(2026, 9, 10, 9, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "price": 11.75,
            "matched": 725,
            "unmatched": 78604,
            "flag": -1,
        },
        {
            "datetime": datetime(2026, 9, 10, 9, 15, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
            "price": pytest.approx(11.70),
            "matched": 920,
            "unmatched": 414,
            "flag": 1,
        },
        {
            "datetime": datetime(2026, 9, 10, 9, 24, 57, tzinfo=ZoneInfo("Asia/Shanghai")),
            "price": pytest.approx(16.34),
            "matched": 5401,
            "unmatched": 109912,
            "flag": 1,
        },
    ]


def test_decode_call_auction_reports_truncated_payload_with_context():
    with pytest.raises(ValueError, match=r"集合竞价.*第 3 条.*需要 50 字节.*实际 49 字节"):
        decode_call_auction(_payload()[:-1])


class _CallAuctionClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def send_raw_pkg(self, request):
        self.requests.append(request)
        return self.payload


def test_std_quotes_call_auction_normalizes_symbol_and_returns_dataframe():
    quotes = object.__new__(StdQuotes)
    quotes.client = _CallAuctionClient(_payload())

    result = quotes.call_auction("SH.600000", trade_date="2026-09-10")

    assert result[["price", "matched", "unmatched", "flag"]].to_dict("records") == [
        {"price": 11.75, "matched": 725, "unmatched": 78604, "flag": -1},
        {"price": pytest.approx(11.70), "matched": 920, "unmatched": 414, "flag": 1},
        {"price": pytest.approx(16.34), "matched": 5401, "unmatched": 109912, "flag": 1},
    ]
    assert result.index[0] == datetime(2026, 9, 10, 9, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert quotes.client.requests == [build_call_auction_request(1, "600000")]


def test_std_quotes_call_auction_wraps_invalid_symbol():
    quotes = object.__new__(StdQuotes)
    quotes.client = _CallAuctionClient(_payload())

    with pytest.raises(TdxhubValidationException, match="证券代码错误"):
        quotes.call_auction("invalid")


def test_call_auction_aware_trade_date_uses_shanghai_calendar_day():
    rows = decode_call_auction(_payload(), trade_date=datetime(2026, 9, 9, 23, tzinfo=UTC))
    assert rows[0]["datetime"].isoformat() == "2026-09-10T09:15:00+08:00"


def test_call_auction_default_date_does_not_depend_on_host_timezone(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Asia/Shanghai"
            return datetime(2026, 9, 10, 0, 1, tzinfo=tz)
    monkeypatch.setattr("tdxhub.call_auction.datetime", Clock)
    assert decode_call_auction(_payload())[0]["datetime"].date() == date(2026, 9, 10)
