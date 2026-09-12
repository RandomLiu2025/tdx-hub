"""Readers for local TongDaXin data files."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from struct import Struct, unpack_from

import pandas as pd
from tdxpy.reader import TdxExHqDailyBarReader, TdxLCMinBarReader, TdxMinBarReader

from tdxhub.contrib.compat import TdxhubDailyBarReader
from tdxhub.exceptions import TdxhubValidationException
from tdxhub.utils import get_stock_market, to_data


class Reader:
    @staticmethod
    def factory(market: str = "std", **kwargs):
        if not isinstance(market, str):
            raise TdxhubValidationException("market 必须是 'std' 或 'ext'")
        market = market.lower()
        if market == "std":
            return StdReader(**kwargs)
        if market == "ext":
            return ExtReader(**kwargs)
        raise TdxhubValidationException("market 必须是 'std' 或 'ext'")


class ReaderBase:
    """Base local reader accepting either a TDX root or its ``vipdoc`` path."""

    def __init__(self, tdxdir: str | Path | None = None) -> None:
        if tdxdir is None:
            raise TdxhubValidationException("tdxdir 不能为空")

        supplied = Path(tdxdir).expanduser()
        if not supplied.is_dir():
            raise NotADirectoryError(f"tdxdir 目录不存在: {supplied}")

        if supplied.name.lower() == "vipdoc":
            self.vipdoc = supplied
            self.tdxdir = supplied.parent
        else:
            self.tdxdir = supplied
            self.vipdoc = supplied / "vipdoc"

        if not self.vipdoc.is_dir():
            raise NotADirectoryError(f"vipdoc 目录不存在: {self.vipdoc}")

    def find_path(
        self,
        symbol: str,
        subdir: str = "lday",
        suffix: str | Sequence[str] | None = None,
        **kwargs,
    ) -> Path | tuple[str, str, list[str]] | None:
        if not isinstance(symbol, str) or not symbol.strip():
            raise TdxhubValidationException("symbol 不能为空")

        symbol = symbol.strip().lower()
        if "#" in symbol:
            market = "ds"
        elif symbol.startswith("88"):
            market = "sh"
        else:
            market = get_stock_market(symbol, string=True)

        if market in {"sh", "sz", "bj"}:
            for prefix in ("sh", "sz", "bj"):
                if symbol.startswith(prefix):
                    symbol = symbol[len(prefix):]
                    break
            symbol = f"{market}{symbol}"

        if suffix is None:
            suffixes: list[str] = []
        elif isinstance(suffix, str):
            suffixes = [suffix]
        else:
            suffixes = list(suffix)
        suffixes = [item.lstrip(".") for item in suffixes if item]

        if kwargs.get("debug"):
            return market, symbol, suffixes

        if subdir == "ds_cache":
            cache_dir = self.tdxdir / "T0002" / "ds_cache"
            if not cache_dir.is_dir():
                return None
            requested = Path(symbol).name.lower()
            for extension in suffixes:
                full_suffix = f".{extension.lower()}"
                requested_stem = requested.removesuffix(full_suffix)
                wanted_code = requested_stem.split("#", 1)[-1]
                if wanted_code.startswith(("sh", "sz", "bj")):
                    wanted_code = wanted_code[2:]
                if not wanted_code.startswith("t"):
                    wanted_code = f"t{wanted_code}"
                for candidate in cache_dir.iterdir():
                    candidate_name = candidate.name.lower()
                    if not candidate.is_file() or not candidate_name.endswith(full_suffix):
                        continue
                    candidate_stem = candidate_name.removesuffix(full_suffix)
                    if candidate_stem == requested_stem or candidate_stem.split("#", 1)[-1] == wanted_code:
                        return candidate
            return None

        for extension in suffixes:
            candidate = self.vipdoc / market / subdir / f"{symbol}.{extension}"
            if candidate.is_file():
                return candidate
        return None


class StdReader(ReaderBase):
    """Reader for Shanghai, Shenzhen and Beijing securities."""

    def daily(self, symbol: str, **kwargs) -> pd.DataFrame:
        normalized = Path(symbol).stem
        if "#" in normalized or normalized.upper().startswith("T"):
            return self.delisted_daily(normalized, **kwargs)

        options = dict(kwargs)
        with_turnover = bool(options.pop("turnover", False))
        gbbq = options.pop("gbbq", None)
        actions = gbbq if gbbq is not None else options.get("xdxr")
        if with_turnover and actions is None:
            raise TdxhubValidationException("turnover=True 时必须提供 xdxr 或 gbbq 股本数据")
        if gbbq is not None and options.get("xdxr") is None:
            options["xdxr"] = gbbq

        filepath = self.find_path(normalized, subdir="lday", suffix="day")
        raw = TdxhubDailyBarReader().get_df(str(filepath)) if filepath else None
        result = to_data(raw, symbol=normalized, **options)
        if not with_turnover:
            return result

        from tdxhub.gbbq import enrich_turnover

        return enrich_turnover(result, actions, code=normalized)

    def delisted_daily(self, symbol: str, **kwargs) -> pd.DataFrame:
        """Read a delisted-security daily cache from ``T0002/ds_cache``."""
        options = dict(kwargs)
        with_turnover = bool(options.pop("turnover", False))
        gbbq = options.pop("gbbq", None)
        actions = gbbq if gbbq is not None else options.get("xdxr")
        if with_turnover and actions is None:
            raise TdxhubValidationException("turnover=True 时必须提供 xdxr 或 gbbq 股本数据")

        normalized = Path(symbol).name.removesuffix(".~~~day")
        filepath = self.find_path(normalized, subdir="ds_cache", suffix="~~~day")
        columns = ["open", "high", "low", "close", "amount", "volume"]
        if filepath is None:
            result = pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], name="date"))
        else:
            data = filepath.read_bytes()
            if len(data) < 14:
                raise ValueError(f"退市缓存文件过短: {len(data)} 字节")
            count = unpack_from("<I", data, 10)[0]
            expected_size = 14 + count * 32
            if expected_size > len(data):
                raise ValueError(f"记录数 {count} 超出文件大小 {len(data)}")

            record = Struct("<I5fI4x")
            rows = []
            for offset in range(14, expected_size, record.size):
                date, open_, high, low, close, amount, volume = record.unpack_from(data, offset)
                rows.append(
                    {
                        "date": pd.to_datetime(str(date), format="%Y%m%d"),
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "amount": amount,
                        "volume": volume / 100,
                    }
                )
            result = pd.DataFrame.from_records(rows, columns=["date", *columns]).set_index("date")

        result.attrs.update(
            {
                "source": "local_delisted",
                "source_path": str(filepath) if filepath is not None else None,
                "symbol": normalized.split("#", 1)[-1],
            }
        )
        if not with_turnover:
            return result

        from tdxhub.gbbq import enrich_turnover

        return enrich_turnover(result, actions, code=normalized.split("#", 1)[-1])

    def minute(self, symbol: str, suffix: int | str = 1, **kwargs) -> pd.DataFrame:
        normalized = Path(symbol).stem
        is_five_minute = str(suffix) == "5"
        subdir = "fzline" if is_five_minute else "minline"
        extensions = ["lc5", "5"] if is_five_minute else ["lc1", "1"]
        filepath = self.find_path(normalized, subdir=subdir, suffix=extensions)
        if filepath is None:
            return pd.DataFrame()

        parser = TdxLCMinBarReader() if filepath.suffix.startswith(".lc") else TdxMinBarReader()
        return to_data(parser.get_df(str(filepath)), symbol=normalized, **kwargs)

    def fzline(self, symbol: str, **kwargs) -> pd.DataFrame:
        return self.minute(symbol, suffix=5, **kwargs)

    def block_new(self, name: str | None = None, symbol: list[str] | None = None, group: bool = False, **kwargs):
        from tdxhub.tools.customize import Customize

        reader = Customize(tdxdir=str(self.tdxdir))
        if symbol:
            return reader.create(name=name, symbol=symbol, **kwargs)
        return reader.search(name=name, group=group)

    def block(self, symbol: str = "", group: bool = False, **kwargs):
        from tdxhub.parse import BaseParse

        return BaseParse(str(self.tdxdir)).parse(symbol, group=group, **kwargs)

    def official(self, symbol: str):
        from tdxhub.parse import BaseParse

        return BaseParse(str(self.tdxdir)).official(symbol)

    def beijing_stocks(self) -> pd.DataFrame:
        """Read the local Beijing Stock Exchange security directory."""
        result = self.official("tdxbjmore.cfg")
        return result if result is not None else pd.DataFrame()

    def stock_industries(self) -> pd.DataFrame:
        """Read local security industry assignments with resolved names."""
        from tdxhub.official import associate_industries

        assignments = self.official("tdxhy.cfg")
        if assignments is None:
            assignments = pd.DataFrame(
                columns=["market", "code", "tdx_industry_code", "sw_industry_code", "source", "raw_fields"]
            )
        dictionary = self.official("incon.dat")
        if dictionary is None:
            dictionary = pd.DataFrame(columns=["source", "code", "name"])
        return associate_industries(assignments, dictionary)


class ExtReader(ReaderBase):
    """Reader for TDX extended-market files."""

    def __init__(self, tdxdir: str | Path | None = None) -> None:
        super().__init__(tdxdir)
        self.reader = TdxExHqDailyBarReader()

    def daily(self, symbol: str) -> pd.DataFrame:
        filepath = self.find_path(symbol, subdir="lday", suffix="day")
        return to_data(self.reader.get_df(str(filepath)) if filepath else None)

    def minute(self, symbol: str) -> pd.DataFrame:
        filepath = self.find_path(symbol, subdir="minline", suffix=["lc1", "1"])
        return to_data(self.reader.get_df(str(filepath)) if filepath else None)

    def fzline(self, symbol: str) -> pd.DataFrame:
        filepath = self.find_path(symbol, subdir="fzline", suffix=["lc5", "5"])
        return to_data(self.reader.get_df(str(filepath)) if filepath else None)
