"""Structured readers for official TongDaXin data files."""

from tdxhub.official.parser import (
    associate_industries,
    parse_hspy,
    parse_incon,
    parse_official,
    parse_spblock,
    parse_tdxbjmore,
    parse_tdxbk,
    parse_tdxhy,
    parse_tdxstat,
    parse_tdxstat2,
    parse_tdxzs,
    parse_xgsg,
    stock_block_index,
)

__all__ = [
    "associate_industries",
    "parse_hspy",
    "parse_incon",
    "parse_official",
    "parse_spblock",
    "parse_tdxbjmore",
    "parse_tdxbk",
    "parse_tdxstat",
    "parse_tdxstat2",
    "parse_tdxhy",
    "parse_tdxzs",
    "parse_xgsg",
    "stock_block_index",
]
