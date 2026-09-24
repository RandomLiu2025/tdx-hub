"""Public data semantics; raw protocol records remain available on the client."""

import math

from tdxhub.tdx.codec import get_security_type


def normalize_index_quotes(rows):
    if rows is None:
        return None
    result = []
    for source in rows:
        row = dict(source)
        try:
            kind = get_security_type(row.get("market"), row.get("code"))
        except NotImplementedError:
            kind = "unknown"
        if kind.endswith("_INDEX"):
            # Confirmed against index_bars on SH/SZ. BJ mapping is unverified.
            row["up_count"] = row.get("bid_vol1") if kind != "BJ_INDEX" else None
            row["down_count"] = row.get("ask_vol1") if kind != "BJ_INDEX" else None
            for level in range(1, 6):
                for field in (f"bid{level}", f"ask{level}", f"bid_vol{level}", f"ask_vol{level}"):
                    if field in row:
                        row[field] = None
        result.append(row)
    return result


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def finance_quality(row):
    """Diagnose normalized records, while retaining explicit legacy diagnostics.

    Equity definitions can differ (e.g. banks). A ratio is not a scaling fix.
    """
    normalized = row.get("finance_schema") == "tdx_finance_v2"
    issues = []
    warnings = []
    share_fields = (
        ("liutongguben", "bgu", "hgu")
        if normalized
        else ("liutongguben", "guojiagu", "faqirenfarengu", "farengu", "bgu", "hgu", "zhigonggu")
    )
    total = _positive(row.get("zongguben"))
    if total and any((_positive(row.get(field)) or 0) > total * 1.001 for field in share_fields):
        issues.append("share_components_exceed_total")
    net = _positive(row.get("jingzichan"))
    per_share = _positive(row.get("meigujingzichan"))
    ratio = net / total / per_share if net and total and per_share else None
    if ratio is not None and not math.isfinite(ratio):
        ratio = None
    if ratio is not None and not math.isclose(ratio, 1, rel_tol=0.05):
        if normalized:
            warnings.append("net_assets_per_share_basis_difference")
        else:
            issues.append("net_assets_per_share_mismatch")
    if normalized:
        return {
            "status": "inconsistent" if issues else "normalized",
            "issues": issues,
            "warnings": warnings,
            "unverified_fields": ["guojiagu", "baoliu2"],
            "net_assets_per_share_ratio": ratio,
            "note": "已按财务摘要字段表换算为元/股；原始槽位保存在 raw_fields，未知槽位未定性；"
            "每股净资产可能与归母权益口径不同，不能据此自动校准；normalized 不是审计认证",
        }
    return {
        "status": "legacy_unverified",
        "issues": issues,
        "net_assets_per_share_ratio": ratio,
        "note": "旧财务字段映射/单位未全面校准；原值保留，勿据此自动调整倍率或作投资估值",
    }
