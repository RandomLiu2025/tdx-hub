"""Classification helpers for standard-market security directories."""

from __future__ import annotations

from collections.abc import Hashable

import pandas as pd

from tdxhub.exceptions import TdxhubValidationException

SECURITY_TYPES = frozenset({"a_stock", "b_stock", "index", "etf", "fund", "bond", "other"})

_MARKETS = {
    0: 0,
    1: 1,
    2: 2,
    "sz": 0,
    "sh": 1,
    "bj": 2,
}

_SZ_BOND_PREFIXES = ("10", "11", "12", "13", "14")
_SZ_FUND_PREFIXES = ("15", "16", "18")
_SH_ETF_PREFIXES = ("51", "56", "588", "589")
_SH_BOND_PREFIXES = ("01", "02", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20")
_SH_FUND_PREFIXES = ("50", "51", "52", "56", "58")


def normalize_security_type(security_type: str | None) -> str | None:
    """Normalize and validate a public security-directory filter."""
    if security_type is None:
        return None
    if not isinstance(security_type, str):
        raise TdxhubValidationException("security_type 必须是字符串或 None")

    normalized = security_type.strip().lower()
    if normalized not in SECURITY_TYPES:
        values = ", ".join(sorted(SECURITY_TYPES))
        raise TdxhubValidationException(f"security_type 必须是以下值之一: {values}")
    return normalized


def _normalize_market(market: Hashable) -> int:
    key = market.lower() if isinstance(market, str) else market
    try:
        return _MARKETS[key]
    except (KeyError, TypeError) as exc:
        raise TdxhubValidationException(f"不支持的证券市场: {market!r}") from exc


def _normalize_code(code: object) -> str:
    value = str(code).strip()
    return value.zfill(6) if value.isdigit() and len(value) < 6 else value


def classify_security(market: Hashable, code: object, name: object = "") -> str:
    """Classify one standard-market directory row by market, code and name."""
    normalized_market = _normalize_market(market)
    normalized_code = _normalize_code(code)
    normalized_name = "" if name is None else str(name).upper()

    if normalized_market == 2:
        return "a_stock"

    if normalized_market == 0:
        if normalized_code.startswith(("00", "30")):
            return "a_stock"
        if normalized_code.startswith("20"):
            return "b_stock"
        if normalized_code.startswith("39"):
            return "index"
        if normalized_code.startswith("159") or "ETF" in normalized_name:
            return "etf"
        if normalized_code.startswith(_SZ_BOND_PREFIXES):
            return "bond"
        if normalized_code.startswith(_SZ_FUND_PREFIXES):
            return "fund"
        return "other"

    if normalized_code.startswith(("60", "68")):
        return "a_stock"
    if normalized_code.startswith("90"):
        return "b_stock"
    if normalized_code.startswith(("00", "88", "99")):
        return "index"
    if normalized_code.startswith(_SH_ETF_PREFIXES) or "ETF" in normalized_name:
        return "etf"
    if normalized_code.startswith(_SH_BOND_PREFIXES):
        return "bond"
    if normalized_code.startswith(_SH_FUND_PREFIXES):
        return "fund"
    return "other"


def filter_security_directory(
    frame: pd.DataFrame,
    market: Hashable,
    security_type: str | None = None,
) -> pd.DataFrame:
    """Filter a security directory without adding classification columns."""
    normalized_type = normalize_security_type(security_type)
    if normalized_type is None:
        return frame
    if "code" not in frame.columns:
        if frame.empty:
            return frame.reset_index(drop=True)
        raise TdxhubValidationException("证券目录缺少 code 字段")

    names = frame["name"] if "name" in frame.columns else pd.Series("", index=frame.index)
    matched = [
        classify_security(market, code, name) == normalized_type
        for code, name in zip(frame["code"], names, strict=True)
    ]
    result = frame.loc[matched].reset_index(drop=True)
    result.attrs = frame.attrs.copy()
    return result
