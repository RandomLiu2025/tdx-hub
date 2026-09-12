"""TDX call-auction request encoding and response decoding."""

from __future__ import annotations

from datetime import date, datetime
from struct import pack, unpack_from
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")

_HEADER_SIZE = 12
_RECORD_SIZE = 16
_CALL_AUCTION_TYPE = 0x056A
_REQUEST_TAIL = bytes.fromhex("00000000030000000000000000000000f4010000")


def build_call_auction_request(market: int, code: str) -> bytes:
    """Build a raw standard-market ``0x056A`` call-auction request frame."""
    if not isinstance(market, int) or isinstance(market, bool) or not 0 <= market <= 0xFF:
        raise ValueError("集合竞价市场代码必须是 0..255 的整数")
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError("集合竞价证券代码必须是 6 位 ASCII 数字")

    payload = bytes((market, 0)) + code.encode("ascii") + _REQUEST_TAIL
    length = len(payload) + 2
    header = pack("<BIBHHH", 0x0C, 0, 0x01, length, length, _CALL_AUCTION_TYPE)
    if len(header) != _HEADER_SIZE:  # pragma: no cover - protects the protocol definition
        raise AssertionError("集合竞价请求帧头长度异常")
    return header + payload


def _normalize_trade_date(value: date | datetime | str | None) -> date:
    if value is None:
        return datetime.now(_SHANGHAI).date()
    if isinstance(value, datetime):
        return value.astimezone(_SHANGHAI).date() if value.tzinfo is not None else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(normalized, fmt).date()
            except ValueError:
                continue
    raise ValueError("集合竞价交易日期格式错误，应为 YYYY-MM-DD 或 YYYYMMDD")


def decode_call_auction(payload: bytes, trade_date: date | datetime | str | None = None) -> list[dict]:
    """Decode a raw ``0x056A`` response body into call-auction records."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError("集合竞价响应必须是字节数据")
    payload = bytes(payload)
    if len(payload) < 2:
        raise ValueError(f"集合竞价响应头截断: 至少需要 2 字节，实际 {len(payload)} 字节")

    count = unpack_from("<H", payload)[0]
    required = 2 + count * _RECORD_SIZE
    if len(payload) < required:
        complete = max(0, (len(payload) - 2) // _RECORD_SIZE)
        raise ValueError(
            f"集合竞价响应第 {complete + 1} 条记录截断: "
            f"共 {count} 条，需要 {required} 字节，实际 {len(payload)} 字节"
        )

    day = _normalize_trade_date(trade_date)
    rows = []
    for index in range(count):
        offset = 2 + index * _RECORD_SIZE
        minute, price, matched, signed_unmatched, _reserved, second = unpack_from(
            "<HfIiBB", payload, offset
        )
        hour, minute_in_hour = divmod(minute, 60)
        if hour > 23 or second > 59:
            raise ValueError(
                f"集合竞价第 {index + 1} 条时间无效: minute={minute}, second={second}"
            )
        rows.append(
            {
                "datetime": datetime.combine(day, datetime.min.time()).replace(
                    hour=hour, minute=minute_in_hour, second=second, tzinfo=_SHANGHAI
                ),
                "price": round(float(price), 3),
                "matched": matched,
                "unmatched": abs(signed_unmatched),
                "flag": -1 if signed_unmatched < 0 else 1,
            }
        )
    return rows
