"""Shared decoding and duplicate-record checks for TDX professional financial data."""

import math
import warnings
from struct import Struct

_HEADER = Struct("<hIH3L")
_INDEX = Struct("<6scL")


class FinancialDataWarning(UserWarning):
    """The source archive contains identical duplicate financial records."""


def unique_financial_records(records):
    """Keep the first identical (code, report_date) record; never discard conflicts."""
    seen = {}
    result = []
    duplicates = 0
    for record in records:
        record = tuple(record)
        key = record[:2]
        previous = seen.get(key)
        if previous is None:
            seen[key] = record
            result.append(record)
            continue

        # Treat missing float values in the same positions as equal, without
        # rounding or tolerances that could conceal genuinely conflicting data.
        if len(previous) != len(record) or not all(
            left == right
            or (isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right))
            for left, right in zip(previous[2:], record[2:], strict=True)
        ):
            raise ValueError(f"{key[0]} 在报告期 {key[1]} 存在冲突财务记录")
        duplicates += 1

    if duplicates:
        warnings.warn(
            f"财务数据中发现 {duplicates} 条完全重复记录，已按 (code, report_date) 去重并保留首次记录",
            FinancialDataWarning,
            stacklevel=2,
        )
    return result


def parse_financial_dat(payload):
    """Decode all header-declared float32 fields, validating lengths and offsets."""
    if len(payload) < _HEADER.size:
        raise ValueError("财务数据文件头不完整")
    _, report_date, count, _, report_size, _ = _HEADER.unpack_from(payload)
    if report_size % 4 or (count and not report_size):
        raise ValueError(f"财务记录长度必须是正的 4 字节倍数: {report_size}")

    index_end = _HEADER.size + count * _INDEX.size
    if len(payload) < index_end:
        raise ValueError("财务证券索引不完整")
    record_struct = None
    records = []
    for index in range(count):
        raw_code, _, offset = _INDEX.unpack_from(payload, _HEADER.size + index * _INDEX.size)
        code = raw_code.decode("ascii").rstrip("\x00")
        if offset < index_end:
            raise ValueError(f"{code} 的财务记录偏移无效: {offset}")
        if offset + report_size > len(payload):
            raise ValueError(f"{code} 的财务记录不完整")
        # Do not allocate a potentially enormous Struct until the untrusted
        # header's declared record size has been checked against the payload.
        if record_struct is None:
            record_struct = Struct(f"<{report_size // 4}f")
        records.append((code, report_date, *record_struct.unpack_from(payload, offset)))

    return unique_financial_records(records)
