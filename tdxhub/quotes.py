import ipaddress
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, suppress
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas
import pandas as pd
from tdxpy.exceptions import TdxConnectionError, TdxFunctionCallError, ValidationException
from tdxpy.exhq import TdxExHq_API
from tdxpy.hq import TdxHq_API
from tenacity import retry, retry_if_exception_type, retry_if_result, stop_after_attempt, wait_random
from tqdm import tqdm

from tdxhub import config
from tdxhub.cache import PersistentDataFrameCache
from tdxhub.consts import MARKET_BJ, MARKET_SH, MARKET_SZ, return_last_value
from tdxhub.exceptions import TdxhubConnectionError, TdxhubValidationException
from tdxhub.f10 import f10_frame, normalize_f10_content
from tdxhub.failover import EndpointPool, FailoverClient, FailoverClientPool
from tdxhub.logger import logger
from tdxhub.security import filter_security_directory, normalize_security_type
from tdxhub.server import check_server
from tdxhub.utils import get_config_path, get_frequency, get_stock_markets, to_data

_QUOTE_METADATA_CACHE = PersistentDataFrameCache()
_QUOTE_METADATA_CACHE_VERSION = 1


def _quote_metadata_cache_directory() -> Path:
    configured = config.get('CACHE.QUOTE_METADATA.DIRECTORY', 'caches/quotes')
    return Path(get_config_path(str(configured)))


def _quote_metadata_ttl(name: str, default: float) -> float:
    value = config.get(f'CACHE.QUOTE_METADATA.{name}', default)
    try:
        ttl = float(value)
    except (TypeError, ValueError):
        logger.warning('忽略无效缓存周期 CACHE.QUOTE_METADATA.%s=%r', name, value)
        return default
    if not math.isfinite(ttl) or ttl < 0:
        logger.warning('忽略无效缓存周期 CACHE.QUOTE_METADATA.%s=%r', name, value)
        return default
    return ttl


def _quote_metadata_cache_file(name: str) -> Path:
    return _quote_metadata_cache_directory() / f'{name}-v{_QUOTE_METADATA_CACHE_VERSION}.pkl'


class Quotes:
    @staticmethod
    def factory(market='std', **kwargs):
        """
        股票市场 工厂方法

        :param market:  std 股票市场, ext 扩展市场， 默认股票市场
        :param kwargs:  可变参数
        :return: object
        """

        logger.debug(kwargs)

        if not isinstance(market, str):
            raise TdxhubValidationException("market 必须是 'std' 或 'ext'")
        market = market.lower()
        if market == 'ext':
            return ExtQuotes(**kwargs)
        if market == 'std':
            return StdQuotes(**kwargs)
        raise TdxhubValidationException("market 必须是 'std' 或 'ext'")


def valid_server(server):
    if server is None:
        return None
    if not isinstance(server, (tuple, list)) or len(server) != 2:
        raise ValueError('Server 格式错误. 例如: server = ("127.0.0.1", 7709)')
    address, port = server
    try:
        address = str(ipaddress.ip_address(address))
        port = int(port)
    except (ValueError, TypeError) as exc:
        raise ValueError('Server 格式错误. 例如: server = ("127.0.0.1", 7709)') from exc
    if not 1 <= port <= 65535:
        raise ValueError('Server 端口必须在 1..65535 之间')
    return address, port


class BaseQuotes:
    verbose = False
    timeout = 15

    def __init__(self, server=None, bestip: bool = False, timeout: int = None, **kwargs) -> None:
        self._client_local = threading.local()
        self._client = None
        self.server = None
        self.bestip = None
        logger.debug('config.setup()')
        config.setup()

        logger.debug(f'server => {server}')
        self.server = valid_server(server)

        logger.debug(f'bestip => {bestip}')
        bestip and check_server(sync=True)

        self.timeout = 15 if timeout is None else timeout
        if self.timeout <= 0:
            raise TdxhubValidationException('timeout 必须大于 0')
        logger.debug(f'timeout => {self.timeout}')

        self.verbose = kwargs.get('verbose', False)
        logger.debug(f'verbose => {self.verbose}')

    @property
    def client(self):
        local = getattr(self, '_client_local', None)
        if local is not None and hasattr(local, 'override'):
            return local.override
        return getattr(self, '_client', None)

    @client.setter
    def client(self, value):
        self._client = value

    @contextmanager
    def _using_client(self, client):
        """Temporarily bind one client to the current worker thread."""

        local = getattr(self, '_client_local', None)
        if local is None:
            local = threading.local()
            self._client_local = local
        missing = object()
        previous = getattr(local, 'override', missing)
        local.override = client
        try:
            yield
        finally:
            if previous is missing:
                del local.override
            else:
                local.override = previous

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        with suppress(Exception):
            self.close()

    def reconnect(self):
        if self.closed:
            logger.debug('服务器连接已断开，正进行重新连接...')
            if isinstance(self.client, FailoverClient):
                self.client.connect()
            else:
                self.client.connect(*self.server, time_out=self.timeout)

    def close(self):
        logger.debug('close')
        client_pool = getattr(self, '_stock_info_client_pool', None)
        if client_pool is not None:
            client_pool.close()
        elif self.client is not None and hasattr(self.client, 'close'):
            self.client.close()

    @property
    def closed(self) -> bool:
        if isinstance(self.client, FailoverClient):
            return not self.client.is_connected
        socket_client = getattr(self.client, 'client', None)
        return socket_client is None or bool(getattr(socket_client, '_closed', False))

    def server_status(self):
        """Return health information for configured runtime quote servers."""

        if isinstance(self.client, FailoverClient):
            return self.client.server_status()
        return [{
            'server': self.server,
            'active': not self.closed,
            'failures': 0,
            'cooldown_remaining': 0.0,
            'last_error': None,
        }]

    def pool(self):
        ...



def _validate_failover_options(max_failovers, unhealthy_cooldown, max_candidates):
    if isinstance(max_failovers, bool) or not isinstance(max_failovers, int) or max_failovers < 0:
        raise TdxhubValidationException('max_failovers 必须是大于等于 0 的整数')
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates <= 0:
        raise TdxhubValidationException('max_candidates 必须是大于 0 的整数')
    try:
        unhealthy_cooldown = float(unhealthy_cooldown)
    except (TypeError, ValueError) as exc:
        raise TdxhubValidationException('unhealthy_cooldown 必须是大于等于 0 的数字') from exc
    if not math.isfinite(unhealthy_cooldown) or unhealthy_cooldown < 0:
        raise TdxhubValidationException('unhealthy_cooldown 必须是大于等于 0 的数字')
    return unhealthy_cooldown


def _quote_candidates(kind, requested_server, fallback_servers):
    hosts = config.get(f'SERVER.{kind}', []) or []
    configured = []
    configured_best = config.get(f'BESTIP.{kind}')
    if configured_best:
        configured.append(valid_server(configured_best))
    configured.extend(valid_server(item[1:3]) for item in hosts)

    if requested_server:
        candidates = [requested_server]
        if fallback_servers:
            candidates.extend(configured)
    else:
        candidates = configured

    return list(dict.fromkeys(candidates))


def _probe_quote_endpoints(candidates, client_factory, healthcheck, timeout, max_candidates):
    def probe(endpoint):
        client = client_factory()
        try:
            connected = client.connect(*endpoint, time_out=min(timeout, 3))
            if not connected:
                return endpoint, False, TdxConnectionError(f'无法连接 {endpoint[0]}:{endpoint[1]}')
            healthy = healthcheck(client)
        except (OSError, TdxConnectionError, TdxFunctionCallError, ValidationException) as exc:
            return endpoint, False, exc
        finally:
            # tdxpy may raise while closing a socket whose connect() failed.
            # Cleanup must not mask the original probe result.
            with suppress(Exception):
                client.close()
        return endpoint, bool(healthy), None

    if not candidates:
        return [], None
    workers = min(32, len(candidates))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='tdxhub-quotes') as pool:
        checks = list(pool.map(probe, candidates))
    healthy = [endpoint for endpoint, available, _ in checks if available][:max_candidates]
    last_error = next((error for _, _, error in reversed(checks) if error is not None), None)
    return healthy, last_error


def check_empty(value):
    """
    重试判断函数

    :param value: 要判断的值
    :return:
    """
    return value.empty if isinstance(value, pd.DataFrame) else not value


class StdQuotes(BaseQuotes):
    """
    股票市场实时行情"""

    @staticmethod
    def _code_market(symbol):
        """Return the numeric market and bare code expected by tdxpy."""
        try:
            market, code = get_stock_markets([symbol])[0]
        except (TypeError, ValueError, IndexError) as exc:
            raise TdxhubValidationException(f'证券代码错误: {symbol!r}') from exc
        return int(market), code

    def __init__(
        self,
        server=None,
        bestip=False,
        timeout=15,
        heartbeat=False,
        auto_retry=True,
        raise_exception=False,
        failover=True,
        fallback_servers=False,
        max_failovers=2,
        unhealthy_cooldown=60.0,
        max_candidates=5,
        **kwargs,
    ):
        """Create a standard quote client with bounded runtime failover."""

        super().__init__(bestip=bestip, timeout=timeout, server=server, **kwargs)
        unhealthy_cooldown = _validate_failover_options(max_failovers, unhealthy_cooldown, max_candidates)
        requested_server = self.server
        if requested_server:
            config.set('BESTIP.HQ', requested_server)

        candidates = _quote_candidates('HQ', requested_server, fallback_servers)
        if not candidates:
            raise TdxhubValidationException('没有可用的标准行情服务器配置')

        def probe_factory():
            return TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=True)
        healthy_endpoints, last_error = _probe_quote_endpoints(
            candidates,
            probe_factory,
            lambda client: client.get_security_bars(9, MARKET_SH, '600000', 0, 1),
            self.timeout,
            max_candidates,
        )
        if not healthy_endpoints:
            message = f'无法连接任何可用的标准行情服务器，已尝试: {candidates}'
            if last_error:
                message = f'{message}: {last_error}'
            raise TdxhubConnectionError(message, data={'servers': candidates}) from last_error

        api_options = {}
        if 'multithread' in kwargs:
            api_options['multithread'] = kwargs['multithread']

        endpoint_pool = EndpointPool(healthy_endpoints, cooldown=unhealthy_cooldown)
        self.client = FailoverClient(
            endpoint_pool,
            lambda: TdxHq_API(
                heartbeat=heartbeat,
                auto_retry=auto_retry,
                raise_exception=True,
                **api_options,
            ),
            timeout=self.timeout,
            max_failovers=max_failovers if failover else 0,
            raise_exception=raise_exception,
            on_switch=lambda endpoint: setattr(self, 'server', endpoint),
        )
        try:
            connected = self.client.connect()
        except (OSError, TdxConnectionError, TdxFunctionCallError) as exc:
            raise TdxhubConnectionError(
                f'无法连接任何可用的标准行情服务器，已尝试: {healthy_endpoints}: {exc}',
                data={'servers': healthy_endpoints},
            ) from exc
        if not connected:
            raise TdxhubConnectionError(
                f'无法连接任何可用的标准行情服务器，已尝试: {healthy_endpoints}',
                data={'servers': healthy_endpoints},
            )

        self._stock_info_client_pool = FailoverClientPool(self.client, max_size=4)
        logger.debug(f'server: {self.server}')

    def traffic(self):
        return self.client.get_traffic_stats()

    def quotes(self, symbol=None, **kwargs):
        """
        获取实时日行情数据

        :param symbol: 股票代码
        :return: pd.dataFrame or None
        """

        if symbol is None or (isinstance(symbol, str) and not symbol.strip()):
            return to_data(None)

        if not isinstance(symbol, str) and hasattr(symbol, '__len__') and len(symbol) == 0:
            return to_data(None)

        if type(symbol) is str:
            symbol = [symbol]

        try:
            symbol = get_stock_markets(symbol)
            result = self.client.get_security_quotes(symbol)
        except ValidationException:
            return to_data(None)

        data = to_data(result, symbol=symbol, client=self, **kwargs)
        internal_columns = [
            column
            for column in data.columns
            if column in {'active1', 'active2'}
            or (isinstance(column, str) and column.startswith('reversed_bytes'))
        ]
        return data.drop(columns=internal_columns)

    def bars(self, symbol='000001', frequency=9, start=0, offset=800, **kwargs):
        """
        获取实时日K线数据

        :param symbol: 股票代码
        :param frequency: 数据频次
        :param start: 开始位置
        :param offset: 每次获取条数
        :return: pd.dataFrame or None
        """
        frequency = get_frequency(frequency)
        options = dict(kwargs)
        with_turnover = bool(options.pop("turnover", False))
        gbbq = options.pop("gbbq", None)
        if with_turnover and frequency != 9:
            raise TdxhubValidationException("换手率仅支持股票日 K")

        actions = gbbq if gbbq is not None else options.get("xdxr")
        market, code = self._code_market(symbol)
        try:
            offset = min(int(offset), 800)
            start = int(start)
        except (TypeError, ValueError) as exc:
            raise TdxhubValidationException('start 和 offset 必须是整数') from exc
        if start < 0 or offset <= 0:
            raise TdxhubValidationException('start 必须大于等于 0，offset 必须大于 0')

        raw = self.client.get_security_bars(int(frequency), market, code, start, offset)
        if with_turnover and actions is None and raw is not None and len(raw) > 0:
            actions = self.xdxr(symbol)
        if options.get("xdxr") is None and actions is not None:
            options["xdxr"] = actions

        result = to_data(raw, symbol=code, client=self, **options)
        if not with_turnover:
            return result

        from tdxhub.gbbq import enrich_turnover

        return enrich_turnover(result, actions, code=code)

    def stock_count(self, market=MARKET_SH, security_type=None):
        """Return a market directory count, optionally filtered by security type."""
        if market not in [0, 1, 2]:
            raise TdxhubValidationException('市场代码错误')

        normalized_type = normalize_security_type(security_type)
        if normalized_type is not None:
            return len(self.stocks(market=market, security_type=normalized_type))
        return self.client.get_security_count(market=market)

    def _load_stock_directory(self, market):
        if market == MARKET_BJ:
            return self._beijing_stocks()

        counts = self.stock_count(market=market)
        frames = []
        if counts > 0:
            for start in tqdm(range(0, counts, 1000), ascii=True):
                page = self.client.get_security_list(market=market, start=start)
                frames.append(to_data(page))
        return pandas.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def stocks(self, market=MARKET_SH, security_type=None, *, refresh=False):
        """Return a cached market directory, optionally filtered by type.

        Complete directories are shared by all clients in this process and are
        persisted below ``~/.tdxhub/caches/quotes``. They refresh lazily every
        six hours by default; pass ``refresh=True`` to force an update.
        """
        if market not in [MARKET_SZ, MARKET_SH, MARKET_BJ]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深京市场')
        if not isinstance(refresh, bool):
            raise TdxhubValidationException('refresh 必须是布尔值')

        normalized_type = normalize_security_type(security_type)
        cached = _QUOTE_METADATA_CACHE.get(
            _quote_metadata_cache_file(f'stocks-{market}'),
            lambda: self._load_stock_directory(market),
            ttl=_quote_metadata_ttl('STOCKS_TTL', 6 * 3600),
            refresh=refresh,
        )
        return filter_security_directory(cached, market, normalized_type)

    def stock_list(self, market=MARKET_SH, start=0):
        """Return one security-directory page, matching the TDX 1000-row API."""
        if market not in [0, 1, 2]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深京市场')
        try:
            start = int(start)
        except (TypeError, ValueError) as exc:
            raise TdxhubValidationException('start 必须是整数') from exc
        if not 0 <= start <= 65535:
            raise TdxhubValidationException('start 必须在 0..65535 之间')

        if market == 2:
            return self._beijing_stocks().iloc[start:start + 1000].reset_index(drop=True)

        return to_data(self.client.get_security_list(market=market, start=start))

    def _get_zhb_file(self, filename):
        """Download one named member from the official ``zhb.zip`` report."""
        content = self.client.get_report_file_by_size('zhb.zip')
        if not content:
            return b''

        try:
            with ZipFile(BytesIO(content)) as archive:
                member = next(
                    (name for name in archive.namelist() if Path(name).name.lower() == filename.lower()),
                    None,
                )
                if member is None:
                    raise TdxhubValidationException(f'zhb.zip 中缺少 {filename}')
                return archive.read(member)
        except BadZipFile as exc:
            raise TdxhubValidationException('zhb.zip 文件格式错误') from exc

    def _beijing_stocks(self):
        """Download and parse the BSE directory without querying unsupported market 2."""
        from tdxhub.official import parse_tdxbjmore

        return parse_tdxbjmore(self._get_zhb_file('tdxbjmore.cfg'))

    def stock_industries(self, symbols=None, *, refresh=False):
        """Return online TongDaXin and Shenwan industry assignments.

        ``symbols`` may be one security code or a list/tuple of codes. The
        complete association is cached process-wide and on disk; pass
        ``refresh=True`` to download the two official source files again.
        """
        from tdxhub.official import associate_industries, parse_incon, parse_tdxhy

        if not isinstance(refresh, bool):
            raise TdxhubValidationException('refresh 必须是布尔值')

        if symbols is None:
            requested = None
        elif isinstance(symbols, str):
            requested = [symbols]
        elif isinstance(symbols, (list, tuple)):
            requested = list(symbols)
        else:
            raise TdxhubValidationException('证券代码必须是字符串、列表或元组')

        market_names = {MARKET_SZ: 'sz', MARKET_SH: 'sh', MARKET_BJ: 'bj'}
        keys = None
        if requested is not None:
            keys = []
            for symbol in requested:
                market, code = self._code_market(symbol)
                keys.append((market_names[market], code))
            if not keys:
                empty_assignments = parse_tdxhy(b'')
                empty_dictionary = parse_incon(b'')
                return associate_industries(empty_assignments, empty_dictionary)

        def load_industries():
            assignment_content = self.client.get_report_file_by_size('tdxhy.cfg') or b''
            if isinstance(assignment_content, (bytearray, memoryview)):
                assignment_content = bytes(assignment_content)
            dictionary_content = self._get_zhb_file('incon.dat')
            assignments = parse_tdxhy(assignment_content)
            dictionary = parse_incon(dictionary_content)
            return associate_industries(assignments, dictionary)

        cached = _QUOTE_METADATA_CACHE.get(
            _quote_metadata_cache_file('stock-industries'),
            load_industries,
            ttl=_quote_metadata_ttl('INDUSTRIES_TTL', 24 * 3600),
            refresh=refresh,
        )

        if keys is None:
            result = cached.copy(deep=True)
        else:
            rows = []
            for market, code in keys:
                matched = cached.loc[(cached['market'] == market) & (cached['code'] == code)]
                if not matched.empty:
                    rows.append(matched)
            result = (
                pd.concat(rows, ignore_index=True)
                if rows
                else cached.iloc[0:0].copy(deep=True).reset_index(drop=True)
            )

        if 'raw_fields' in result:
            result['raw_fields'] = result['raw_fields'].map(deepcopy)
        result.attrs = deepcopy(cached.attrs)
        return result

    def _stock_info_directory(self, market, *, refresh=False):
        if refresh:
            return self.stocks(market, refresh=True)
        return self.stocks(market)

    def _stock_info_source(self, source, symbol):
        client_pool = getattr(self, '_stock_info_client_pool', None)
        if client_pool is None:
            return getattr(self, source)(symbol)
        with client_pool.connection() as client, self._using_client(client):
            return getattr(self, source)(symbol)

    def stock_info(
        self,
        symbols,
        *,
        refresh_industries=False,
        refresh_directories=False,
        max_workers=4,
    ):
        """Return one merged security, quote, finance and industry row per symbol."""
        from tdxhub.stock_info import (
            INDUSTRY_COLUMNS,
            STOCK_INFO_COLUMNS,
            build_stock_info_row,
            empty_stock_info_frame,
            frame_record,
            normalize_code,
            normalize_market_id,
        )

        if not isinstance(refresh_industries, bool):
            raise TdxhubValidationException('refresh_industries 必须是布尔值')
        if not isinstance(refresh_directories, bool):
            raise TdxhubValidationException('refresh_directories 必须是布尔值')
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or not 1 <= max_workers <= 16
        ):
            raise TdxhubValidationException('max_workers 必须是 1..16 之间的整数')
        if isinstance(symbols, str):
            requested = [symbols]
        elif isinstance(symbols, (list, tuple)):
            requested = list(symbols)
        else:
            raise TdxhubValidationException('证券代码必须是字符串、列表或元组')
        if not requested:
            return empty_stock_info_frame()

        exchanges = {MARKET_SZ: 'sz', MARKET_SH: 'sh', MARKET_BJ: 'bj'}
        normalized = []
        for symbol in requested:
            if not isinstance(symbol, str) or not symbol.strip():
                raise TdxhubValidationException(f'证券代码错误: {symbol!r}')
            market_id, code = self._code_market(symbol)
            if market_id not in exchanges or not code.isdigit() or len(code) != 6:
                raise TdxhubValidationException(f'证券代码错误: {symbol!r}')
            normalized.append((market_id, exchanges[market_id], code))

        unique = list(dict.fromkeys(normalized))
        full_codes = [f'{exchange}{code}' for _, exchange, code in unique]

        securities = {}
        for market_id in dict.fromkeys(item[0] for item in unique):
            directory = self._stock_info_directory(market_id, refresh=refresh_directories)
            if directory is None or directory.empty:
                continue
            for record in directory.to_dict('records'):
                record_code = normalize_code(record.get('code'))
                if record_code is not None:
                    securities[(market_id, record_code)] = record

        quote_rows = {}
        quote_code_counts = {}
        realtime_symbols = [
            f'{exchange}{code}'
            for market_id, exchange, code in unique
            if market_id in (MARKET_SZ, MARKET_SH)
        ]
        if realtime_symbols:
            realtime = self.quotes(realtime_symbols)
            if realtime is not None:
                for record in realtime.to_dict('records'):
                    record_code = normalize_code(record.get('code'))
                    if record_code is None:
                        continue
                    record_market = normalize_market_id(record.get('market'))
                    if record_market is not None:
                        quote_rows[(record_market, record_code)] = record
                    quote_code_counts.setdefault(record_code, []).append(record)

        industry_rows = {}
        industries = self.stock_industries(full_codes, refresh=refresh_industries)
        if industries is not None:
            for record in industries.to_dict('records'):
                record_code = normalize_code(record.get('code'))
                record_market = normalize_market_id(record.get('market'))
                if record_code is not None and record_market is not None:
                    industry_rows[(record_market, record_code)] = {
                        column: record.get(column) for column in INDUSTRY_COLUMNS
                    }

        source_results = {item: {} for item in unique}
        jobs = [
            (item, source, f'{item[1]}{item[2]}')
            for item in unique
            if item[0] in (MARKET_SZ, MARKET_SH)
            for source in ('finance', 'xdxr', 'call_auction')
        ]
        client_pool = getattr(self, '_stock_info_client_pool', None)
        if client_pool is not None:
            client_pool.ensure_capacity(max_workers)
        if jobs:
            workers = min(max_workers, len(jobs))
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix='tdxhub-stock-info',
            ) as executor:
                futures = {
                    executor.submit(self._stock_info_source, source, full_code): (item, source, full_code)
                    for item, source, full_code in jobs
                }
                for future in as_completed(futures):
                    item, source, full_code = futures[future]
                    try:
                        source_results[item][source] = future.result()
                    except Exception as exc:
                        exc.add_note(f'汇总证券 {full_code} 数据失败')
                        raise

        unique_rows = {}
        for market_id, exchange, code in unique:
            item = (market_id, exchange, code)
            quote = quote_rows.get((market_id, code))
            if quote is None and len(quote_code_counts.get(code, ())) == 1:
                quote = quote_code_counts[code][0]
            sources = source_results[item]

            unique_rows[item] = build_stock_info_row(
                market_id=market_id,
                exchange=exchange,
                code=code,
                security=securities.get((market_id, code)),
                quote=quote,
                finance=frame_record(sources.get('finance')),
                actions=sources.get('xdxr'),
                auction=sources.get('call_auction'),
                industry=industry_rows.get((market_id, code)),
            )

        rows = [deepcopy(unique_rows[item]) for item in normalized]
        return pd.DataFrame(rows, columns=STOCK_INFO_COLUMNS, dtype=object)

    def call_auction(self, symbol, trade_date=None, **kwargs):
        """Return call-auction snapshots for one standard-market security."""
        from tdxhub.call_auction import build_call_auction_request, decode_call_auction

        market, code = self._code_market(symbol)
        try:
            request = build_call_auction_request(market, code)
        except ValueError as exc:
            raise TdxhubValidationException(f'证券代码错误: {symbol!r}') from exc
        payload = self.client.send_raw_pkg(request)
        result = decode_call_auction(payload, trade_date=trade_date)
        return to_data(result, symbol=code, client=self, **kwargs)

    def statistics(self):
        """Return verified per-security statistics from the official report archive."""
        from tdxhub.official import parse_tdxstat

        return parse_tdxstat(self._get_zhb_file('tdxstat.cfg'))

    def money_flow(self):
        """Return money-flow and block membership from the official report archive."""
        from tdxhub.official import parse_tdxstat2

        return parse_tdxstat2(self._get_zhb_file('tdxstat2.cfg'))

    def xgsg(self):
        """Return new-share subscriptions from the official report archive."""
        from tdxhub.official import parse_xgsg

        return parse_xgsg(self._get_zhb_file('xgsg.cfg'))

    def stock_all(self, security_type=None):
        """Return the combined Shenzhen, Shanghai and Beijing security directories."""
        normalized_type = normalize_security_type(security_type)
        return pandas.concat(
            [self.stocks(market, security_type=normalized_type) for market in [0, 1, 2]],
            ignore_index=True,
        )

    def index_bars(self, symbol='000001', frequency=9, start=0, offset=800, **kwargs):
        """
        获取指数k线

        :param symbol: 股票代码
        :param frequency: 数据频次
        :param start: 开始位置
        :param offset: 获取数量
        :return:
        """

        frequency = get_frequency(frequency)
        offset = (offset, 800)[offset > 800]

        market = (MARKET_SZ, MARKET_SH)[symbol[:2] in ['00', '88', '99']]
        result = self.client.get_index_bars(int(frequency), int(market), str(symbol), int(start), int(offset))

        return to_data(result, symbol=symbol, client=self, **kwargs)

    @staticmethod
    def _parse_since(since):
        if since is None:
            return None
        if not isinstance(since, str) or re.fullmatch(r'\d{8}', since) is None:
            raise TdxhubValidationException('since 必须使用 YYYYMMDD 格式')
        try:
            return pd.Timestamp(datetime.strptime(since, '%Y%m%d'))
        except ValueError as exc:
            raise TdxhubValidationException('since 必须使用有效的 YYYYMMDD 日期') from exc

    @staticmethod
    def _page_datetimes(frame):
        if 'datetime' in frame.columns:
            return pd.to_datetime(frame['datetime'], errors='coerce')
        if 'date' in frame.columns:
            return pd.to_datetime(frame['date'], errors='coerce')
        if isinstance(frame.index, pd.DatetimeIndex):
            return pd.Series(frame.index, index=frame.index)
        return None

    def _collect_pages(self, loader, page_size, since=None):
        """Collect newest-first protocol pages into an oldest-first frame."""
        since_date = self._parse_since(since)
        frames = []
        start = 0

        while start <= 65535:
            page = loader(start, page_size)
            if not isinstance(page, pd.DataFrame):
                page = to_data(page)
            if page.empty:
                break

            frames.insert(0, page)
            stop_at_since = False
            if since_date is not None:
                page_datetimes = self._page_datetimes(page)
                if page_datetimes is None:
                    raise TdxhubValidationException('K线数据缺少 datetime/date 字段')
                stop_at_since = bool((page_datetimes < since_date).fillna(False).any())

            if len(page) < page_size or stop_at_since:
                break
            start += page_size

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames)
        if since_date is not None:
            datetimes = self._page_datetimes(result)
            result = result.loc[(datetimes >= since_date).fillna(False)]
        return result

    @staticmethod
    def _adjust_collected(result, code, adjust, xdxr):
        # Pages already have normalized datetime indices. Do not parse the
        # original string columns again: pages may use different date formats.
        if result.empty or str(adjust).lower() not in {"qfq", "01", "before", "hfq", "02", "after"}:
            return result
        from tdxhub.utils.adjust import to_adjust

        return to_adjust(result, symbol=code, adjust=adjust, xdxr=xdxr)

    def bars_all(self, symbol='000001', frequency=9, since=None, **kwargs):
        """Return all available stock K-lines in chronological order."""
        frequency = get_frequency(frequency)
        options = dict(kwargs)
        adjust = options.pop("adjust", None)
        with_turnover = bool(options.pop("turnover", False))
        gbbq = options.pop("gbbq", None)
        if with_turnover and frequency != 9:
            raise TdxhubValidationException("换手率仅支持股票日 K")

        actions = gbbq if gbbq is not None else options.get("xdxr")
        result = self._collect_pages(
            lambda start, size: self.bars(
                symbol=symbol,
                frequency=frequency,
                start=start,
                offset=size,
                **options,
            ),
            800,
            since=since,
        )
        if with_turnover and actions is None and not result.empty:
            actions = self.xdxr(symbol)
        if options.get("xdxr") is None and actions is not None:
            options["xdxr"] = actions

        _, code = self._code_market(symbol)
        result = self._adjust_collected(result, code, adjust, options.get("xdxr"))
        if not with_turnover:
            return result

        from tdxhub.gbbq import enrich_turnover

        return enrich_turnover(result, actions, code=code)

    def minute_241(self, symbol="000001", since=None):
        """Return latest-day or ranged minute bars with a 09:30 auction bar."""
        from zoneinfo import ZoneInfo

        from tdxhub.minute import build_minute_241, minute_241_dates, select_latest_minute_bars

        bars = self.bars_all(symbol=symbol, frequency=8, since=since)
        if since is None:
            bars = select_latest_minute_bars(bars)
        if bars.empty:
            return bars

        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        trades_by_date = {}
        for trade_date in minute_241_dates(bars):
            if trade_date == today:
                trades = self.transaction_all(symbol=symbol)
            else:
                trades = self.transactions_all(symbol=symbol, date=trade_date.strftime("%Y%m%d"))
            trades_by_date[trade_date] = trades
        return build_minute_241(bars, trades_by_date)

    def index_all(self, symbol='000001', frequency=9, since=None, **kwargs):
        """Return all available index K-lines in chronological order."""
        adjust = kwargs.pop("adjust", None)
        result = self._collect_pages(
            lambda start, size: self.index(
                symbol=symbol,
                frequency=frequency,
                start=start,
                offset=size,
                **kwargs,
            ),
            800,
            since=since,
        )
        _, code = self._code_market(symbol)
        return self._adjust_collected(result, code, adjust, kwargs.get("xdxr"))

    def minute(self, symbol=None, **kwargs):
        """
        获取实时分时数据

        :param symbol: 股票代码
        :return: pd.DataFrame
        """

        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y%m%d')
        return self.minutes(symbol=symbol, date=today, **kwargs)

    def minutes(self, symbol=None, date='20191023', **kwargs):
        """
        分时历史数据

        :param symbol:  股票代码
        :param date:    查询日期
        :return: pd.dataFrame or None
        """

        market, code = self._code_market(symbol)

        if market not in [0, 1]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深市场')
        result = self.client.get_history_minute_time_data(market=market, code=code, date=date)
        data = to_data(result, symbol=code, client=self, **kwargs)

        from tdxhub.minute import attach_minute_timestamps

        return attach_minute_timestamps(data, date)

    def transaction(self, symbol='', start=0, offset=800, **kwargs):
        """
        查询分笔成交

        :param symbol:  股票代码
        :param start:   起始位置
        :param offset:  结束位置
        :return: pd.dataFrame or None
        """

        market, code = self._code_market(symbol)

        result = self.client.get_transaction_data(market, code, start, offset)

        return to_data(result, symbol=code, client=self, **kwargs)

    def transactions(self, symbol='', start=0, offset=800, date='20170209', **kwargs):
        """
        查询历史分笔成交

        :param symbol:  股票代码
        :param start:   起始位置
        :param offset:  获取数量
        :param date:    查询日期
        :return: pd.dataFrame or None
        """

        market, code = self._code_market(symbol)

        if market not in [0, 1]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深市场')

        result = self.client.get_history_transaction_data(market, code, start, offset, int(date))
        return to_data(result, symbol=code, client=self, **kwargs)

    def transaction_all(self, symbol='', **kwargs):
        """Return all current-day trades in chronological order."""
        return self._collect_pages(
            lambda start, size: self.transaction(
                symbol=symbol,
                start=start,
                offset=size,
                **kwargs,
            ),
            1800,
        )

    def transactions_all(self, symbol='', date='20170209', **kwargs):
        """Return all trades for one historical day in chronological order."""
        return self._collect_pages(
            lambda start, size: self.transactions(
                symbol=symbol,
                date=date,
                start=start,
                offset=size,
                **kwargs,
            ),
            2000,
        )

    def F10C(self, symbol=''):  # noqa
        """
        查询公司信息目录

        :param symbol: 股票代码
        :return: pd.dataFrame or None
        """

        market, symbol = self._code_market(symbol)

        if market not in [0, 1]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深市场')

        result = self.client.get_company_info_category(market, symbol)

        return result

    def company_content(self, symbol='', filename='', start=0, length=0):
        """Read an explicit byte range from a company information file."""
        market, code = self._code_market(symbol)

        if market not in [0, 1]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深市场')
        if not isinstance(filename, str) or not filename.strip():
            raise TdxhubValidationException('filename 不能为空')
        try:
            start = int(start)
            length = int(length)
        except (TypeError, ValueError) as exc:
            raise TdxhubValidationException('start 和 length 必须是整数') from exc
        if start < 0 or length < 0:
            raise TdxhubValidationException('start 和 length 必须大于等于 0')

        return self.client.get_company_info_content(
            market=market,
            code=code,
            filename=filename.strip(),
            start=start,
            length=length,
        )

    def F10(self, symbol='', name=''):  # noqa
        """
        读取规范化的公司信息详情

        :param name: 公司 F10 标题
        :param symbol: 股票代码
        :return: 固定列 pd.DataFrame
        """

        if not isinstance(name, str):
            raise TdxhubValidationException('name 必须是字符串')
        section = name.strip()
        market, code = self._code_market(symbol)

        if market not in [0, 1]:
            raise TdxhubValidationException('市场代码错误, 目前只支持沪深市场')

        categories = self.client.get_company_info_category(market, code) or []
        if section:
            categories = [item for item in categories if item['name'] == section]

        exchange = {MARKET_SZ: 'sz', MARKET_SH: 'sh'}[market]
        records = []
        for item in categories:
            content = self.client.get_company_info_content(
                market=market,
                code=code,
                filename=item['filename'],
                start=item['start'],
                length=item['length'],
            )
            records.append({
                'full_code': f'{exchange}{code}',
                'exchange': exchange,
                'market_id': market,
                'code': code,
                'section': item['name'],
                'filename': item['filename'],
                'start': item['start'],
                'length': item['length'],
                'content': normalize_f10_content(content),
            })

        return f10_frame(records)

    def xdxr(self, symbol='', **kwargs):
        """
        读取除权除息信息

        :param symbol: 股票代码
        :return: pd.dataFrame or None
        """

        market, symbol = self._code_market(symbol)
        result = self.client.get_xdxr_info(market, symbol)
        frame = to_data(result, symbol=symbol, client=self, **kwargs)
        frame.attrs["equity_unit"] = "ten_thousand_shares"
        return frame

    def finance(self, symbol='000001', **kwargs):
        """
        读取财务信息

        :param symbol: 股票代码
        :return:
        """

        market, symbol = self._code_market(symbol)
        result = self.client.get_finance_info(market=market, code=symbol)

        return to_data(result, symbol=symbol, client=self, **kwargs)

    def k(self, symbol='', begin=None, end=None, **kwargs):
        """
        读取k线信息

        :param symbol:  股票代码
        :param begin:   开始日期
        :param end:     截止日期
        :return: pd.dataFrame or None
        """

        result = self.get_k_data(symbol, begin, end)
        return to_data(result, symbol=symbol, **kwargs)

    def ohlc(self, **kwargs):
        return self.k(**kwargs)

    def get_k_data(self, code, start_date, end_date):
        if start_date is None or end_date is None:
            return pd.DataFrame()
        try:
            start = pd.Timestamp(start_date)
            end = pd.Timestamp(end_date)
        except (TypeError, ValueError) as exc:
            raise TdxhubValidationException('日期格式错误') from exc
        if start >= end:
            return pd.DataFrame()

        # 开始时间离现在有几天
        first = (end - pd.Timestamp(datetime.now().date())).days
        first = (abs(first), 0)[first >= 0]

        # 结束时间离现在有几天
        last = (start - pd.Timestamp(datetime.now().date())).days
        last = (abs(last), 0)[last >= 0]

        # 去除节假日
        first -= int(first / 2.8)  # 非交易日大概是全年的1/3
        last -= int(last / 3.5)  # 非交易日大概是全年的1/3

        temp = []
        market, code = self._code_market(code)

        pages = max(1, math.ceil((last - first) / 800))
        for i in range(pages):
            data = self.client.get_security_bars(9, market, code, (first + i * 800), 800)
            if data is not None:
                frame = self.client.to_df(data)
                if frame is not None and not frame.empty:
                    temp.append(frame)

        if not temp:
            return pd.DataFrame()
        data = pd.concat(temp, ignore_index=True)
        if 'datetime' not in data:
            return pd.DataFrame()
        data = data.assign(date=data['datetime'].apply(lambda x: str(x)[0:10])).assign(code=str(code))
        data = data.set_index('date', drop=False, inplace=False)
        data = data.drop(['year', 'month', 'day', 'hour', 'minute', 'datetime'], axis=1, errors='ignore')
        data = data.loc[(data.date >= start.strftime('%Y-%m-%d')) & (data.date < end.strftime('%Y-%m-%d'))]
        data = data.sort_index()

        return data

    def index(self, symbol='000001', frequency=9, start=0, offset=800, **kwargs):
        """
        获取指数k线

        K线种类:
        - 0 5分钟K线
        - 1 15分钟K线
        - 2 30分钟K线
        - 3 1小时K线
        - 4 日K线
        - 5 周K线
        - 6 月K线
        - 7 1分钟
        - 8 1分钟K线
        - 9 日K线
        - 10 季K线
        - 11 年K线

        :param symbol:      股票代码
        :param frequency:   数据频次
        :param market:      证券市场
        :param start:       开始位置
        :param offset:      每次获取条数
        :return: pd.dataFrame or None
        """
        frequency = get_frequency(frequency)

        offset = (offset, 800)[offset > 800]
        market = (MARKET_SZ, MARKET_SH)[symbol[:2] in ['00', '88', '99']]
        result = self.client.get_index_bars(int(frequency), int(market), str(symbol), int(start), int(offset))

        return to_data(result, symbol=symbol, client=self, **kwargs)

    def block(self, tofile='block.dat', **kwargs):
        """
        获取证券板块信息

        :param tofile: 保存文件
        :return: pd.dataFrame or None
        """

        result = self.client.get_and_parse_block_info(tofile)
        return to_data(result, **kwargs)


class ExtQuotes(BaseQuotes):
    """扩展市场实时行情"""

    # server = ("112.74.214.43", 7727)

    def __init__(
        self,
        server=None,
        bestip=False,
        timeout=15,
        heartbeat=False,
        auto_retry=True,
        raise_exception=False,
        failover=True,
        fallback_servers=False,
        max_failovers=2,
        unhealthy_cooldown=60.0,
        max_candidates=5,
        **kwargs,
    ):
        """Create an extended-market quote client with bounded failover."""

        super().__init__(bestip=bestip, timeout=timeout, server=server, **kwargs)
        unhealthy_cooldown = _validate_failover_options(max_failovers, unhealthy_cooldown, max_candidates)
        requested_server = self.server
        if requested_server:
            config.set('BESTIP.EX', requested_server)

        candidates = _quote_candidates('EX', requested_server, fallback_servers)
        if not candidates:
            raise TdxhubValidationException('没有可用的扩展行情服务器配置')

        def probe_factory():
            return TdxExHq_API(heartbeat=False, auto_retry=False, raise_exception=True)

        healthy_endpoints, last_error = _probe_quote_endpoints(
            candidates,
            probe_factory,
            lambda client: client.get_instrument_count(),
            self.timeout,
            max_candidates,
        )
        if not healthy_endpoints:
            message = f'无法连接任何可用的扩展行情服务器，已尝试: {candidates}'
            if last_error:
                message = f'{message}: {last_error}'
            raise TdxhubConnectionError(message, data={'servers': candidates}) from last_error

        api_options = {}
        if 'multithread' in kwargs:
            api_options['multithread'] = kwargs['multithread']

        endpoint_pool = EndpointPool(healthy_endpoints, cooldown=unhealthy_cooldown)
        self.client = FailoverClient(
            endpoint_pool,
            lambda: TdxExHq_API(
                heartbeat=heartbeat,
                auto_retry=auto_retry,
                raise_exception=True,
                **api_options,
            ),
            timeout=self.timeout,
            max_failovers=max_failovers if failover else 0,
            raise_exception=raise_exception,
            on_switch=lambda endpoint: setattr(self, 'server', endpoint),
        )
        try:
            connected = self.client.connect()
        except (OSError, TdxConnectionError, TdxFunctionCallError) as exc:
            raise TdxhubConnectionError(
                f'无法连接任何可用的扩展行情服务器，已尝试: {healthy_endpoints}: {exc}',
                data={'servers': healthy_endpoints},
            ) from exc
        if not connected:
            raise TdxhubConnectionError(
                f'无法连接任何可用的扩展行情服务器，已尝试: {healthy_endpoints}',
                data={'servers': healthy_endpoints},
            )

    @staticmethod
    def validate(market, symbol):
        """
        验证股票市场

        :param market: 股票市场
        :param symbol: 股票代码
        :return: tuple
        """

        if not market and len(symbol.split('#')) > 1:
            market = symbol.split('#')[0]
            symbol = symbol.split('#')[1]

        if not market:
            raise ValueError('市场参数错误, 市场参数不能为空.')

        return int(market), symbol

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def markets(self, **kwargs):
        """
        获取实时市场列表

        :return: pd.dataFrame or None
        """

        result = self.client.get_markets()
        return to_data(result, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def instrument(self, start=0, offset=800, **kwargs):
        """
        查询代码列表

        :param start:   开始位置
        :param offset:  获取数量
        :return:
        """

        result = self.client.get_instrument_info(start=start, count=offset)
        return to_data(result, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def instrument_count(self):
        """
        市场商品数量

        :return:
        """

        result = self.client.get_instrument_count()

        return result

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def instruments(self, **kwargs):
        """
        查询所有代码列表

        :return:
        """

        result = []

        count = self.client.get_instrument_count()
        pages = math.ceil(count / 100)

        for page in tqdm(range(0, pages), ascii=True):
            result += self.client.get_instrument_info(page * 100, 100)

        return to_data(result, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def quote_list(self, market='', category=0, start=0, offset=80, **kwargs):
        """Query one page of extended-market quotes."""
        if market in (None, ''):
            raise ValueError('市场参数错误, 市场参数不能为空.')
        result = self.client.get_instrument_quote_list(
            market=int(market), category=int(category), start=int(start), count=int(offset)
        )
        return to_data(result, client=self, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def bars_range(self, market='', symbol='', start_date='', end_date='', **kwargs):
        """Query extended-market K-lines in an inclusive protocol date range."""
        market, symbol = self.validate(market, symbol)
        result = self.client.get_history_instrument_bars_range(
            market=market,
            code=symbol,
            start=int(start_date),
            end=int(end_date),
        )
        return to_data(result, symbol=symbol, client=self, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def quote(self, market='', symbol='', **kwargs):
        """
        查询五档行情

        :param market: 市场ID
        :param symbol: 证券代码
        :return:
        """

        market, symbol = self.validate(market, symbol)
        result = self.client.get_instrument_quote(market, symbol)

        return to_data(result, symbol=symbol, client=self, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def minute(self, market='', symbol='', **kwargs):
        """
        查询分时行情

        :param market: 市场ID
        :param symbol: 证券代码
        :return:
        """

        market, symbol = self.validate(market, symbol)
        result = self.client.get_minute_time_data(market, symbol)

        return to_data(result, symbol=symbol, client=self, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def minutes(self, market=None, symbol='', date='', **kwargs):
        """
        查询历史分时行情

        :param market:  市场ID
        :param symbol:  证券代码
        :param date:    查询日期
        :return:
        """

        market, symbol = self.validate(market, symbol)
        result = self.client.get_history_minute_time_data(market, symbol, date)

        return to_data(result, symbol=symbol, client=self, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def bars(self, frequency='', market='', symbol='', start=0, offset=800, **kwargs):
        """
        查询k线数据

        :param frequency: 数据频次, K线周期
        :param market: 市场ID
        :param symbol: 证券代码
        :param start:  起始位置
        :param offset: 获取数量
        :return:
        """

        frequency = get_frequency(frequency)
        market, symbol = self.validate(market, symbol)
        result = self.client.get_instrument_bars(
            category=frequency, market=market, code=symbol, start=start, count=offset
        )

        return to_data(result, symbol=symbol, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def transaction(self, market=None, symbol='', start=0, offset=800, **kwargs):
        """
        查询分笔成交

        :param market: 市场ID
        :param symbol: 证券代码
        :param start:  开始位置
        :param offset: 获取数量
        :return:
        """

        market, symbol = self.validate(market, symbol)
        result = self.client.get_transaction_data(market=market, code=symbol, start=start, count=offset)

        return to_data(result, symbol=symbol, client=self, **kwargs)

    @retry(
        wait=wait_random(min=1, max=10),
        stop=stop_after_attempt(3),
        retry_error_callback=return_last_value,
        retry=(retry_if_exception_type() | retry_if_result(check_empty)),
    )
    def transactions(self, market=None, symbol='', date='', start=0, offset=800, **kwargs):
        """
        查询历史分笔成交

        :param market:  市场ID
        :param symbol:  证券代码
        :param date:    查询日期
        :param start:   开始位置
        :param offset:  获取数量
        :return:
        """

        market, symbol = self.validate(market, symbol)
        result = self.client.get_history_transaction_data(
            market=market, code=symbol, date=int(date), start=start, count=offset
        )

        return to_data(result, symbol=symbol, client=self, **kwargs)
