"""Contracts for the project-owned TDX implementation (no network)."""

import importlib
import importlib.resources
import importlib.util
import struct

import pytest


@pytest.mark.parametrize(
    "module, name",
    [
        ("client", "StandardClient"),
        ("extended", "ExtendedClient"),
        ("errors", "ProtocolError"),
        ("transport", "BaseSocketClient"),
        ("codec", "get_volume"),
        ("files", "TdxDailyBarReader"),
    ],
)
def test_module_entrypoints(module, name):
    assert getattr(importlib.import_module(f"tdxhub.tdx.{module}"), name)


def test_old_vendor_and_patch_layer_are_not_installed():
    assert importlib.util.find_spec("tdxhub._vendor") is None
    assert importlib.util.find_spec("tdxhub.tdxpy_compat") is None


def test_all_standard_client_consumers_share_one_implementation():
    from tdxhub import quotes
    from tdxhub.financial import financial
    from tdxhub.tdx.client import StandardClient

    server = importlib.import_module("tdxhub.server")
    assert quotes.StandardClient is server.StandardClient is financial.StandardClient is StandardClient


@pytest.mark.parametrize(
    "market, code",
    [(1, "520500"), (1, "560010"), (1, "588000"), (1, "589000"), (1, "510300"), (0, "159915"), (0, "180101")],
)
def test_fund_coefficients_are_correct_in_decoder(market, code):
    from tdxhub.tdx.codec import get_security_coefficient

    assert get_security_coefficient(market, code) == 0.001


def test_directory_multi_record_float32():
    from tdxhub.tdx.protocol.std.get_security_list import GetSecurityList

    body = struct.pack("<H", 2)
    for code, price in [(b"588000", 1.659), (b"510300", 4.617)]:
        body += struct.pack("<6sH8s4sBf4s", code, 100, b"ETF", b"\0" * 4, 3, price, b"\0" * 4)
    rows = GetSecurityList(None).parseResponse(body)
    assert [row["pre_close"] for row in rows] == pytest.approx([1.659, 4.617])


def test_daily_reader_compatibility_alias():
    from tdxhub.contrib.compat import TdxhubDailyBarReader
    from tdxhub.tdx.files import TdxDailyBarReader

    assert TdxhubDailyBarReader is TdxDailyBarReader
    reader = TdxDailyBarReader()
    assert reader.get_security_type("bj920001.day") == "BJ_A_STOCK"
    assert reader.get_security_type("sh688001.day") == "SH_STAR_STOCK"


def test_redundant_version_module_removed_and_financial_modules_kept():
    from tdxhub import __version__
    from tdxhub.tdx.crawler.history_financial_crawler import HistoryFinancialCrawler
    from tdxhub.tdx.files import HistoryFinancialReader

    assert importlib.util.find_spec("tdxhub.tdx.version") is None
    assert __version__
    assert HistoryFinancialReader
    assert HistoryFinancialCrawler


def test_redundant_tdx_resources_are_not_installed():
    assert importlib.util.find_spec("tdxhub.licenses") is None
    resources = importlib.resources.files("tdxhub.tdx")
    assert not resources.joinpath("README.md").is_file()
    assert not resources.joinpath("UPSTREAM.json").is_file()
