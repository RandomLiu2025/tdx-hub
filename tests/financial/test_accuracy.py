"""Offline financial field, serialization and duplicate-source regressions."""

import io
import json
import struct
import warnings
import zipfile

import pytest

from tdxhub.affair import Affair
from tdxhub.financial import financial
from tdxhub.financial.columns import columns
from tdxhub.financial.financial import Financial
from tdxhub.tdx.crawler.history_financial_crawler import HistoryFinancialCrawler
from tdxhub.tdx.financial_data import FinancialDataWarning
from tdxhub.utils import gpcw

REPORT_DATE = 20260630
HEADER = struct.Struct("<hIH3L")
INDEX = struct.Struct("<6scL")


def make_dat(rows, field_count):
    header = HEADER.pack(1, REPORT_DATE, len(rows), 0, field_count * 4, 0)
    offset = len(header) + INDEX.size * len(rows)
    indices = []
    records = []
    for code, values in rows:
        indices.append(INDEX.pack(code.encode("ascii"), b"\0", offset))
        record = struct.pack(f"<{field_count}f", *values)
        records.append(record)
        offset += len(record)
    return header + b"".join(indices) + b"".join(records)


@pytest.fixture(params=["financial", "crawler", "gpcw"])
def read_dat(request, tmp_path):
    """Normalize only the legacy return shape, not any financial values."""
    def read(payload):
        if request.param == "financial":
            stream = io.BytesIO(payload)
            stream.name = "report.dat"
            # Parsing local data must not depend on server configuration.
            result = object.__new__(Financial).parse(stream)
            assert stream.closed
            return result
        if request.param == "crawler":
            with io.BytesIO(payload) as stream:
                result = HistoryFinancialCrawler().parse(stream)
                assert not stream.closed
                return result
        path = tmp_path / "report.dat"
        path.write_bytes(payload)
        return [(code, REPORT_DATE, *values) for code, values in gpcw(path)]

    return read


@pytest.mark.parametrize("field_count", [1, 264, 584, 600])
def test_all_readers_keep_every_header_declared_field(read_dat, field_count):
    values = tuple(float(i) for i in range(1, field_count + 1))
    negative = tuple(-value for value in values)
    payload = make_dat([("600519", values), ("000001", negative)], field_count)
    assert read_dat(payload) == [("600519", REPORT_DATE, *values), ("000001", REPORT_DATE, *negative)]


def test_other_equity_holder_profit_is_not_folded_into_minorities(read_dat):
    # 600188 2026H1 consolidated statement, RMB thousands. See the sourced
    # comparison in docs/local/financial-verification.md. The fourth component
    # is legitimate; 95 = 96 + 97 must not become a universal repair/reject rule.
    profit, parent_profit, minority_profit = (9898971, 7149644, 2425726)
    other_equity_profit = 323601 * 1000
    assert profit * 1000 == (parent_profit + minority_profit) * 1000 + other_equity_profit
    values = [0.0] * 584
    values[94:97] = [value * 1000 for value in (profit, parent_profit, minority_profit)]
    records = read_dat(make_dat([("600188", values)], 584))
    assert len(records) == 1
    # Tuple begins with code and report_date; FINVALUE95 is at index 96.
    actual = records[0][96:99]
    assert actual == (9898971136.0, 7149643776.0, 2425725952.0)
    assert actual[0] - actual[1] - actual[2] == 323601408.0


def test_identical_source_duplicates_are_removed_with_one_warning(read_dat):
    payload = make_dat([("600600", (1.0,)), ("301192", (2.0,)), ("600600", (1.0,))] * 2, 1)
    with pytest.warns(FinancialDataWarning, match="4 条完全重复记录") as caught:
        records = read_dat(payload)
    assert len(caught) == 1
    assert records == [("600600", REPORT_DATE, 1.0), ("301192", REPORT_DATE, 2.0)]


def test_conflicting_source_duplicates_raise_without_silently_picking_one(read_dat):
    values = [0.0] * 584
    conflict = [*values[:-1], 1.0]
    payload = make_dat([("600600", values), ("600600", values), ("600600", conflict)], 584)
    with pytest.raises(ValueError, match="600600.*20260630.*冲突"):
        read_dat(payload)


@pytest.mark.parametrize("field_count", [0, 264, 584])
def test_empty_archive(read_dat, field_count):
    assert read_dat(make_dat([], field_count)) == []


@pytest.mark.parametrize(
    "corruption,match",
    [
        ("header", "文件头不完整"),
        ("index", "索引不完整"),
        ("record", "600519.*记录不完整"),
        ("zero_size", "4 字节倍数"),
        ("unaligned_size", "4 字节倍数"),
        ("oversized_record", "600519.*记录不完整"),
        ("offset_header", "600519.*偏移无效"),
        ("offset_index", "600519.*偏移无效"),
        ("offset_past_end", "600519.*记录不完整"),
    ],
)
def test_malformed_archives_fail_explicitly(read_dat, corruption, match):
    payload = make_dat([("600519", (1.0,))], 1)
    if corruption == "header":
        payload = payload[:HEADER.size - 1]
    elif corruption == "index":
        payload = payload[:HEADER.size + INDEX.size - 1]
    elif corruption == "record":
        payload = payload[:-1]
    elif corruption in ("zero_size", "unaligned_size", "oversized_record"):
        size = {"zero_size": 0, "unaligned_size": 5, "oversized_record": 0xFFFFFFFC}[corruption]
        payload = HEADER.pack(1, REPORT_DATE, 1, 0, size, 0) + payload[HEADER.size:]
    else:
        offset = {"offset_header": 0, "offset_index": HEADER.size, "offset_past_end": len(payload) + 10}[corruption]
        payload = payload[:HEADER.size] + INDEX.pack(b"600519", b"\0", offset) + payload[HEADER.size + INDEX.size:]
    with pytest.raises(ValueError, match=match):
        read_dat(payload)


def test_index_offsets_can_reference_the_same_record(read_dat):
    payload = make_dat([("600519", (1.0,))] * 2, 1)
    start = HEADER.size + INDEX.size
    payload = payload[:start] + INDEX.pack(b"600519", b"\0", start + INDEX.size) + payload[start + INDEX.size:]
    with pytest.warns(FinancialDataWarning):
        assert read_dat(payload) == [("600519", REPORT_DATE, 1.0)]


@pytest.mark.parametrize("width", [1, 196, 237, 264, 580, 584, 600])
@pytest.mark.parametrize("header", ["zh", "en"])
def test_dataframe_columns_are_unique_and_serialization_keeps_all_values(width, header):
    values = tuple(float(i) for i in range(1, width + 1))
    df = Financial.to_df([("600519", REPORT_DATE, *values)], header=header)
    assert df.shape == (1, width + 1)
    assert df.columns.is_unique
    assert df.index.name == "code"
    assert df.index.tolist() == ["600519"]
    assert df.iloc[0].tolist() == [REPORT_DATE, *values]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        record = df.to_dict("records")[0]
    assert len(record) == width + 1
    assert json.loads(df.to_json(orient="records"))[0] == record
    if header == "en":
        assert df.columns.tolist() == ["report_date", *[f"col{i}" for i in range(1, width + 1)]]
    else:
        assert df.columns.tolist() == columns[:width + 1] + [f"col{i}" for i in range(len(columns), width + 1)]


def test_cumulative_and_single_quarter_profit_are_not_overwritten():
    values = [0.0] * 584
    values[95] = 44516880384.0
    values[231] = 17274368000.0
    df = Financial.to_df([("600519", REPORT_DATE, *values)])
    record = df.to_dict("records")[0]
    assert record["归属于母公司所有者的净利润"] == values[95]
    assert record["单季度归属于母公司所有者的净利润"] == values[231]
    assert columns[6] == "净资产收益率"
    assert columns[197] == "净资产收益率(FINVALUE197)"
    assert columns[80] == "财务费用"
    assert columns[142] == "财务费用(现金流量表补充资料)"
    assert columns[200] == "总资产净利率"
    assert columns[517] == "信用减值损失(万元)"
    assert columns[580] == "信用减值损失(万元、FINVALUE580)"
    assert all(label.startswith("单季度") for label in columns[230:238])


def test_future_duplicate_labels_fail_instead_of_losing_data(monkeypatch):
    monkeypatch.setattr(financial, "columns", ["report_date", "重复", "重复"])
    data = [("600519", REPORT_DATE, 1.0, 2.0)]
    with pytest.raises(ValueError, match="中文表头存在重名"):
        Financial.to_df(data)
    assert Financial.to_df(data, header="en").columns.is_unique


@pytest.mark.parametrize("to_df", [Financial.to_df, HistoryFinancialCrawler.to_df])
def test_dataframe_conversion_also_checks_duplicates_but_preserves_different_periods(to_df):
    current = ("600519", REPORT_DATE, 1.0)
    previous = ("600519", 20250630, 2.0)
    with pytest.warns(FinancialDataWarning, match="1 条完全重复记录"):
        df = to_df([current, current, previous])
    assert df.shape == (2, 2)
    assert df["report_date"].tolist() == [REPORT_DATE, 20250630]
    with pytest.raises(ValueError, match="冲突"):
        to_df([current, ("600519", REPORT_DATE, 1.000001)])
    with pytest.raises(ValueError, match="冲突"):
        to_df([current, (*current, 2.0)])


def test_identical_missing_values_are_deduplicated(read_dat):
    payload = make_dat([("600519", (float("nan"), 1.0))] * 2, 2)
    with pytest.warns(FinancialDataWarning):
        assert len(read_dat(payload)) == 1
    conflict = make_dat([("600519", (float("nan"),)), ("600519", (0.0,))], 1)
    with pytest.raises(ValueError, match="冲突"):
        read_dat(conflict)


@pytest.mark.parametrize("suffix", [".dat", ".zip"])
def test_affair_local_parse_exposes_safe_labels_and_duplicate_policy(tmp_path, monkeypatch, suffix):
    values = tuple(float(i) for i in range(1, 585))
    payload = make_dat([("600519", values)] * 2, 584)
    path = tmp_path / f"gpcw20260630{suffix}"
    if suffix == ".zip":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("reports.dat/", b"")
            archive.writestr("reports.dat/report.DAT", payload)
    else:
        path.write_bytes(payload)
    monkeypatch.setattr(Financial, "__init__", lambda self: None)
    for header in ("zh", "en"):
        with pytest.warns(FinancialDataWarning):
            df = Affair.parse(downdir=tmp_path, filename=path.name, header=header)
        assert df.shape == (1, 585)
        assert df.index.is_unique
        assert df.columns.is_unique
        assert df.iloc[0].tolist() == [REPORT_DATE, *values]
        assert len(json.loads(df.reset_index().to_json(orient="records"))[0]) == 586
