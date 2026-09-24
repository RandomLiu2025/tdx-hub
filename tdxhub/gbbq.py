"""Semantic helpers for TDX GBBQ/XDXR corporate-action data."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pandas as pd

CATEGORY_NAMES = {
    1: "除权除息",
    2: "送配股上市",
    3: "非流通股上市",
    4: "未知股本变动",
    5: "股本变化",
    6: "增发新股",
    7: "股份回购",
    8: "增发新股上市",
    9: "转配股上市",
    10: "可转债上市",
    11: "扩缩股",
    12: "非流通股缩股",
    13: "送认购权证",
    14: "送认沽权证",
}

EQUITY_CATEGORIES = frozenset({2, 3, 5, 7, 8, 9, 10})
_ACTION_COLUMNS = ("fenhong", "peigujia", "songzhuangu", "peigu")
_NUMERIC_COLUMNS = (
    *_ACTION_COLUMNS,
    "suogu",
    "panqianliutong",
    "panhouliutong",
    "qianzongguben",
    "houzongguben",
    "fenshu",
    "xingquanjia",
)
_PRICE_COLUMNS = ("open", "high", "low", "close", "high_limit", "low_limit", "preclose")
_ZERO = Decimal(0)
_ONE = Decimal(1)
_TEN = Decimal(10)


@dataclass(frozen=True)
class EquitySnapshot:
    """Effective share-capital snapshot. Equity values are measured in shares."""

    date: pd.Timestamp
    category: int
    code: str | None
    float_equity: int
    total_equity: int

    def turnover(self, volume_shares: float) -> float:
        """Calculate turnover percentage from a volume measured in shares."""

        return turnover_rate(volume_shares, self.float_equity)


def _dates_from_frame(data: pd.DataFrame) -> pd.DatetimeIndex:
    if isinstance(data.index, pd.DatetimeIndex):
        dates = pd.DatetimeIndex(data.index)
    elif "date" in data.columns:
        dates = pd.DatetimeIndex(pd.to_datetime(data["date"], errors="raise"))
    elif {"year", "month", "day"}.issubset(data.columns):
        dates = pd.DatetimeIndex(pd.to_datetime(data[["year", "month", "day"]], errors="raise"))
    else:
        raise ValueError("GBBQ 数据缺少日期")
    return dates.normalize()


def normalize_gbbq(data: pd.DataFrame | None) -> pd.DataFrame:
    """Return a normalized copy of raw TDX GBBQ/XDXR records.

    The result uses a normalized ``date`` DatetimeIndex, preserves duplicate
    action dates, adds ``category_name`` and replaces missing numeric payload
    values with zero.
    """

    if data is None:
        return pd.DataFrame()
    if data.empty:
        result = data.copy()
        if not isinstance(result.index, pd.DatetimeIndex):
            result.index = pd.DatetimeIndex([], name="date")
        else:
            result.index = result.index.normalize().rename("date")
        return result

    result = data.copy()
    result.index = _dates_from_frame(result).rename("date")

    if "category" not in result.columns:
        raise ValueError("GBBQ 数据缺少 category 字段")
    result["category"] = pd.to_numeric(result["category"], errors="raise").astype(int)
    result["category_name"] = result["category"].map(lambda value: CATEGORY_NAMES.get(value, str(value)))

    for column in _NUMERIC_COLUMNS:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)

    return result.sort_index(kind="stable")


def turnover_rate(volume_shares: float, float_equity: float) -> float:
    """Calculate turnover percentage; both arguments use shares as the unit."""

    if pd.isna(volume_shares) or pd.isna(float_equity):
        return 0.0
    if volume_shares <= 0 or float_equity <= 0:
        return 0.0
    return float(volume_shares) / float(float_equity) * 100.0


def _normalized_bar_dates(data: pd.DataFrame) -> pd.DatetimeIndex:
    if isinstance(data.index, pd.DatetimeIndex):
        values = data.index
    elif "datetime" in data.columns:
        values = data["datetime"]
    elif "date" in data.columns:
        values = data["date"]
    else:
        raise ValueError("K线数据缺少日期")

    dates = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"))
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    return dates.normalize()


def _normalized_code(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    code = str(value).strip().upper().replace(".", "")
    for prefix in ("SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    return code.zfill(6) if code.isdigit() else code


def enrich_turnover(
    bars: pd.DataFrame,
    actions: pd.DataFrame | None,
    *,
    code: str | None = None,
    column: str = "turnover",
) -> pd.DataFrame:
    """Add historical daily turnover percentages to a copy of ``bars``.

    Daily-bar volume is measured in lots. Unmarked GBBQ float equity is
    interpreted as shares, while native online XDXR data marked with
    ``equity_unit=ten_thousand_shares`` is converted from ten-thousand shares
    to shares. Each bar uses the latest equity event effective on or before
    that trading date. Missing or non-positive equity remains ``NaN``.
    """

    result = bars.copy()
    if result.empty:
        result[column] = pd.Series(index=result.index, dtype="float64")
        result.attrs.update(
            {
                "turnover_unit": "percent",
                "turnover_volume_unit": "lots",
                "turnover_equity_unit": "shares",
            }
        )
        return result
    if "volume" not in result.columns:
        raise ValueError("K线数据缺少 volume 字段")

    equity_scale = 1.0
    if actions is not None and actions.attrs.get("equity_unit") == "ten_thousand_shares":
        equity_scale = 10_000.0

    turnover = pd.Series(float("nan"), index=range(len(result)), dtype="float64")
    normalized = normalize_gbbq(actions)

    if not normalized.empty:
        equity = normalized.loc[normalized["category"].isin(EQUITY_CATEGORIES)]
        if code is not None and "code" in equity.columns:
            wanted = _normalized_code(code)
            codes = equity["code"].map(_normalized_code)
            equity = equity.loc[codes == wanted]

        if not equity.empty and "panhouliutong" in equity.columns:
            equity_dates = pd.DatetimeIndex(equity.index)
            if equity_dates.tz is not None:
                equity_dates = equity_dates.tz_localize(None)
            equity_lookup = pd.DataFrame(
                {
                    "_date": equity_dates,
                    "_float_equity": (
                        pd.to_numeric(equity["panhouliutong"], errors="coerce").to_numpy()
                        * equity_scale
                    ),
                }
            )
            equity_lookup = equity_lookup.drop_duplicates("_date", keep="last").sort_values("_date")

            bar_lookup = pd.DataFrame(
                {"_date": _normalized_bar_dates(result), "_position": range(len(result))}
            )
            valid_bars = bar_lookup.loc[bar_lookup["_date"].notna()].sort_values("_date")
            if not valid_bars.empty:
                matched = pd.merge_asof(valid_bars, equity_lookup, on="_date", direction="backward")
                float_equity = pd.Series(float("nan"), index=range(len(result)), dtype="float64")
                float_equity.iloc[matched["_position"].to_numpy()] = matched["_float_equity"].to_numpy()
                volume_lots = pd.to_numeric(result["volume"], errors="coerce").reset_index(drop=True)
                valid = volume_lots.notna() & float_equity.gt(0)
                turnover.loc[valid] = (
                    volume_lots.loc[valid].clip(lower=0) * 100.0 / float_equity.loc[valid] * 100.0
                )

    result[column] = turnover.to_numpy()
    result.attrs.update(
        {
            "turnover_unit": "percent",
            "turnover_volume_unit": "lots",
            "turnover_equity_unit": "shares",
        }
    )
    return result


def get_equity_snapshot(
    data: pd.DataFrame | None,
    at: str | pd.Timestamp | None = None,
    *,
    code: str | None = None,
) -> EquitySnapshot | None:
    """Return the latest effective equity record at or before ``at``, in shares.

    Marked XDXR frames use ten-thousand shares; convert before truncating
    fractional shares so the fractional ten-thousands are not discarded.
    Unmarked local GBBQ frames already use shares.
    """

    actions = normalize_gbbq(data)
    if actions.empty:
        return None

    equity = actions.loc[actions["category"].isin(EQUITY_CATEGORIES)]
    if code is not None:
        if "code" not in equity.columns:
            return None
        equity = equity.loc[equity["code"].astype(str) == code]
    if at is not None:
        equity = equity.loc[equity.index <= pd.Timestamp(at).normalize()]
    if equity.empty:
        return None

    row = equity.iloc[-1]
    scale = 10_000 if actions.attrs.get("equity_unit") == "ten_thousand_shares" else 1
    row_code = row.get("code")
    if pd.isna(row_code):
        row_code = None
    return EquitySnapshot(
        date=pd.Timestamp(equity.index[-1]),
        category=int(row["category"]),
        code=None if row_code is None else str(row_code),
        float_equity=_integer_value(row.get("panhouliutong", 0) * scale),
        total_equity=_integer_value(row.get("houzongguben", 0) * scale),
    )


def _integer_value(value: object) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


def _decimal(value: object) -> Decimal:
    if value is None or pd.isna(value):
        return _ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"无法转换为数值: {value!r}") from exc


def _normalize_dates(dates: Iterable[object]) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="raise"))
    return result.normalize()


def _event_coefficients(row: pd.Series) -> tuple[Decimal, Decimal]:
    if row["category"] == 11:
        ratio = _decimal(row.get("suogu", 0))
        if not ratio.is_finite() or ratio <= 0:
            raise ValueError("扩缩股 suogu 必须是正有限数")
        return ratio, _ZERO
    dividend = _decimal(row.get("fenhong", 0))
    rights_price = _decimal(row.get("peigujia", 0))
    bonus = _decimal(row.get("songzhuangu", 0))
    rights = _decimal(row.get("peigu", 0))
    multiplier = (_TEN + bonus + rights) / _TEN
    cash = (dividend - rights * rights_price) / _TEN
    if multiplier == 0:
        multiplier = _ONE
    return multiplier, cash


def _decimal_factors(
    dates: Iterable[object], actions: pd.DataFrame | None
) -> tuple[pd.DatetimeIndex, list[tuple[Decimal, Decimal, Decimal, Decimal]]]:
    trading_dates = _normalize_dates(dates)
    if trading_dates.empty:
        return trading_dates, []

    normalized = normalize_gbbq(actions)
    if normalized.empty:
        identity = [(_ONE, _ZERO, _ONE, _ZERO) for _ in trading_dates]
        return trading_dates, identity

    events = normalized.loc[
        normalized["category"].isin([1, 11]) & (normalized.index <= trading_dates.max())
    ]
    if events.empty:
        identity = [(_ONE, _ZERO, _ONE, _ZERO) for _ in trading_dates]
        return trading_dates, identity

    # Compose backwards: reverse chronological order INCLUDING same-day source
    # order. This represents applying the original events forwards in time.
    ordered_events = list(events.sort_index(kind="stable").iloc[::-1].iterrows())
    positions = sorted(range(len(trading_dates)), key=lambda index: trading_dates[index], reverse=True)
    qfq = [(_ONE, _ZERO) for _ in trading_dates]
    multiplier, offset = _ONE, _ZERO
    event_index = 0

    for position in positions:
        trading_day = trading_dates[position]
        while event_index < len(ordered_events) and ordered_events[event_index][0] > trading_day:
            event_multiplier, cash = _event_coefficients(ordered_events[event_index][1])
            multiplier /= event_multiplier
            offset -= multiplier * cash
            event_index += 1
        qfq[position] = (multiplier, offset)

    anchor_multiplier, anchor_offset = qfq[positions[-1]]
    factors: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    for factor in qfq:
        qfq_multiplier, qfq_offset = factor
        if anchor_multiplier == 0:
            hfq_multiplier, hfq_offset = _ONE, _ZERO
        else:
            hfq_multiplier = qfq_multiplier / anchor_multiplier
            hfq_offset = (qfq_offset - anchor_offset) / anchor_multiplier
        factors.append((qfq_multiplier, qfq_offset, hfq_multiplier, hfq_offset))
    return trading_dates, factors


def adjustment_factors(dates: Iterable[object], actions: pd.DataFrame | None) -> pd.DataFrame:
    """Calculate daily affine QFQ/HFQ coefficients for trading dates."""

    index, factors = _decimal_factors(dates, actions)
    return pd.DataFrame(
        [[float(value) for value in factor] for factor in factors],
        index=index.rename("date"),
        columns=["qfq_mul", "qfq_add", "hfq_mul", "hfq_add"],
        dtype=float,
    )


def _method(value: str) -> str:
    method = str(value).lower()
    method = {"01": "qfq", "before": "qfq", "02": "hfq", "after": "hfq"}.get(method, method)
    if method not in {"qfq", "hfq"}:
        raise ValueError("复权方式必须是 qfq/01/before 或 hfq/02/after")
    return method


def _round_price(raw: object, multiplier: Decimal, offset: Decimal, quantum: Decimal) -> float:
    if pd.isna(raw):
        return float("nan")
    adjusted = multiplier * _decimal(raw) + offset
    return float(adjusted.quantize(quantum, rounding=ROUND_HALF_UP))


def adjust_prices(
    prices: pd.DataFrame | None, actions: pd.DataFrame | None, method: str = "qfq", *, price_decimals: int = 2
) -> pd.DataFrame:
    """Apply exact affine GBBQ adjustment without changing volume or amount."""

    normalized_method = _method(method)
    if price_decimals not in (2, 3):
        raise ValueError("价格精度仅支持 2 或 3 位小数")
    quantum = Decimal(1).scaleb(-price_decimals)
    if prices is None:
        return pd.DataFrame()
    result = prices.copy()
    if result.empty:
        return result

    if isinstance(result.index, pd.DatetimeIndex):
        dates = pd.DatetimeIndex(result.index).normalize()
    elif "date" in result.columns:
        dates = pd.DatetimeIndex(pd.to_datetime(result["date"], errors="raise")).normalize()
    elif {"year", "month", "day"}.issubset(result.columns):
        dates = pd.DatetimeIndex(pd.to_datetime(result[["year", "month", "day"]], errors="raise")).normalize()
    else:
        raise ValueError("行情数据缺少日期")

    _, factors = _decimal_factors(dates, actions)
    factor_offset = 0 if normalized_method == "qfq" else 2
    for column in _PRICE_COLUMNS:
        if column not in result.columns:
            continue
        result[column] = [
            _round_price(raw, factor[factor_offset], factor[factor_offset + 1], quantum)
            for raw, factor in zip(result[column], factors, strict=True)
        ]
    return result
