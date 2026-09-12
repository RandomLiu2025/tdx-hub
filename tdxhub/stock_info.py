"""Helpers for assembling normalized stock information."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import date, datetime
from typing import Any

import pandas as pd

from tdxhub.gbbq import get_equity_snapshot
from tdxhub.security import classify_security

INDUSTRY_COLUMNS = [
    "tdx_industry_code",
    "tdx_industry_name",
    "tdx_industry_source",
    "sw_industry_code",
    "sw_industry_name",
    "sw_industry_source",
    "sw_level1_code",
    "sw_level1_name",
    "sw_level2_code",
    "sw_level2_name",
    "sw_level3_code",
    "sw_level3_name",
]

STOCK_INFO_COLUMNS = [
    "full_code",
    "exchange",
    "market_id",
    "code",
    "name",
    "category",
    "board",
    "last_price",
    "pre_close_price",
    "open_price",
    "high_price",
    "low_price",
    "change",
    "change_pct",
    "volume_hand",
    "amount",
    "open_amount_yuan",
    "circulating_shares",
    "total_shares",
    "turnover_rate",
    "circulating_market_value",
    "total_market_value",
    "eps",
    "ipo_date",
    "updated_date",
    *INDUSTRY_COLUMNS,
]

_CATEGORY_NAMES = {
    "a_stock": "a_share",
    "b_stock": "b_share",
    "index": "index",
    "etf": "etf",
    "fund": "fund",
    "bond": "bond",
    "other": "other",
}
_EPS_FIELDS = ("eps", "basic_eps", "diluted_eps", "meigushouyi")
_DATE_DIGITS = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def empty_stock_info_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STOCK_INFO_COLUMNS, dtype=object)


def safe_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_code(value: Any) -> str | None:
    if value is None:
        return None
    code = str(value).strip()
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    if not code.isdigit():
        return None
    return code.zfill(6)


def normalize_market_id(value: Any) -> int | None:
    aliases = {0: 0, 1: 1, 2: 2, "0": 0, "1": 1, "2": 2, "sz": 0, "sh": 1, "bj": 2}
    key = value.lower() if isinstance(value, str) else value
    return aliases.get(key)


def frame_record(frame: pd.DataFrame | None) -> dict[str, Any] | None:
    if frame is None or frame.empty:
        return None
    return deepcopy(frame.iloc[0].to_dict())


def normalize_date(value: Any) -> str | None:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
    else:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "nat", "none"}:
            return None
        match = _DATE_DIGITS.fullmatch(text.removesuffix(".0"))
        try:
            timestamp = pd.Timestamp("-".join(match.groups())) if match else pd.Timestamp(text)
        except (TypeError, ValueError):
            return None
    if pd.isna(timestamp):
        return None
    return timestamp.strftime("%Y-%m-%d")


def category_and_board(market_id: int, code: str, name: Any) -> tuple[str, str | None]:
    category = _CATEGORY_NAMES[classify_security(market_id, code, name)]
    if category != "a_share":
        return category, None
    if market_id == 2:
        return category, "北交所"
    if market_id == 0 and code.startswith(("300", "301")):
        return category, "创业板"
    if market_id == 1 and code.startswith(("688", "689")):
        return category, "科创板"
    return category, "主板"


def equity_values(
    actions: pd.DataFrame | None,
    finance: dict[str, Any] | None,
    *,
    code: str,
) -> tuple[int | None, int | None]:
    snapshot = None
    if actions is not None and not actions.empty:
        snapshot = get_equity_snapshot(actions, code=code if "code" in actions.columns else None)

    scale = 10_000 if actions is not None and actions.attrs.get("equity_unit") == "ten_thousand_shares" else 1
    circulating = safe_number(snapshot.float_equity * scale) if snapshot is not None else None
    total = safe_number(snapshot.total_equity * scale) if snapshot is not None else None
    if circulating is None or circulating <= 0:
        circulating = safe_number((finance or {}).get("liutongguben"))
    if total is None or total <= 0:
        total = safe_number((finance or {}).get("zongguben"))

    return (
        int(circulating) if circulating is not None and circulating > 0 else None,
        int(total) if total is not None and total > 0 else None,
    )


def auction_open_amount(frame: pd.DataFrame | None) -> float | None:
    if frame is None or frame.empty:
        return None
    for _, row in frame.iloc[::-1].iterrows():
        price = safe_number(row.get("price"))
        matched = safe_number(row.get("matched"))
        if price is not None and price > 0 and matched is not None and matched >= 0:
            return price * matched * 100.0
    return None


def build_stock_info_row(
    *,
    market_id: int,
    exchange: str,
    code: str,
    security: dict[str, Any] | None,
    quote: dict[str, Any] | None,
    finance: dict[str, Any] | None,
    actions: pd.DataFrame | None,
    auction: pd.DataFrame | None,
    industry: dict[str, Any] | None,
) -> dict[str, Any]:
    industry = industry or {}

    name = security.get("name") if security else None
    category, board = category_and_board(market_id, code, name)

    last_price = safe_number((quote or {}).get("price"))
    pre_close_price = safe_number((quote or {}).get("last_close"))
    open_price = safe_number((quote or {}).get("open"))
    high_price = safe_number((quote or {}).get("high"))
    low_price = safe_number((quote or {}).get("low"))
    volume_hand = safe_number((quote or {}).get("vol", (quote or {}).get("volume")))
    amount = safe_number((quote or {}).get("amount"))

    change = None
    change_pct = None
    if last_price is not None and pre_close_price is not None:
        change = last_price - pre_close_price
        if pre_close_price > 0:
            change_pct = change / pre_close_price * 100.0

    circulating_shares, total_shares = equity_values(actions, finance, code=code)
    turnover_rate = None
    if volume_hand is not None and volume_hand >= 0 and circulating_shares:
        turnover_rate = volume_hand * 100.0 / circulating_shares * 100.0

    circulating_market_value = None
    total_market_value = None
    if last_price is not None and last_price >= 0:
        if circulating_shares:
            circulating_market_value = last_price * circulating_shares
        if total_shares:
            total_market_value = last_price * total_shares

    eps = None
    for field in _EPS_FIELDS:
        if field in (finance or {}):
            eps = safe_number(finance[field])
            break

    row = {
        "full_code": f"{exchange}{code}",
        "exchange": exchange,
        "market_id": market_id,
        "code": code,
        "name": name,
        "category": category,
        "board": board,
        "last_price": last_price,
        "pre_close_price": pre_close_price,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "change": change,
        "change_pct": change_pct,
        "volume_hand": volume_hand,
        "amount": amount,
        "open_amount_yuan": auction_open_amount(auction),
        "circulating_shares": circulating_shares,
        "total_shares": total_shares,
        "turnover_rate": turnover_rate,
        "circulating_market_value": circulating_market_value,
        "total_market_value": total_market_value,
        "eps": eps,
        "ipo_date": normalize_date((finance or {}).get("ipo_date")),
        "updated_date": normalize_date((finance or {}).get("updated_date")),
    }
    row.update({column: deepcopy(industry.get(column)) for column in INDUSTRY_COLUMNS})
    return row
