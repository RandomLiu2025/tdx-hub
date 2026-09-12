# Go tdx 迁移能力使用指南

本页描述当前 Python 实现，不表示与 Go 的全部能力已经对齐。PyPI 发行包名为 `tdxhub-sdk`，
Python 导入路径和 CLI 命令仍为 `tdxhub`，需要 Python 3.11+。
完成状态及待办见 仓库根目录的 `IMPLEMENTATION_PLAN.md`；
口径与架构见 [迁移设计](../design/202609101744-port-go-data-capabilities.md)。

## 1. GBBQ 与统一复权

```python
from tdxhub.gbbq import adjust_prices, adjustment_factors, get_equity_snapshot, normalize_gbbq

# raw_actions 为单只证券的 GBBQ/XDXR DataFrame；prices 为价格 DataFrame。
actions = normalize_gbbq(raw_actions)
qfq = adjust_prices(prices, actions, method="qfq")
hfq = adjust_prices(prices, actions, method="hfq")
factors = adjustment_factors(prices.index, actions)
snapshot = get_equity_snapshot(actions, at="2026-09-10")
if snapshot is not None:
    turnover_percent = snapshot.turnover(volume_shares=100_000)
```

- 输入使用 `DatetimeIndex`、`date` 列或 `year/month/day` 列。批量 GBBQ 需先按证券筛选；
  `get_equity_snapshot` 另支持 `code=` 筛选。
- 仿射因子列为 `qfq_mul/qfq_add/hfq_mul/hfq_add`；只让 `category=1` 参与价格复权。
- 同日事件保留稳定顺序；支持停牌期间事件，忽略晚于最新 K 线的事件。
- 价格以元为单位，按 `ROUND_HALF_UP` 保留两位小数；这也适用于原始精度高于两位的品种，
  不宜将复权结果用于需要原始报价精度的债券/衍生品撮合。
- `volume/amount` 不因复权改变；股本快照输入/输出口径均为股，换手率返回百分数。
  不会自动把上游“万股”或“手”转换为股。
- 保留 `qfq/01/before`、`hfq/02/after` 别名；既有 `reversion()` 复用同一实现。

离线复权要显式传入事件，避免默认 XDXR 下载：

```python
from tdxhub.reader import Reader

reader = Reader.factory(market="std", tdxdir=r"D:\new_tdx")
bars = reader.daily("sh600000", adjust="qfq", xdxr=actions)
```

### 日 K 历史换手率

换手率是可选字段，默认不会改变既有日 K 列结构。本地 Reader 必须显式传入股本事件：

```python
local = reader.daily("sh600000", turnover=True, xdxr=actions)
# 也可使用 gbbq=actions；退市日线 delisted_daily() 规则相同。
```

在线 Quotes 未收到显式事件时会自动获取一次 XDXR；全量接口在分页合并后统一计算：

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market="std", timeout=5)
try:
    online = client.bars_all("sh600000", frequency=9, turnover=True)
finally:
    client.close()
```

- `turnover` 是百分数，`2.35` 表示 `2.35%`。
- 标准股票日 K 的 `volume` 按手处理，先乘 `100` 转成股，再除以当日或之前最新的
  流通股本。在线 `StdQuotes.xdxr()` 的原始 `panhouliutong` 单位是“万股”，客户端会
  通过 DataFrame 元数据识别并自动乘 `10,000`；手工传入且未标记的数据仍按“股”处理。
- 没有有效历史流通股本时返回 `NaN`；股本有效且零成交量时返回 `0.0`。
- 价格复权不改变换手率。指数和分钟 K 线不计算；股票非日频显式开启会报参数错误。
- 详见[股票日 K 历史换手率设计](../design/202609111042-daily-turnover-rate.md)。

## 2. 官方文件、北交所与退市缓存

```python
from tdxhub.official import associate_industries, parse_official
from tdxhub.reader import Reader

# 文件路径可按文件名推断类型；bytes 输入必须提供 kind。
bse = parse_official(r"D:\new_tdx\T0002\hq_cache\tdxbjmore.cfg")
# stats = parse_official(raw_bytes, kind="tdxstat")

reader = Reader.factory(market="std", tdxdir=r"D:\new_tdx")
bse = reader.beijing_stocks()
industries = reader.stock_industries()
delisted = reader.delisted_daily("sz000003")

# 也可关联已解析或自行构造的 DataFrame。
assignments = reader.official("tdxhy.cfg")
dictionary = reader.official("incon.dat")
industries = associate_industries(assignments, dictionary)
```

没有本地通达信目录时，可从标准行情服务器读取同类配置：

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    industries = client.stock_industries(["sh600519", "sz000001"])
    # 默认复用进程全局和磁盘缓存；需要服务器最新文件时显式刷新。
    refreshed = client.stock_industries(refresh=True)
```

支持 `spblock`、`tdxzs`、`tdxbk`、`tdxhy`、`tdxbjmore`、`incon`、`hspy`、
`tdxstat`、`tdxstat2`，返回 DataFrame。可直接调用同名的 `parse_*` 函数。

- `stock_block_index(statistics)` 提供证券到板块索引的映射；`stock_industries()` 则关联
  `tdxhy.cfg` 与 `incon.dat`，增加 `tdx_industry_name/source` 和
  `sw_industry_name/source`，并通过 `sw_level1/2/3_code/name` 展开申万一、二、三级行业。
  关联优先使用完整代码；旧版申万 `X...` 代码仅在精确匹配失败时去掉 `X` 并限定到
  `SWHY` 分区查找，父级名称也只在命中的申万分区内解析，避免跨字典同码误配。
- 行业关联不会修改输入 DataFrame，也不会丢弃未命中行；原代码保留，并在结果 attrs 的
  `industry_dictionary_source` 与 `unresolved_industry_codes` 中记录字典来源和未解析代码。
- 在线 `StdQuotes.stock_industries()` 直接下载 `tdxhy.cfg`，并从 `zhb.zip` 提取
  `incon.dat`；支持全量、单只和批量过滤，结果跨实例共享并持久化。该数据是服务器发布的配置，
  不是逐笔实时行情。
- 北交所目录来自客户端 `tdxbjmore.cfg`；在线 `client.stocks(market=2)` 从
  `zhb.zip` 中读取该目录，并非行情主站的实时证券数量口径。
- `delisted_daily()` 读取本地 `ds_cache/*.~~~day`，结果 attrs 中包含
  `source="local_delisted"`。`daily()` 在正常日线不存在时尝试退市缓存。
- Reader 接受安装根目录或 `vipdoc` 目录；官方文件仍需存在于关联安装目录中。

## 3. 在线行情扩展

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market="std", timeout=5)
try:
    bars = client.bars_all("sh600000", frequency=9, since="20260101")
    # 全量分页先合并，再统一复权，不按各页分别确定锚点。
    qfq = client.bars_all("sh600000", frequency=9, adjust="qfq", xdxr=actions)
    index = client.index_all("sh000001", frequency=9, since="20260101")
    auction = client.call_auction("sh600000")
    stats = client.statistics()
    flows = client.money_flow()
finally:
    client.close()
```

- `since` 使用 `YYYYMMDD`；“全量”指主站可返回且受协议分页范围约束的数据，不保证上市以来完整历史。
- 另支持 `stock_list()`、`transaction_all()`、`transactions_all()`、`company_content()`。
- 集合竞价时间使用 `Asia/Shanghai`；未给日期时使用上海当天，显式日期只为响应补日期，
  不会让协议变成历史集合竞价查询。未知字段不臆造含义。
- 扩展市场客户端增加 `quote_list(market=..., category=..., start=..., offset=...)`
  和 `bars_range(market=..., symbol=..., start_date=YYYYMMDD, end_date=YYYYMMDD)`；
  后者保留底层协议的闭区间日期语义，不等同于 Pull 的半开区间。
- 目前以 fixture/mock 覆盖新增协议和包装层；真实主站、Go/Python 实盘结果对账尚未完成。
  新股专用接口尚未迁移，扩展市场各品种的单位/交易时区仍需逐一核验。

## 4. 增量拉取与 SQLite

```python
from tdxhub.pull import PullService, QuoteFetcher, SQLiteStore
from tdxhub.quotes import Quotes

client = Quotes.factory(market="std", timeout=5)
try:
    # 本例假设已确认源成交量以股计；若源为手，明确传 source_volume_unit="lots"。
    fetcher = QuoteFetcher(client, timezone="Asia/Shanghai", source_volume_unit="shares")
    with SQLiteStore("market.sqlite3") as store:
        service = PullService(store, fetcher)
        bars = service.sync(
            market=1, code="600000", frequency=9,
            start="2026-09-01", end="2026-09-11",
            adjustment="none", overlap="1D",
        )
finally:
    client.close()
```

标准市场 `0/sz`、`1/sh`、`2/bj` 明确决定代码前缀；前缀冲突会在 I/O 前报错。
持久化 identity 会保留传入字符串形式，因此同一数据流应固定使用数值或字符串，避免混用。
扩展市场需使用 `ExtQuotes`（或 `QuoteFetcher(..., extended=True)`）与对应市场 ID。

### 存储契约

- 主键：`market + code + frequency + datetime + adjustment`。
- 保存 `source/volume_unit/timezone/is_approximate`；`QuoteFetcher` 将股/手显式归一到股。
  期货等以合约计量的品种不能未经验证套用该转换。
- `sync()` 使用 `[start, end)`；无时区输入按 `timezone` 本地化。
- 同次同步先拉取、校验全部缺口，再将行和覆盖范围写入一个 SQLite 事务；
  拉取/校验失败不留下部分数据，事务失败同时回滚行和覆盖标记。
- 重复时间戳幂等 upsert；尾部部分响应只更新返回的行，不删除未返回的旧行。
- 非空成功响应会把**请求区间**标记为覆盖；这不是“逐交易日无缺口”的证明。
  空响应不标记覆盖。节假日、停牌、主站历史截断和内部缺点需要额外校验。
- `overlap` 控制已存尾部重拉；当前 `PullService` 仅支持 `adjustment="none"`，
  对 qfq/hfq 显式报错。尚未实现除权事件变化时的历史复权分区失效/重算。

`day_to_calendar()` 支持日线聚合为周/月/季/年线；`minute_to_sessions()` 根据调用方提供的
`TradingSession` 聚合分钟线，不跨午休/夜盘边界。它们不是官方节假日交易日历。
`fallback_fetcher` 接收的是已规范化 bar 数据，并给近似来源打标；尚不包含逐笔→分钟合成引擎。

## 5. 可选 HTTP 服务

核心包不强制依赖 FastAPI。HTTP 层通过 `MarketDataService` 注入客户端：

```python
# 保存为 serve_tdxhub.py；工厂启动时初始化行情连接，关闭时释放。
from contextlib import asynccontextmanager

from tdxhub.http import MarketDataService, create_app
from tdxhub.quotes import Quotes


def make_app():
    service = MarketDataService(standard_quotes=None)
    app = create_app(service)

    @asynccontextmanager
    async def lifespan(_app):
        client = Quotes.factory(market="std", timeout=5)
        service.standard_quotes = client
        try:
            yield
        finally:
            service.standard_quotes = None
            client.close()

    app.router.lifespan_context = lifespan
    return app
```

从源码目录启动（以下命令会连接真实行情服务器）：

```sh
uv run --python 3.11 --extra server uvicorn serve_tdxhub:make_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

常用 GET 路径：

| 路径 | 参数示例 / 用途 |
|---|---|
| `/`、`/ready` | 存活、客户端已配置；`ready` 不主动验证主站连接 |
| `/count`、`/code/all`、`/code` | `exchange=sh`；分页目录增加 `start=0` |
| `/quote` | `codes=sh600000,sz000001` |
| `/stock/info` | `codes=sh600519,sz000001`; 聚合证券信息，内部默认 4 路并行 |
| `/kline`、`/kline/all` | `code=sh600000&category=9`；全量可加 `since=20260101&adjust=qfq` |
| `/index`、`/index/all` | 指数 K 线 |
| `/call_auction`、`/gbbq` | `code=sh600000` |
| `/finance` | `exchange=sh&code=600000` |
| `/tdx/stat`、`/tdx/stat2` | 统计、资金流 |
| `/ex/*` | 扩展行情，须注入 `extended_quotes`；具体参数见 `/docs` |

还有周期别名、逐笔、分时及公司资料路径，完整请求参数见 `/docs` 与 `/openapi.json`。
当前请求参数有校验，响应仍为通用 JSON envelope，尚无逐接口完整强类型响应模型。
`pull_service` 为预留注入项，没有 HTTP Pull 路由。

### JSON 与错误契约

成功返回 `{"code": 0, "msg": "ok", "data": ...}`，错误返回
`{"code": 1, "msg": "...", "data": null}`。

- 参数/校验错误 HTTP 400；资源缺失或扩展行情未启用 HTTP 404；未配置标准客户端 `/ready` 返回 503。
- 其他调用异常保留 Go 兼容口径：HTTP 200、`code=1`。客户端必须同时检查 HTTP 状态与业务码。
- DataFrame 转为记录数组；DatetimeIndex 是权威时间字段（无名时使用 `datetime`），
  覆盖同名原始时间字符串，但不修改原 DataFrame。
- 时间输出带偏移 RFC3339；无时区 datetime 以 `Asia/Shanghai` 解释，有时区值保留偏移；
  普通字符串不会被盲目解析。NaN/NaT/无穷值转 null，bytes 转 Base64。

### 部署边界

上述是本地开发样例，不是生产部署方案：未内置认证、限流或通用请求级并发隔离。
`/stock/info` 的聚合子请求使用实例内有界连接池，但其他同步端点仍共享主客户端；
单 worker 也可能同时处理多个 HTTP 请求。部署方仍需限制请求并发，
并设置请求量/分页上限、超时和访问控制。不要直接绑定公网；不要将原始异常信息暴露给不可信用户。
