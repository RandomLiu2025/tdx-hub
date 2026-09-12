# tdxhub

`tdxhub` 是面向 Python 3.11+ 的通达信市场数据工具包。它将本地 VIPDOC 文件、标准/扩展在线行情、官方配置与财务文件、复权与换手率、增量拉取和可选 HTTP 服务统一到一套 Python API 中。

> 项目只提供数据读取、解析与本地存储能力，不包含交易下单功能。

## 功能概览

| 能力 | 主要入口 | 说明 |
|---|---|---|
| 本地行情 | `tdxhub.reader.Reader` | 日线、1 分钟、5 分钟、扩展市场、退市缓存、板块与官方配置 |
| 在线行情 | `tdxhub.quotes.Quotes` | 快照、分页/全量 K 线、指数、分时、逐笔、集合竞价、公司资料、财务与扩展行情 |
| 复权与换手率 | `tdxhub.gbbq` | GBBQ/XDXR 规范化、前复权、后复权、历史股本快照和日 K 换手率 |
| 官方文件 | `tdxhub.official` | 板块、指数、行业、北交所目录、统计、资金流和新股申购配置解析 |
| 专业财务 | `tdxhub.affair.Affair` | 财务压缩包清单、下载、校验和解析 |
| 增量同步 | `tdxhub.pull` | 缺口规划、分页抓取、逐笔合成分钟线、SQLite 幂等持久化 |
| HTTP API | `tdxhub.http` | 可选 FastAPI 服务，提供行情、K 线、指数、逐笔、财务和扩展行情路由 |
| CLI | `tdxhub` | 本地读取、在线行情、线路探测、财务文件和批量导出 |

## 安装

PyPI 发行包名为 `tdxhub-sdk`；安装后仍使用 `import tdxhub`，命令行入口仍为 `tdxhub`。

```bash
python -m pip install -U tdxhub-sdk
```

按需安装可选能力：

```bash
# 节假日解析
python -m pip install -U "tdxhub-sdk[holiday]"

# FastAPI HTTP 服务
python -m pip install -U "tdxhub-sdk[server]"

# 安装全部可选依赖
python -m pip install -U "tdxhub-sdk[all]"
```

源码开发：

```bash
git clone https://github.com/RandomLiu2025/tdx-hub.git
cd tdx-hub
uv sync --extra server --extra test
```

## 快速开始

### 读取本地 VIPDOC

`tdxdir` 可以是通达信安装根目录，也可以直接指向 `vipdoc`。证券代码支持 `600000`、`SH600000`、`SH.600000` 等形式，并识别沪、深、北市场。

```python
from tdxhub.reader import Reader

reader = Reader.factory("std", tdxdir=r"D:\new_tdx")

daily = reader.daily("SH.600000")
minute = reader.minute("600000")
five_minute = reader.fzline("600000")

print(daily.tail())
```

其他本地能力：

```python
# 退市证券 ds_cache/*.~~~day；普通 daily 缺文件时也会尝试该缓存
retired = reader.delisted_daily("sz000003")

# 传统板块文件和官方配置
concepts = reader.block("block_gn.dat")
beijing = reader.beijing_stocks()
industries = reader.stock_industries()
statistics = reader.official("tdxstat.cfg")
```

扩展市场本地文件使用独立 reader：

```python
ext_reader = Reader.factory("ext", tdxdir=r"D:\new_tdx")
future_daily = ext_reader.daily("4#CF7D0LAO")
```

### 读取在线行情

`Quotes` 是标准市场和扩展市场的统一工厂。建议使用上下文管理器及时关闭连接：

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    snapshot = client.quotes(["sh600000", "sz000001"])
    daily = client.bars("sh600000", frequency=9, offset=100)
    all_daily = client.bars_all("sh600000", frequency=9, since="20250101")
    all_index = client.index_all("000001", frequency=9, since="20250101")
    auction = client.call_auction("sh600000")
    minute = client.minute("sz300394")  # datetime 列/索引：09:31～11:30、13:01～15:00
    minute_241 = client.minute_241("sh600000")  # 最新交易日，收盘后最多 241 条
    minute_history = client.minute_241("sh600000", since="20250901")  # 日期范围
    trades = client.transaction_all("sh600000")
    history_trades = client.transactions_all("sh600000", date="20250910")

    # 证券目录可按 A/B 股、指数、ETF、其他基金、债券或未识别品种筛选
    etfs = client.stocks(market=1, security_type="etf")

    # 在线下载通达信/申万行业配置；申万结果同时展开一、二、三级行业
    industries = client.stock_industries(["sh600519", "sz000001"])

    # 聚合目录、快照、行业、财务、除权与集合竞价；默认 4 路并行并复用连接
    stock_summary = client.stock_info(["sh600519", "sz000001"])
    index_count = client.stock_count(market=1, security_type="index")
    a_stocks = client.stock_all(security_type="a_stock")
```

`stock_count()` 和 `stocks()` 不传 `security_type` 时保持完整证券目录口径。可选值为
`a_stock`、`b_stock`、`index`、`etf`、`fund`、`bond` 和 `other`；其中 `fund`
不包含 ETF。完整市场目录在进程内全局共享并持久化到 `~/.tdxhub/caches/quotes`，默认每 6 小时
按需更新；`stocks(..., refresh=True)` 可强制刷新。带筛选条件的 `stock_count()` 复用完整目录。

`stock_info()` 固定返回 37 列 DataFrame，保留输入顺序和重复代码，不包含证券目录、行情和
财务接口的原始字典。沪深证券的财务、XDXR、
集合竞价通过实例内有界连接池并行获取，默认 `max_workers=4`；市场目录和行业配置跨客户端共享
并持久化，默认分别每 6 小时和 24 小时按需更新，可用 `refresh_directories=True`、
`refresh_industries=True` 显式刷新。自动更新失败时会临时使用磁盘旧值，显式刷新失败仍抛错。

常用 K 线频率：`8` 1 分钟、`0` 5 分钟、`1` 15 分钟、`2` 30 分钟、`3` 60 分钟、`9` 日线、`5` 周线、`6` 月线。

`stock_industries()` 保留 `sw_industry_code/name/source`，并额外返回
`sw_level1_code/name`、`sw_level2_code/name` 和 `sw_level3_code/name`。新旧申万编码均在
命中的字典分区内展开，避免相同数字代码跨分区误配。

扩展市场接口：

```python
with Quotes.factory("ext", timeout=5) as client:
    markets = client.markets()
    instruments = client.instruments()
    bars = client.bars(market=47, symbol="IFL0", frequency=9, offset=100)
```

在线能力依赖可用的通达信行情节点及 `tdxpy` 协议实现。节点临时不可用、协议变化或数据源历史深度限制都可能影响结果。

标准行情和扩展行情默认启用**单活动连接容灾**：构造时最多保留 5 个健康候选节点；当前
节点在 `auto_retry` 重连后仍发生网络或协议错误时，单次请求最多切换 2 次，故障节点冷却
60 秒。不会因合法空结果或参数错误切换节点。

```python
with Quotes.factory(
    "std",
    timeout=5,
    failover=True,
    max_failovers=2,
    unhealthy_cooldown=60,
    max_candidates=5,
) as client:
    data = client.quotes("sh600000")
    print(client.server)          # 当前活动节点
    print(client.server_status()) # 所有候选节点的健康状态
```

传入 `server=(ip, port)` 时默认只连接指定节点；如需失败后回退公共节点，显式设置
`fallback_servers=True`。设置 `failover=False` 可关闭跨节点切换，但不影响 `auto_retry`
对当前节点的重连。

加载 `~/.tdxhub/config.json` 时，持久化的 `SERVER.HQ` / `SERVER.EX` 顺序会优先保留，
并按 IP + 端口自动补入新版本内置但本地配置中缺失的节点。升级后无需删除旧配置文件，
也不会因旧配置快照而遗漏新节点。

## 复权、GBBQ 与历史换手率

全量日 K 可在分页合并后统一前复权/后复权，并按历史流通股本计算换手率：

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    qfq = client.bars_all(
        "sh600000",
        frequency=9,
        since="20200101",
        adjust="qfq",
        turnover=True,
    )
```

本地读取不会隐式联网。复权或换手率需要显式提供 GBBQ/XDXR 事件：

```python
from tdxhub.reader import Reader

reader = Reader.factory("std", tdxdir=r"D:\new_tdx")
bars = reader.daily(
    "sh600000",
    adjust="hfq",
    turnover=True,
    xdxr=actions,  # pandas.DataFrame
)
```

在线 `xdxr()` 的原始流通股本字段以“万股”为单位，tdxhub 会在计算换手率时自动转换为
“股”；手工传入且没有单位标记的 `xdxr`/`gbbq` DataFrame 继续按“股”处理。返回的
`turnover` 是百分数，例如 `0.2784` 表示约 `0.2784%`。

底层函数可直接使用：

```python
from tdxhub.gbbq import adjust_prices, get_equity_snapshot, normalize_gbbq

events = normalize_gbbq(actions)
adjusted = adjust_prices(prices, events, method="qfq")
snapshot = get_equity_snapshot(events, at="2026-09-10")
```

价格复权不修改成交量和成交额；换手率返回百分数。完整数据口径见 [迁移能力使用指南](docs/api/migration.md)。

## 官方文件与财务数据

### 官方配置解析

```python
from tdxhub.official import associate_industries, parse_official

blocks = parse_official(r"D:\new_tdx\T0002\hq_cache\spblock.dat")
beijing = parse_official(r"D:\new_tdx\T0002\hq_cache\tdxbjmore.cfg")

assignments = parse_official(r"D:\new_tdx\T0002\hq_cache\tdxhy.cfg")
dictionary = parse_official(r"D:\new_tdx\T0002\hq_cache\incon.dat")
industries = associate_industries(assignments, dictionary)
```

不安装通达信客户端时，也可通过标准行情连接在线获取服务器发布的行业配置：

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    one = client.stock_industries("sh600519")
    selected = client.stock_industries(["sz000001", "sh600519"])
    latest = client.stock_industries(refresh=True)
```

在线接口直接下载 `tdxhy.cfg`，并从 `zhb.zip` 读取 `incon.dat` 后完成关联。结果在当前
进程内全局共享并持久化到 `~/.tdxhub/caches/quotes`，默认 24 小时按需更新；
`refresh=True` 强制刷新。它属于服务器发布的配置数据，不是
逐笔实时行情，更新时点取决于服务器文件版本。

支持的主要文件包括：

- `spblock.dat`
- `tdxzs.cfg`、`tdxzs3.cfg`、`tdxdszs.cfg`
- `tdxbk.cfg`、`tdxhy.cfg`、`incon.dat`、`hspy.dat`
- `tdxstat.cfg`、`tdxstat2.cfg`
- `tdxbjmore.cfg`、`xgsg.cfg`

### 专业财务文件

```python
from tdxhub.affair import Affair

manifest = Affair.files()
archive = Affair.fetch(downdir="output", filename="gpcw19960630.zip")
frame = Affair.parse(downdir="output", filename="gpcw19960630.zip")
```

不传 `filename` 时，`Affair.fetch()` 会并发下载清单中的全部文件，并对已有文件执行 MD5 校验。

## 增量拉取与 SQLite

`tdxhub.pull` 使用半开区间 `[start, end)`，按已记录 coverage 计算缺口，并将数据行与 coverage 在同一 SQLite 事务中写入。重复同步采用幂等 upsert。

```python
from tdxhub.pull import PullService, QuoteFetcher, SQLiteStore
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client, SQLiteStore("market.db") as store:
    fetcher = QuoteFetcher(client, source_volume_unit="lots")
    service = PullService(store, fetcher)
    bars = service.sync(
        market="sh",
        code="600000",
        frequency=9,
        start="2026-09-01",
        end="2026-09-11",
        adjustment="none",
        overlap="1D",
    )
```

分钟数据可使用逐笔 fallback：

```python
from tdxhub.pull import PullService, QuoteFetcher, TradeMinuteFetcher

service = PullService(
    store,
    QuoteFetcher(client, source_volume_unit="lots"),
    fallback_fetcher=TradeMinuteFetcher(client),
)
```

当前限制：

- 增量同步仅支持 `adjustment="none"`，不接受 qfq/hfq 分区。
- coverage 表示请求区间已成功返回并写入，不等同于官方交易日历完整性证明。
- 标准市场成交量可从“手”归一为“股”；期货等扩展品种的单位需要调用方核验。
- `TradeMinuteFetcher` 仅支持沪深标准市场 1 分钟线。

## HTTP API

安装 `tdxhub[server]` 后，可通过依赖注入创建 FastAPI 应用：

```python
# serve_tdxhub.py
from contextlib import asynccontextmanager

from tdxhub.http import MarketDataService, create_app
from tdxhub.quotes import Quotes


def make_app():
    service = MarketDataService(standard_quotes=None)
    app = create_app(service)

    @asynccontextmanager
    async def lifespan(_app):
        client = Quotes.factory("std", timeout=5)
        service.standard_quotes = client
        try:
            yield
        finally:
            service.standard_quotes = None
            client.close()

    app.router.lifespan_context = lifespan
    return app
```

启动：

```bash
uvicorn serve_tdxhub:make_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

OpenAPI 页面位于 <http://127.0.0.1:8000/docs>。主要 GET 路由包括：

- 健康检查：`/`、`/ready`
- 证券目录和快照：`/count`、`/code`、`/code/all`、`/quote`
- K 线和指数：`/kline/*`、`/index/*`、`/kline/minute/241`
- 盘中数据：`/minute`、`/trade/*`、`/call_auction`
- 公司与财务：`/stock/info`、`/gbbq`、`/finance`、`/company/*`、`/tdx/*`
- 扩展行情：`/ex/*`（需注入 `extended_quotes`）

成功响应为 `{"code": 0, "msg": "ok", "data": ...}`。当前 HTTP 层未内置认证、限流和通用请求并发隔离；仅 `/stock/info` 内部使用有界连接池，不应直接暴露到公网。

## 命令行

```bash
tdxhub --help
tdxhub --version

tdxhub reader --tdxdir D:\new_tdx --symbol 600000 --action daily
tdxhub quotes --symbol 600000 --action daily
tdxhub bestip --limit 5
tdxhub affair --listfile
tdxhub bundle --symbol 600000,000001 --action daily
```

各命令可通过 `tdxhub <command> --help` 查看完整参数。

## 测试与开发

默认测试排除真实网络和本地集成用例：

```bash
uv run pytest -q
```

使用真实通达信目录运行 VIPDOC 集成测试：

```bash
TDXHUB_TDXDIR=/mnt/d/new_tdx_mock uv run pytest -q -m integration tests/integration/test_vipdoc.py
```

Windows PowerShell：

```powershell
$env:TDXHUB_TDXDIR = "D:\new_tdx_mock"
uv run pytest -q -m integration tests\integration\test_vipdoc.py
```

也可以通过 Makefile 传入同名变量：

```bash
make test-vipdoc TDXHUB_TDXDIR=/mnt/d/new_tdx_mock
```

其他常用命令：

```bash
uv run ruff check tdxhub tests
uv run python -m compileall -q tdxhub tests
uv build
```

## 数据口径与使用限制

- 默认时区为 `Asia/Shanghai`；不同接口的时间字段和历史深度取决于上游数据源。
- 在线标准行情支持沪深京代码识别，但某些底层接口本身只覆盖沪深市场。
- 北交所本地目录来自 `tdxbjmore.cfg`；在线目录可能来自客户端配置包，不代表实时主站证券计数。
- 复权依赖正确的 GBBQ/XDXR 事件；债券、期货和衍生品的价格精度、成交量单位需单独核验。
- 请遵守通达信及相关数据源的服务条款。项目仅供学习、研究和个人数据处理使用。

## 文档

- [迁移能力使用指南](docs/api/migration.md)
- [架构与迁移设计](docs/design/202609101744-port-go-data-capabilities.md)
- [实施计划](IMPLEMENTATION_PLAN.md)

## License

[MIT License](LICENSE)
