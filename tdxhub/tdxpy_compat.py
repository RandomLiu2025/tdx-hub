"""Narrow compatibility fixes for known tdxpy protocol-decoding defects."""

from __future__ import annotations

import math
import struct
import warnings
from collections.abc import Mapping
from typing import Any

from tdxpy.base_socket_client import last_ack_time
from tdxpy.constants import TDXParams
from tdxpy.helper import get_security_coefficient
from tdxpy.hq import TdxHq_API as _TdxHq_API
from tdxpy.parser.std.get_security_list import GetSecurityList

from tdxhub.security import classify_security

_FUND_PRICE_COEFFICIENT = 0.001
_QUOTE_PRICE_FIELDS = (
    "price",
    "last_close",
    "open",
    "high",
    "low",
    "bid1",
    "ask1",
    "bid2",
    "ask2",
    "bid3",
    "ask3",
    "bid4",
    "ask4",
    "bid5",
    "ask5",
)
_SECURITY_LIST_RECORD_SIZE = 29
_SECURITY_LIST_PRE_CLOSE_OFFSET = 21


def normalize_security_quotes(rows: Any) -> Any:
    """Correct fund price fields when tdxpy selected a stale coefficient.

    The correction is capability-based: once tdxpy recognizes the security and
    returns the expected coefficient, the row passes through unchanged.
    """
    if not isinstance(rows, (list, tuple)):
        return rows

    normalized = []
    for row in rows:
        if not isinstance(row, Mapping):
            normalized.append(row)
            continue

        market = row.get("market")
        code = row.get("code")
        try:
            security_type = classify_security(market, code)
        except (TypeError, ValueError):
            normalized.append(row)
            continue
        if security_type not in {"etf", "fund"}:
            normalized.append(row)
            continue

        actual_coefficient = get_security_coefficient(market, code)
        if not actual_coefficient or math.isclose(
            actual_coefficient,
            _FUND_PRICE_COEFFICIENT,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            normalized.append(row)
            continue

        ratio = _FUND_PRICE_COEFFICIENT / actual_coefficient
        corrected = row.copy()
        for field in _QUOTE_PRICE_FIELDS:
            value = corrected.get(field)
            if isinstance(value, int | float) and not isinstance(value, bool):
                corrected[field] = value * ratio
        normalized.append(corrected)

    return normalized


class FixedGetSecurityList(GetSecurityList):
    """Decode directory ``pre_close`` as the float32 carried by TDX."""

    def parseResponse(self, body_buf):  # noqa: N802 - inherited tdxpy API
        rows = super().parseResponse(body_buf)
        for index, row in enumerate(rows):
            offset = 2 + index * _SECURITY_LIST_RECORD_SIZE + _SECURITY_LIST_PRE_CLOSE_OFFSET
            (row["pre_close"],) = struct.unpack_from("<f", body_buf, offset)
        return rows


class TdxHq_API(_TdxHq_API):  # noqa: N801 - preserve the dependency's public class name
    """Use the corrected security-directory parser and inherit all other APIs."""

    @last_ack_time
    def get_security_list(self, market, start):
        if market == TDXParams.MARKET_BJ:
            warnings.warn("此接口暂时不支持北证A股", DeprecationWarning, stacklevel=2)
            return None

        cmd = FixedGetSecurityList(self.client, lock=self.lock)
        cmd.setParams(market, start)
        return cmd.call_api()
