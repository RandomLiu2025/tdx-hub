"""Price adjustment helpers."""

from __future__ import annotations

import pandas as pd

from tdxhub.gbbq import adjust_prices, adjustment_factors, normalize_gbbq
from tdxhub.utils.factor import fq_factor

_OHLC = ["open", "high", "low", "close"]
_ACTION_COLUMNS = ["fenhong", "peigu", "peigujia", "songzhuangu"]


def _method(value: str) -> str:
    normalized = str(value).lower()
    aliases = {"01": "qfq", "before": "qfq", "02": "hfq", "after": "hfq"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"qfq", "hfq"}:
        raise ValueError("复权方式必须是 qfq/01/before 或 hfq/02/after")
    return normalized


def factor_reversion(symbol: str, method: str = "qfq", raw: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adjust prices with a remote factor series without adding fake rows."""

    method = _method(method)
    if raw is None or raw.empty:
        return pd.DataFrame() if raw is None else raw.copy()

    factors = fq_factor(symbol, method).sort_index()
    if factors.empty:
        return raw.copy()

    data = raw.sort_index().copy()
    combined_index = factors.index.union(data.index).sort_values()
    aligned = factors["factor"].reindex(combined_index).ffill().bfill().reindex(data.index).astype(float)
    if method == "qfq" and aligned.iloc[-1] != 0:
        aligned = aligned / aligned.iloc[-1]

    for column in _OHLC:
        if column in data:
            data[column] = data[column].astype(float) * aligned
    data["factor"] = aligned
    return data


def _prepare_actions(xdxr_data: pd.DataFrame | None) -> pd.DataFrame:
    if xdxr_data is None or xdxr_data.empty or "category" not in xdxr_data.columns:
        return pd.DataFrame()
    return normalize_gbbq(xdxr_data)


def _reference_preclose(raw: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Build each trading day's ex-rights reference previous close."""

    result = raw["close"].shift(1).astype(float)
    if len(raw) < 2 or actions.empty:
        return result

    events = actions.loc[actions["category"].eq(1)].sort_index(kind="stable")
    for position in range(1, len(raw)):
        previous_day = pd.Timestamp(raw.index[position - 1]).normalize()
        current_day = pd.Timestamp(raw.index[position]).normalize()
        interval = events.loc[(events.index > previous_day) & (events.index <= current_day)]
        price = result.iloc[position]
        for _, event in interval.iterrows():
            denominator = 10 + event.get("peigu", 0) + event.get("songzhuangu", 0)
            if denominator == 0:
                continue
            price = (
                price * 10
                - event.get("fenhong", 0)
                + event.get("peigu", 0) * event.get("peigujia", 0)
            ) / denominator
        result.iloc[position] = price
    return result


def _reversion(bfq_data: pd.DataFrame, xdxr_data: pd.DataFrame, type_: str) -> pd.DataFrame:
    """Adjust stock prices using TDX category-1 corporate actions."""

    method = _method(type_)
    if bfq_data is None or bfq_data.empty:
        return pd.DataFrame() if bfq_data is None else bfq_data.copy()

    raw = bfq_data.sort_index().copy()
    actions = _prepare_actions(xdxr_data)
    if actions.empty or "category" not in actions or not actions["category"].eq(1).any():
        return raw

    if "volume" not in raw and "vol" in raw:
        raw["volume"] = raw["vol"]
    required = set(_OHLC + ["volume"])
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise ValueError(f"行情数据缺少字段: {', '.join(missing)}")
    if not isinstance(raw.index, pd.DatetimeIndex):
        raise ValueError("行情数据索引必须是日期")

    raw["preclose"] = _reference_preclose(raw, actions)
    factors = adjustment_factors(raw.index, actions)
    result = adjust_prices(raw, actions, method)
    result["adj"] = factors[f"{method}_mul"].to_numpy()
    return result.loc[result["open"].ne(0)]


def etf_reversion(data: pd.DataFrame, xdxr: pd.DataFrame, adjust: str = "01") -> pd.DataFrame:
    """Adjust fund prices using TDX category-11 split factors."""

    method = _method(adjust)
    actions = _prepare_actions(xdxr)
    if data is None or data.empty or actions.empty or "category" not in actions:
        return data.copy()
    actions = actions.loc[actions["category"].eq(11)]
    if actions.empty or "suogu" not in actions:
        return data.copy()

    result = data.copy()
    if not isinstance(result.index, pd.DatetimeIndex):
        if {"year", "month", "day"}.issubset(result.columns):
            result.index = pd.to_datetime(result[["year", "month", "day"]])
        elif "datetime" in result:
            result.index = pd.to_datetime(result["datetime"])
        else:
            raise ValueError("基金行情缺少日期")

    factors = actions["suogu"].reindex(actions.index.union(result.index)).sort_index()
    factors = (factors.bfill() if method == "qfq" else factors.ffill()).reindex(result.index).fillna(1.0)
    if method == "qfq":
        factors = factors.shift(-1, fill_value=1.0)
    for column in _OHLC:
        result[column] = result[column] / factors if method == "qfq" else result[column] * factors
    return result


def reversion(symbol: str, stock_data: pd.DataFrame, xdxr: pd.DataFrame, type_: str = "01") -> pd.DataFrame:
    """Adjust an OHLCV frame using the supplied TDX corporate actions."""

    _method(type_)
    if symbol.startswith(("15", "16", "50", "51")):
        return etf_reversion(stock_data, xdxr, type_)
    return _reversion(stock_data, xdxr, type_)


def baoli_qfq(df: pd.DataFrame, xdxr: pd.DataFrame) -> pd.DataFrame:
    """Compatibility implementation of iterative forward adjustment."""

    result = df.copy()
    for _, action in _prepare_actions(xdxr).iterrows():
        before = result.index < action.name
        denominator = 10 + action.get("peigu", 0) + action.get("songzhuangu", 0)
        for column in _OHLC:
            result.loc[before, column] = (
                result.loc[before, column] * 10
                - action.get("fenhong", 0)
                + action.get("peigu", 0) * action.get("peigujia", 0)
            ) / denominator
    return result
