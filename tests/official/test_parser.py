from pathlib import Path

import pandas as pd
import pytest

from tdxhub.official import (
    associate_industries,
    parse_hspy,
    parse_incon,
    parse_official,
    parse_spblock,
    parse_tdxbjmore,
    parse_tdxbk,
    parse_tdxhy,
    parse_tdxzs,
    parse_xgsg,
)
from tdxhub.reader import Reader


def gbk(value: str) -> bytes:
    return value.encode("gbk")


def test_parse_spblock_decodes_gbk_and_splits_market_code():
    raw = gbk(
        "#中证2000\r\n0000001\r\n1600519\r\n2920001\r\n"
        "123\r\nabcdefg\r\n\r\n#空板块\r\n"
    )

    result = parse_spblock(raw)

    assert result.to_dict("records") == [
        {
            "block_name": "中证2000",
            "market": "sz",
            "code": "000001",
            "raw_code": "0000001",
            "source": "spblock.dat",
        },
        {
            "block_name": "中证2000",
            "market": "sh",
            "code": "600519",
            "raw_code": "1600519",
            "source": "spblock.dat",
        },
        {
            "block_name": "中证2000",
            "market": "bj",
            "code": "920001",
            "raw_code": "2920001",
            "source": "spblock.dat",
        },
    ]


def test_parse_tdxzs_keeps_unknown_fields_and_defaults_invalid_numbers():
    raw = gbk(
        "# comment\r\n轮动趋势|880081|5|2|0|轮动趋势|extra\r\n"
        "黑龙江|880201|bad||0|1\r\nmissing-code|||||\r\n"
    )

    result = parse_tdxzs(raw)

    assert result[["name", "code", "type", "sub_type", "ref"]].to_dict("records") == [
        {"name": "轮动趋势", "code": "880081", "type": 5, "sub_type": 2, "ref": "轮动趋势"},
        {"name": "黑龙江", "code": "880201", "type": 0, "sub_type": 0, "ref": "1"},
    ]
    assert result.iloc[0]["raw_fields"] == ["轮动趋势", "880081", "5", "2", "0", "轮动趋势", "extra"]


def test_parse_tdxbk_filters_malformed_rows():
    result = parse_tdxbk(gbk("1|有机硅|有机硅概念|0\r\n# x\r\n1||bad|0\r\ninvalid\r\n"))

    assert result[["short_name", "full_name"]].to_dict("records") == [
        {"short_name": "有机硅", "full_name": "有机硅概念"}
    ]
    assert result.iloc[0]["raw_fields"] == ["1", "有机硅", "有机硅概念", "0"]


def test_parse_tdxhy_normalizes_market_and_preserves_raw_fields():
    raw = "0|000001|T1001|||X500102\r\n1|600000|T0101|X999\r\n2|920001|T0201|||X600101\r\n"

    result = parse_tdxhy(raw)

    assert result[["market", "code", "tdx_industry_code", "sw_industry_code"]].to_dict("records") == [
        {"market": "sz", "code": "000001", "tdx_industry_code": "T1001", "sw_industry_code": "X500102"},
        {"market": "sh", "code": "600000", "tdx_industry_code": "T0101", "sw_industry_code": "X999"},
        {"market": "bj", "code": "920001", "tdx_industry_code": "T0201", "sw_industry_code": "X600101"},
    ]


def test_parse_tdxbjmore_returns_beijing_stock_directory():
    raw = gbk(
        "44|430047|2|诺思兰德|\r\n"
        "44|430090|2|同辉信息|extra\r\n"
        "44||2|缺少代码|\r\n"
        "invalid\r\n"
    )

    result = parse_tdxbjmore(raw)

    assert result[["market", "code", "name", "security_type", "source"]].to_dict("records") == [
        {
            "market": "bj",
            "code": "430047",
            "name": "诺思兰德",
            "security_type": "stock",
            "source": "tdxbjmore.cfg",
        },
        {
            "market": "bj",
            "code": "430090",
            "name": "同辉信息",
            "security_type": "stock",
            "source": "tdxbjmore.cfg",
        },
    ]
    assert result.iloc[1]["raw_fields"] == ["44", "430090", "2", "同辉信息", "extra"]


def test_parse_xgsg_decodes_gbk_and_preserves_all_fields():
    fields = [""] * 18
    fields[0:7] = ["1", "732001", "20260911", "18.88", "2500", "1000", "44"]
    fields[9] = "0.052"
    fields[11] = "47200"
    fields[14] = "测试新股"
    invalid_price = fields.copy()
    invalid_price[0] = "2"
    invalid_price[1] = "920001"
    invalid_price[3] = "bad"
    invalid_price[14] = "北交新股"
    raw = gbk(
        "# comment\r\n"
        + "|".join(fields)
        + "\r\n"
        + "|".join(invalid_price)
        + "\r\n0||20260911|1.0|too-short\r\n"
    )

    result = parse_xgsg(raw)

    assert result.drop(columns=["raw_fields"]).to_dict("records") == [
        {
            "market": "sh",
            "code": "732001",
            "date": "20260911",
            "issue_price": 18.88,
            "name": "测试新股",
            "source": "xgsg.cfg",
        },
        {
            "market": "bj",
            "code": "920001",
            "date": "20260911",
            "issue_price": 0.0,
            "name": "北交新股",
            "source": "xgsg.cfg",
        },
    ]
    assert result.iloc[0]["raw_fields"] == fields


def test_parse_official_dispatches_xgsg_bytes():
    fields = [""] * 18
    fields[0:4] = ["0", "001234", "20260911", "9.99"]
    fields[14] = "深市新股"

    result = parse_official(gbk("|".join(fields)), kind="xgsg.cfg")

    assert result.iloc[0][["market", "code", "name"]].to_dict() == {
        "market": "sz",
        "code": "001234",
        "name": "深市新股",
    }


def test_parse_incon_tracks_sections_and_extra_fields():
    raw = gbk(
        "TDXHY\r\nT01|银行\r\nT02|煤炭|extra\r\ninvalid\r\n"
        "######\r\nSWHY\r\nX01|申万银行\r\n######\r\n"
    )

    result = parse_incon(raw)

    assert result[["source", "code", "name"]].to_dict("records") == [
        {"source": "TDXHY", "code": "T01", "name": "银行"},
        {"source": "TDXHY", "code": "T02", "name": "煤炭"},
        {"source": "SWHY", "code": "X01", "name": "申万银行"},
    ]
    assert result.iloc[1]["raw_fields"] == ["T02", "煤炭", "extra"]


def test_parse_incon_accepts_real_hash_prefixed_section_headers():
    result = parse_incon(gbk("#TDXNHY\r\nT10|金融\r\nT1001|银行\r\n######\r\n#TDXRSHY\r\nX500102|股份制银行\r\n"))

    assert result[["source", "code", "name"]].to_dict("records") == [
        {"source": "TDXNHY", "code": "T10", "name": "金融"},
        {"source": "TDXNHY", "code": "T1001", "name": "银行"},
        {"source": "TDXRSHY", "code": "X500102", "name": "股份制银行"},
    ]


def test_associate_industries_resolves_names_without_mutating_inputs():
    assignments = parse_tdxhy(
        "0|000001|T1001|||X500102\n"
        "1|600000|T9999|||X999999\n"
        "2|920001||||X110101\n"
    )
    dictionary = parse_incon(
        gbk(
            "#TDXNHY\nT10|金融\nT1001|银行\n"
            "######\n#TDXRSHY\nX500102|股份制银行\n"
            "######\n#SWHY\n110101|种子生产\n"
        )
    )
    assignments_before = assignments.copy(deep=True)
    dictionary_before = dictionary.copy(deep=True)

    result = associate_industries(assignments, dictionary)

    assert result[
        [
            "market",
            "code",
            "tdx_industry_code",
            "tdx_industry_name",
            "tdx_industry_source",
            "sw_industry_code",
            "sw_industry_name",
            "sw_industry_source",
        ]
    ].to_dict("records") == [
        {
            "market": "sz",
            "code": "000001",
            "tdx_industry_code": "T1001",
            "tdx_industry_name": "银行",
            "tdx_industry_source": "TDXNHY",
            "sw_industry_code": "X500102",
            "sw_industry_name": "股份制银行",
            "sw_industry_source": "TDXRSHY",
        },
        {
            "market": "sh",
            "code": "600000",
            "tdx_industry_code": "T9999",
            "tdx_industry_name": None,
            "tdx_industry_source": None,
            "sw_industry_code": "X999999",
            "sw_industry_name": None,
            "sw_industry_source": None,
        },
        {
            "market": "bj",
            "code": "920001",
            "tdx_industry_code": "",
            "tdx_industry_name": None,
            "tdx_industry_source": None,
            "sw_industry_code": "X110101",
            "sw_industry_name": "种子生产",
            "sw_industry_source": "SWHY",
        },
    ]
    assert result.attrs["industry_dictionary_source"] == "incon.dat"
    assert result.attrs["unresolved_industry_codes"] == ["T9999", "X999999"]
    pd.testing.assert_frame_equal(assignments, assignments_before)
    pd.testing.assert_frame_equal(dictionary, dictionary_before)


def test_associate_industries_expands_shenwan_levels_for_both_code_systems():
    assignments = parse_tdxhy(
        "0|000001|T1001|||X21\n"
        "0|000002|T1001|||X2102\n"
        "0|000003|T1001|||X210205\n"
        "1|600000|T1001|||X110000\n"
        "1|600001|T1001|||X110100\n"
        "1|600002|T1001|||X110101\n"
    )
    dictionary = parse_incon(
        gbk(
            "#TDXRSHY\n"
            "X21|采掘\n"
            "X2102|煤炭开采\n"
            "X210205|焦煤\n"
            "######\n"
            "#SWHY\n"
            "110000|农林牧渔\n"
            "110100|种植业\n"
            "110101|种子生产\n"
        )
    )

    result = associate_industries(assignments, dictionary)

    assert result[
        [
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
    ].to_dict("records") == [
        {
            "sw_industry_code": "X21",
            "sw_industry_name": "采掘",
            "sw_industry_source": "TDXRSHY",
            "sw_level1_code": "X21",
            "sw_level1_name": "采掘",
            "sw_level2_code": None,
            "sw_level2_name": None,
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
        {
            "sw_industry_code": "X2102",
            "sw_industry_name": "煤炭开采",
            "sw_industry_source": "TDXRSHY",
            "sw_level1_code": "X21",
            "sw_level1_name": "采掘",
            "sw_level2_code": "X2102",
            "sw_level2_name": "煤炭开采",
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
        {
            "sw_industry_code": "X210205",
            "sw_industry_name": "焦煤",
            "sw_industry_source": "TDXRSHY",
            "sw_level1_code": "X21",
            "sw_level1_name": "采掘",
            "sw_level2_code": "X2102",
            "sw_level2_name": "煤炭开采",
            "sw_level3_code": "X210205",
            "sw_level3_name": "焦煤",
        },
        {
            "sw_industry_code": "X110000",
            "sw_industry_name": "农林牧渔",
            "sw_industry_source": "SWHY",
            "sw_level1_code": "110000",
            "sw_level1_name": "农林牧渔",
            "sw_level2_code": None,
            "sw_level2_name": None,
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
        {
            "sw_industry_code": "X110100",
            "sw_industry_name": "种植业",
            "sw_industry_source": "SWHY",
            "sw_level1_code": "110000",
            "sw_level1_name": "农林牧渔",
            "sw_level2_code": "110100",
            "sw_level2_name": "种植业",
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
        {
            "sw_industry_code": "X110101",
            "sw_industry_name": "种子生产",
            "sw_industry_source": "SWHY",
            "sw_level1_code": "110000",
            "sw_level1_name": "农林牧渔",
            "sw_level2_code": "110100",
            "sw_level2_name": "种植业",
            "sw_level3_code": "110101",
            "sw_level3_name": "种子生产",
        },
    ]


def test_associate_industries_handles_partial_levels_and_missing_parents():
    assignments = parse_tdxhy(
        "0|000001|T1001|||X21\n"
        "1|600000|T1001|||X2102\n"
        "1|600519|T1001|||X330101\n"
        "0|000002|T1001|||X999999\n"
    )
    dictionary = parse_incon(
        gbk(
            "#TDXRSHY\n"
            "X21|采掘\n"
            "X2102|煤炭开采\n"
            "X330101|三级行业\n"
        )
    )

    result = associate_industries(assignments, dictionary)
    levels = result[
        [
            "sw_level1_code",
            "sw_level1_name",
            "sw_level2_code",
            "sw_level2_name",
            "sw_level3_code",
            "sw_level3_name",
        ]
    ].to_dict("records")

    assert levels == [
        {
            "sw_level1_code": "X21",
            "sw_level1_name": "采掘",
            "sw_level2_code": None,
            "sw_level2_name": None,
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
        {
            "sw_level1_code": "X21",
            "sw_level1_name": "采掘",
            "sw_level2_code": "X2102",
            "sw_level2_name": "煤炭开采",
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
        {
            "sw_level1_code": "X33",
            "sw_level1_name": None,
            "sw_level2_code": "X3301",
            "sw_level2_name": None,
            "sw_level3_code": "X330101",
            "sw_level3_name": "三级行业",
        },
        {
            "sw_level1_code": None,
            "sw_level1_name": None,
            "sw_level2_code": None,
            "sw_level2_name": None,
            "sw_level3_code": None,
            "sw_level3_name": None,
        },
    ]


def test_associate_industries_validates_required_columns():
    with pytest.raises(ValueError, match="assignments 缺少列: sw_industry_code"):
        associate_industries(
            pd.DataFrame({"tdx_industry_code": ["T1001"]}),
            pd.DataFrame({"source": ["TDXNHY"], "code": ["T1001"], "name": ["银行"]}),
        )


def test_parse_hspy_is_conservative_and_keeps_unrecognized_rows():
    raw = gbk("# comment\r\n1|600000|浦发银行|PFYH\r\n000001|平安银行|PAYH\r\nraw only\r\n")

    result = parse_hspy(raw)

    assert result[["market", "code", "name", "pinyin"]].to_dict("records") == [
        {"market": "sh", "code": "600000", "name": "浦发银行", "pinyin": "PFYH"},
        {"market": None, "code": "000001", "name": "平安银行", "pinyin": "PAYH"},
        {"market": None, "code": None, "name": None, "pinyin": None},
    ]
    assert result.iloc[2]["raw_fields"] == ["raw", "only"]


@pytest.mark.parametrize(
    ("filename", "expected_columns"),
    [
        ("spblock.dat", {"block_name", "market", "code", "raw_code", "source"}),
        ("tdxzs.cfg", {"name", "code", "type", "sub_type", "ref", "source", "raw_fields"}),
        ("tdxbk.cfg", {"short_name", "full_name", "source", "raw_fields"}),
        ("tdxhy.cfg", {"market", "code", "tdx_industry_code", "sw_industry_code", "source", "raw_fields"}),
        ("tdxbjmore.cfg", {"market", "code", "name", "security_type", "source", "raw_fields"}),
        ("hspy.dat", {"market", "code", "name", "pinyin", "source", "raw_fields"}),
    ],
)
def test_parse_official_dispatches_real_fixtures(filename, expected_columns):
    path = Path("tests/fixtures/T0002/hq_cache") / filename

    result = parse_official(path)

    assert isinstance(result, pd.DataFrame)
    assert not result.empty
    assert set(result.columns) == expected_columns
    assert result.attrs["source"] == filename


def test_parse_official_supports_incon_path_and_kind_for_bytes():
    from_path = parse_official(Path("tests/fixtures/incon.dat"))
    from_bytes = parse_official(gbk("1|600000|浦发银行|PFYH\n"), kind="hspy")

    assert not from_path.empty
    assert from_path.attrs["source"] == "incon.dat"
    assert from_bytes.iloc[0]["code"] == "600000"


def test_parse_official_rejects_unknown_kind():
    with pytest.raises(ValueError, match="不支持的官方文件类型"):
        parse_official(b"data", kind="unknown")


def test_std_reader_exposes_official_parser_without_changing_block_api():
    reader = Reader.factory(market="std", tdxdir="tests/fixtures")

    result = reader.official("spblock.dat")

    assert not result.empty
    assert result.attrs["source"] == "spblock.dat"


def test_std_reader_associates_local_industry_dictionary():
    reader = Reader.factory(market="std", tdxdir="tests/fixtures")

    result = reader.stock_industries()

    first = result.loc[(result["market"] == "sz") & (result["code"] == "000001")].iloc[0]
    assert first["tdx_industry_name"] == "银行"
    assert first["tdx_industry_source"] == "TDXNHY"
    assert first["sw_industry_name"] == "股份制银行"
    assert first["sw_industry_source"] == "TDXRSHY"
    assert first[
        [
            "sw_level1_code",
            "sw_level1_name",
            "sw_level2_code",
            "sw_level2_name",
            "sw_level3_code",
            "sw_level3_name",
        ]
    ].to_dict() == {
        "sw_level1_code": "X50",
        "sw_level1_name": "银行",
        "sw_level2_code": "X5001",
        "sw_level2_name": "全国性银行",
        "sw_level3_code": "X500102",
        "sw_level3_name": "股份制银行",
    }


def test_parse_tdxstat_maps_verified_fields_and_preserves_all_fields():
    from tdxhub.official import parse_tdxstat

    fields = [""] * 35
    values = {
        0: "1",
        1: "600519",
        3: "28.51",
        4: "20260910",
        5: "-2",
        6: "-1.25",
        9: "24.12",
        10: "2.34",
        18: "6.7",
        20: "8.9",
        21: "10.1",
        28: "1.2",
        30: "3.4",
    }
    for index, value in values.items():
        fields[index] = value

    result = parse_tdxstat(gbk("|".join(fields) + "\r\n# comment\r\ninvalid\r\n"))

    assert result.drop(columns=["raw_fields"]).to_dict("records") == [
        {
            "market": "sh",
            "code": "600519",
            "date": "20260910",
            "pe_ttm": 28.51,
            "trend_days": -2,
            "change_pct": -1.25,
            "pe_static": 24.12,
            "dividend_yield": 2.34,
            "change_5d": 1.2,
            "change_10d": 3.4,
            "change_20d": 6.7,
            "change_60d": 8.9,
            "change_ytd": 10.1,
            "source": "tdxstat.cfg",
        }
    ]
    assert result.iloc[0]["raw_fields"] == fields


def test_parse_tdxstat2_and_stock_block_index_handle_missing_numbers():
    from tdxhub.official import parse_tdxstat2, stock_block_index

    fields = [""] * 21
    values = {
        0: "0",
        1: "000001",
        2: "20260910",
        3: "12345.67",
        5: "11000",
        13: "880301",
        16: "1.50",
        17: "15.20",
        18: "bad",
    }
    for index, value in values.items():
        fields[index] = value
    no_block = fields.copy()
    no_block[1] = "000002"
    no_block[13] = ""

    result = parse_tdxstat2("|".join(fields) + "\n" + "|".join(no_block))

    assert result.iloc[0].drop(labels="raw_fields").to_dict() == {
        "market": "sz",
        "code": "000001",
        "date": "20260910",
        "block_index": "880301",
        "amount": 12345.67,
        "amount_prev": 11000.0,
        "ipo_price": 1.5,
        "high_52w": 15.2,
        "low_52w": 0.0,
        "source": "tdxstat2.cfg",
    }
    assert stock_block_index(result) == {"000001": "880301"}
