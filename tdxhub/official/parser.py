"""Parsers for text files distributed with the TongDaXin client."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from pathlib import Path
from typing import TypeAlias

import pandas as pd

OfficialSource: TypeAlias = bytes | str | Path

_MARKETS = {"0": "sz", "1": "sh", "2": "bj", "sz": "sz", "sh": "sh", "bj": "bj"}


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")


def _load(source: OfficialSource, default_source: str) -> tuple[str, str]:
    source_name = default_source
    if isinstance(source, Path):
        source_name = source.name
        data: bytes | str = source.read_bytes()
    elif isinstance(source, bytes):
        data = source
    elif isinstance(source, str):
        path = Path(source).expanduser()
        try:
            is_file = "\n" not in source and "\r" not in source and path.is_file()
        except OSError:
            is_file = False
        if is_file:
            source_name = path.name
            data = path.read_bytes()
        else:
            data = source
    else:
        raise TypeError("source 必须是 bytes、str 或 Path")

    text = _decode(data) if isinstance(data, bytes) else data
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff"), source_name


def _frame(records: list[dict], columns: list[str], source: str) -> pd.DataFrame:
    result = pd.DataFrame.from_records(records, columns=columns)
    result.attrs["source"] = source
    return result


def _fields(line: str) -> list[str]:
    return [field.strip() for field in line.split("|")]


def _number(value: str) -> int:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return 0


def _optional_float(value: str, *, multiplier: float = 1.0) -> float:
    """Preserve unknown report values as NaN, not a fabricated zero."""
    try:
        number = float(value.strip()) * multiplier
    except (TypeError, ValueError):
        return float("nan")
    return number if isfinite(number) else float("nan")


def _optional_number(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _field(fields: list[str], index: int) -> str:
    return fields[index] if index < len(fields) else ""


def _market(value: str) -> str | None:
    return _MARKETS.get(value.strip().lower())


def parse_spblock(source: OfficialSource, *, source_name: str = "spblock.dat") -> pd.DataFrame:
    """Parse unlimited-size professional block membership from ``spblock.dat``."""
    text, resolved_source = _load(source, source_name)
    current_block: str | None = None
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line:
            continue
        if line.startswith("#"):
            current_block = line[1:].strip()
            continue
        if current_block is None or len(line) != 7 or not line.isascii() or not line.isdigit():
            continue
        records.append(
            {
                "block_name": current_block,
                "market": _market(line[0]),
                "code": line[1:],
                "raw_code": line,
                "source": resolved_source,
            }
        )

    return _frame(records, ["block_name", "market", "code", "raw_code", "source"], resolved_source)


def parse_tdxzs(source: OfficialSource, *, source_name: str = "tdxzs.cfg") -> pd.DataFrame:
    """Parse block-index definitions from the ``tdxzs*.cfg`` family."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 2 or not fields[0] or not fields[1]:
            continue
        records.append(
            {
                "name": fields[0],
                "code": fields[1],
                "type": _number(fields[2]) if len(fields) >= 3 else 0,
                "sub_type": _number(fields[3]) if len(fields) >= 4 else 0,
                "ref": fields[5] if len(fields) >= 6 else "",
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    columns = ["name", "code", "type", "sub_type", "ref", "source", "raw_fields"]
    return _frame(records, columns, resolved_source)


def parse_tdxbk(source: OfficialSource, *, source_name: str = "tdxbk.cfg") -> pd.DataFrame:
    """Parse short-to-full concept block name mappings from ``tdxbk.cfg``."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 3 or not fields[1] or not fields[2]:
            continue
        records.append(
            {
                "short_name": fields[1],
                "full_name": fields[2],
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    return _frame(records, ["short_name", "full_name", "source", "raw_fields"], resolved_source)


def parse_tdxhy(source: OfficialSource, *, source_name: str = "tdxhy.cfg") -> pd.DataFrame:
    """Parse per-security TongDaXin and Shenwan industry assignments."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 3 or not fields[0] or not fields[1]:
            continue
        records.append(
            {
                "market": _market(fields[0]),
                "code": fields[1],
                "tdx_industry_code": fields[2],
                "sw_industry_code": fields[5] if len(fields) >= 6 else fields[-1],
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    columns = ["market", "code", "tdx_industry_code", "sw_industry_code", "source", "raw_fields"]
    return _frame(records, columns, resolved_source)


def parse_tdxbjmore(source: OfficialSource, *, source_name: str = "tdxbjmore.cfg") -> pd.DataFrame:
    """Parse the Beijing Stock Exchange directory from ``tdxbjmore.cfg``."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 4 or not fields[1] or not fields[3]:
            continue
        records.append(
            {
                "market": "bj",
                "code": fields[1],
                "name": fields[3],
                "security_type": "stock",
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    columns = ["market", "code", "name", "security_type", "source", "raw_fields"]
    return _frame(records, columns, resolved_source)


def parse_incon(source: OfficialSource, *, source_name: str = "incon.dat") -> pd.DataFrame:
    """Parse sectioned industry-code definitions from ``incon.dat``."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for section in text.split("######"):
        lines = [line.strip().strip("\x00") for line in section.splitlines() if line.strip().strip("\x00")]
        if len(lines) < 2:
            continue
        section_source = lines[0].removeprefix("#").strip()
        if not section_source:
            continue
        for line in lines[1:]:
            if line.startswith("#"):
                continue
            fields = _fields(line)
            if len(fields) < 2 or not fields[0] or not fields[1]:
                continue
            records.append(
                {
                    "source": section_source,
                    "code": fields[0],
                    "name": fields[1],
                    "raw_fields": fields,
                }
            )

    return _frame(records, ["source", "code", "name", "raw_fields"], resolved_source)


def associate_industries(assignments: pd.DataFrame, dictionary: pd.DataFrame) -> pd.DataFrame:
    """Resolve industry assignments and expand Shenwan hierarchy fields.

    Full codes are matched first. For legacy Shenwan assignments only, an ``X``
    prefix may be removed and looked up within the ``SWHY`` section. Hierarchy
    names are resolved only within the section that matched the assignment.
    Unknown codes remain in the result and are reported through DataFrame
    attributes.
    """
    required_assignments = {"tdx_industry_code", "sw_industry_code"}
    required_dictionary = {"source", "code", "name"}
    missing_assignments = sorted(required_assignments.difference(assignments.columns))
    missing_dictionary = sorted(required_dictionary.difference(dictionary.columns))
    if missing_assignments:
        raise ValueError(f"assignments 缺少列: {', '.join(missing_assignments)}")
    if missing_dictionary:
        raise ValueError(f"dictionary 缺少列: {', '.join(missing_dictionary)}")

    exact: dict[str, tuple[str, str, str]] = {}
    shenwan: dict[str, tuple[str, str, str]] = {}
    section_names: dict[tuple[str, str], str] = {}
    for source_value, code_value, name_value in dictionary[["source", "code", "name"]].itertuples(
        index=False, name=None
    ):
        if pd.isna(source_value) or pd.isna(code_value) or pd.isna(name_value):
            continue
        source_text = str(source_value).strip()
        code_text = str(code_value).strip()
        name_text = str(name_value).strip()
        if not source_text or not code_text or not name_text:
            continue
        match = (name_text, source_text, code_text)
        exact.setdefault(code_text, match)
        section_names.setdefault((source_text, code_text), name_text)
        if source_text == "SWHY":
            shenwan.setdefault(code_text, match)

    def resolve(
        code_value: object,
        *,
        allow_shenwan_fallback: bool = False,
    ) -> tuple[str | None, str | None, str | None]:
        if pd.isna(code_value):
            return None, None, None
        code_text = str(code_value).strip()
        if not code_text:
            return None, None, None
        match = exact.get(code_text)
        if match is None and allow_shenwan_fallback and code_text.startswith("X"):
            match = shenwan.get(code_text[1:])
        return match if match is not None else (None, None, None)

    def shenwan_level_codes(
        match: tuple[str | None, str | None, str | None],
    ) -> tuple[str | None, str | None, str | None]:
        _, source_text, code_text = match
        if source_text == "TDXRSHY" and code_text is not None:
            digits = code_text[1:] if code_text.startswith("X") else ""
            if digits.isdigit() and len(digits) in {2, 4, 6}:
                return (
                    f"X{digits[:2]}",
                    f"X{digits[:4]}" if len(digits) >= 4 else None,
                    f"X{digits[:6]}" if len(digits) == 6 else None,
                )
        if (
            source_text == "SWHY"
            and code_text is not None
            and code_text.isdigit()
            and len(code_text) == 6
        ):
            return (
                f"{code_text[:2]}0000",
                f"{code_text[:4]}00" if code_text[2:] != "0000" else None,
                code_text if code_text[-2:] != "00" else None,
            )
        return None, None, None

    def shenwan_levels(
        match: tuple[str | None, str | None, str | None],
    ) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
        _, source_text, _ = match
        codes = shenwan_level_codes(match)
        level_values: list[str | None] = []
        for code_text in codes:
            level_values.append(code_text)
            level_values.append(
                section_names.get((source_text, code_text))
                if source_text is not None and code_text is not None
                else None
            )
        return (
            level_values[0],
            level_values[1],
            level_values[2],
            level_values[3],
            level_values[4],
            level_values[5],
        )

    result = assignments.copy(deep=True)
    tdx_matches = [resolve(code) for code in result["tdx_industry_code"]]
    sw_matches = [resolve(code, allow_shenwan_fallback=True) for code in result["sw_industry_code"]]
    sw_levels = [shenwan_levels(match) for match in sw_matches]

    def values(matches: list[tuple], index: int) -> pd.Series:
        return pd.Series([match[index] for match in matches], index=result.index, dtype=object)

    tdx_position = result.columns.get_loc("tdx_industry_code") + 1
    result.insert(tdx_position, "tdx_industry_name", values(tdx_matches, 0))
    result.insert(tdx_position + 1, "tdx_industry_source", values(tdx_matches, 1))
    sw_position = result.columns.get_loc("sw_industry_code") + 1
    result.insert(sw_position, "sw_industry_name", values(sw_matches, 0))
    result.insert(sw_position + 1, "sw_industry_source", values(sw_matches, 1))
    for offset, column in enumerate(
        (
            "sw_level1_code",
            "sw_level1_name",
            "sw_level2_code",
            "sw_level2_name",
            "sw_level3_code",
            "sw_level3_name",
        ),
        start=2,
    ):
        result.insert(sw_position + offset, column, values(sw_levels, offset - 2))

    unresolved: set[str] = set()
    for code_value, match in zip(result["tdx_industry_code"], tdx_matches, strict=True):
        if match[0] is None and not pd.isna(code_value) and str(code_value).strip():
            unresolved.add(str(code_value).strip())
    for code_value, match in zip(result["sw_industry_code"], sw_matches, strict=True):
        if match[0] is None and not pd.isna(code_value) and str(code_value).strip():
            unresolved.add(str(code_value).strip())

    result.attrs["industry_dictionary_source"] = dictionary.attrs.get("source")
    result.attrs["unresolved_industry_codes"] = sorted(unresolved)
    return result


def parse_hspy(source: OfficialSource, *, source_name: str = "hspy.dat") -> pd.DataFrame:
    """Conservatively parse variable-layout security name/pinyin records."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line) if "|" in line else line.split()
        record = {
            "market": None,
            "code": None,
            "name": None,
            "pinyin": None,
            "source": resolved_source,
            "raw_fields": fields.copy(),
        }
        for index, field in enumerate(fields):
            if len(field) != 6 or not field.isascii() or not field.isdigit():
                continue
            record["code"] = field
            if index > 0:
                record["market"] = _market(fields[index - 1])
            if index + 1 < len(fields):
                record["name"] = fields[index + 1]
            if index + 2 < len(fields):
                record["pinyin"] = fields[index + 2]
            break
        records.append(record)

    columns = ["market", "code", "name", "pinyin", "source", "raw_fields"]
    result = _frame(records, columns, resolved_source)
    for column in ("market", "code", "name", "pinyin"):
        result[column] = pd.Series([record[column] for record in records], dtype=object)
    return result


def parse_tdxstat(source: OfficialSource, *, source_name: str = "tdxstat.cfg") -> pd.DataFrame:
    """Parse verified per-security statistics from ``tdxstat.cfg``."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 5 or not fields[1]:
            continue
        records.append(
            {
                "market": _market(fields[0]),
                "code": fields[1],
                "date": _field(fields, 4),
                "pe_ttm": _optional_float(_field(fields, 3)),
                "trend_days": _optional_number(_field(fields, 5)),
                "change_pct": _optional_float(_field(fields, 6)),
                "pe_static": _optional_float(_field(fields, 9)),
                "dividend_yield": _optional_float(_field(fields, 10)),
                "change_5d": _optional_float(_field(fields, 28)),
                "change_10d": _optional_float(_field(fields, 30)),
                "change_20d": _optional_float(_field(fields, 18)),
                "change_60d": _optional_float(_field(fields, 20)),
                "change_ytd": _optional_float(_field(fields, 21)),
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    columns = [
        "market",
        "code",
        "date",
        "pe_ttm",
        "trend_days",
        "change_pct",
        "pe_static",
        "dividend_yield",
        "change_5d",
        "change_10d",
        "change_20d",
        "change_60d",
        "change_ytd",
        "source",
        "raw_fields",
    ]
    return _frame(records, columns, resolved_source)


def parse_tdxstat2(source: OfficialSource, *, source_name: str = "tdxstat2.cfg") -> pd.DataFrame:
    """Parse ``tdxstat2.cfg``; amounts are yuan, raw_fields retain 10k yuan."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 14 or not fields[1]:
            continue
        records.append(
            {
                "market": _market(fields[0]),
                "code": fields[1],
                "date": _field(fields, 2),
                "block_index": _field(fields, 13),
                "amount": _optional_float(_field(fields, 3), multiplier=10_000),
                "amount_prev": _optional_float(_field(fields, 5), multiplier=10_000),
                "ipo_price": _optional_float(_field(fields, 16)),
                "high_52w": _optional_float(_field(fields, 17)),
                "low_52w": _optional_float(_field(fields, 18)),
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    columns = [
        "market",
        "code",
        "date",
        "block_index",
        "amount",
        "amount_prev",
        "ipo_price",
        "high_52w",
        "low_52w",
        "source",
        "raw_fields",
    ]
    result = _frame(records, columns, resolved_source)
    result.attrs["amount_unit"] = "yuan"
    result.attrs["source_amount_unit"] = "ten_thousand_yuan"
    return result


def parse_xgsg(source: OfficialSource, *, source_name: str = "xgsg.cfg") -> pd.DataFrame:
    """Parse new-share subscriptions from the official ``xgsg.cfg`` file."""
    text, resolved_source = _load(source, source_name)
    records: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        fields = _fields(line)
        if len(fields) < 15 or not fields[1]:
            continue
        records.append(
            {
                "market": _market(fields[0]),
                "code": fields[1],
                "date": _field(fields, 2),
                "issue_price": _optional_float(_field(fields, 3)),
                "name": _field(fields, 14),
                "source": resolved_source,
                "raw_fields": fields,
            }
        )

    columns = ["market", "code", "date", "issue_price", "name", "source", "raw_fields"]
    return _frame(records, columns, resolved_source)


def stock_block_index(statistics: pd.DataFrame) -> dict[str, str]:
    """Build the security-to-block reverse index from parsed ``tdxstat2`` data."""
    if "code" not in statistics or "block_index" not in statistics:
        return {}
    rows = statistics.loc[statistics["block_index"].fillna("") != "", ["code", "block_index"]]
    return dict(rows.itertuples(index=False, name=None))


Parser = Callable[..., pd.DataFrame]
_PARSERS: dict[str, tuple[Parser, str]] = {
    "spblock": (parse_spblock, "spblock.dat"),
    "spblock.dat": (parse_spblock, "spblock.dat"),
    "tdxzs": (parse_tdxzs, "tdxzs.cfg"),
    "tdxzs.cfg": (parse_tdxzs, "tdxzs.cfg"),
    "tdxzs3": (parse_tdxzs, "tdxzs3.cfg"),
    "tdxzs3.cfg": (parse_tdxzs, "tdxzs3.cfg"),
    "tdxdszs": (parse_tdxzs, "tdxdszs.cfg"),
    "tdxdszs.cfg": (parse_tdxzs, "tdxdszs.cfg"),
    "tdxbk": (parse_tdxbk, "tdxbk.cfg"),
    "tdxbk.cfg": (parse_tdxbk, "tdxbk.cfg"),
    "tdxhy": (parse_tdxhy, "tdxhy.cfg"),
    "tdxhy.cfg": (parse_tdxhy, "tdxhy.cfg"),
    "tdxbjmore": (parse_tdxbjmore, "tdxbjmore.cfg"),
    "tdxbjmore.cfg": (parse_tdxbjmore, "tdxbjmore.cfg"),
    "tdxstat": (parse_tdxstat, "tdxstat.cfg"),
    "tdxstat.cfg": (parse_tdxstat, "tdxstat.cfg"),
    "tdxstat2": (parse_tdxstat2, "tdxstat2.cfg"),
    "tdxstat2.cfg": (parse_tdxstat2, "tdxstat2.cfg"),
    "xgsg": (parse_xgsg, "xgsg.cfg"),
    "xgsg.cfg": (parse_xgsg, "xgsg.cfg"),
    "incon": (parse_incon, "incon.dat"),
    "incon.dat": (parse_incon, "incon.dat"),
    "hspy": (parse_hspy, "hspy.dat"),
    "hspy.dat": (parse_hspy, "hspy.dat"),
}


def parse_official(source: OfficialSource, kind: str | None = None) -> pd.DataFrame:
    """Parse a supported official file, inferring its type from a path when possible."""
    if kind is None:
        if isinstance(source, Path):
            kind = source.name
        elif isinstance(source, str) and "\n" not in source and "\r" not in source:
            kind = Path(source).name
        else:
            raise ValueError("bytes 或文本内容必须通过 kind 指定官方文件类型")

    normalized_kind = Path(kind.strip().lower()).name
    parser_entry = _PARSERS.get(normalized_kind)
    if parser_entry is None:
        raise ValueError(f"不支持的官方文件类型: {kind}")
    parser, default_source = parser_entry
    return parser(source, source_name=default_source)
