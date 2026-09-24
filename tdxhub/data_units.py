"""Units confirmed for derived stock/fund statistics (not all TDX products)."""

from tdxhub.exceptions import TdxhubValidationException
from tdxhub.tdx.codec import get_security_type


def trade_volume_multiplier(market, code):
    try:
        security_type = get_security_type(market, code)
    except NotImplementedError:
        security_type = "unknown"
    if security_type in {"SH_A_STOCK", "SZ_A_STOCK", "BJ_A_STOCK", "SH_FUND", "SZ_FUND"}:
        return 100
    raise TdxhubValidationException(f"{code} 的成交量单位/币种尚未校准，不支持资金流或竞价金额估算")
