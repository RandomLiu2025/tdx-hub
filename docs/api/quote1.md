# 标准行情接口

下面是如何在程序里面调用本接口

**参数说明:**

- market: 对应市场。 (std 标准股票市场，ext 扩展市场)

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
```

### 其他参数

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(
    market='std',
    multithread=True,
    heartbeat=True,
    bestip=False,
    timeout=15,
    failover=True,
    max_failovers=2,
    unhealthy_cooldown=60,
    max_candidates=5,
)
# multithread 启用 tdxpy 客户端锁
# heartbeat 开启心跳包
# bestip 重新测试最快服务器
# server 自行设置服务器 IP，例如 server=('127.0.0.1', 7709)
# timeout 连接与请求超时时间
# failover 请求失败后是否切换服务器，默认 True
# max_failovers 单次请求最多切换的服务器数量，默认 2
# unhealthy_cooldown 故障服务器冷却秒数，默认 60
# max_candidates 构造时最多保留的健康候选服务器数，默认 5
```

默认按 `BESTIP.HQ`、配置服务器的顺序探测，运行时仅保持一个活动连接。网络、连接或
TDX 协议调用失败时，会先由 `auto_retry` 重连当前节点；仍失败后再切换候选节点并重放
当前只读请求。空结果和参数校验错误不会触发切换。

显式传入 `server` 时默认只使用该节点。如需指定节点失败后回退到公共节点，请设置
`fallback_servers=True`：

```python
client = Quotes.factory(
    'std',
    server=('127.0.0.1', 7709),
    fallback_servers=True,
)

# 查看活动节点、连续失败数、冷却剩余时间和最近错误
print(client.server_status())
```

`raise_exception=False`（默认）会在全部尝试失败后返回空结果；设置为 `True` 时抛出最后
一个底层连接/协议异常。构造阶段所有候选节点均不可用时始终抛出
`TdxhubConnectionError`。

## 01. 查询实时行情

可以获取**多**只股票的行情信息

**参数说明: **

- symbol: 多个股票号码。 `["000001", "600300"]` 格式

返回值：

- `pd.DataFrame`
- 常用字段包括 `market`、`code`、`price`、`last_close`、`open`、`high`、`low`、
  `servertime`、`vol`、`volume`、`cur_vol`、`amount`、`s_vol`、`b_vol`，以及五档
  `bid` / `ask` 价格和数量字段。实际字段可能随行情服务器和证券状态有所差异。
- `active1`、`active2` 和所有 `reversed_bytes*` 字段属于底层协议保留字段，不作为
  稳定业务数据返回。

**调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.quotes(symbol=["000001", "600300"])
```

## 02. 获取k线数据

**调用方法：**

> frequency -> K线种类
> 0 => 5分钟K线             => 5m
> 1 => 15分钟K线            => 15m
> 2 => 30分钟K线            => 30m
> 3 => 小时K线              => 1h
> 4 => 日K线 (小数点x100)    => days
> 5 => 周K线                => week
> 6 => 月K线                => mon
> 7 => 1分钟K线(好像一样)     => 1m
> 8 => 1分钟K线(好像一样)     => 1m
> 9 => 日K线                => day
> 10 => 季K线               => 3mon
> 11 => 年K线               => year

如

**调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.bars(symbol='600036', frequency=9, offset=10)

# 前复权
client.bars(symbol='600036', adjust='qfq')

# 后复权
client.bars(symbol='600036', adjust='hfq')
```

## 03. 查询证券数量

**参数说明：**

- `market`：市场代码，`0` - 深圳、`1` - 上海、`2` - 北京；沪深市场也可使用
  `MARKET_SZ`、`MARKET_SH` 常量。
- `security_type`：可选证券类型。支持 `a_stock`、`b_stock`、`index`、`etf`、
  `fund`、`bond`、`other`；`None` 表示不筛选。

不传 `security_type` 时直接使用行情服务器的快速计数。指定类型时需要拉取完整市场目录后过滤，
因此速度慢于不筛选的计数。

**调用方法：**

```python
from tdxhub import consts
from tdxhub.quotes import Quotes

client = Quotes.factory(market="std")
all_security_count = client.stock_count(market=consts.MARKET_SH)
etf_count = client.stock_count(market=consts.MARKET_SH, security_type="etf")
```

## 04. 查询证券列表

**参数说明：**

- `market`：市场代码，含义同 `stock_count()`。
- `security_type`：可选证券类型，含义同 `stock_count()`。参数忽略大小写和首尾空格。

结果保持行情目录原有列和顺序，不额外增加分类列；筛选后的行索引从 `0` 重新开始。
`fund` 只返回 ETF 以外的基金。

**调用方法：**

```python
from tdxhub import consts
from tdxhub.quotes import Quotes

client = Quotes.factory(market="std")
all_symbols = client.stocks(market=consts.MARKET_SH)
indexes = client.stocks(market=consts.MARKET_SH, security_type="index")
etfs = client.stocks(market=consts.MARKET_SH, security_type="etf")
latest = client.stocks(market=consts.MARKET_SH, refresh=True)
a_stocks = client.stock_all(security_type="a_stock")  # 合并深、沪、北三个市场
```

## 05. 指数K线行情

** 参数说明: **

- frequency: K线种类
- market: 市场代码. 0 - 深圳, 1 - 上海 (可以使用常量 `MARKET_SZ`, `MARKET_SH` 代替)
- start: 开始位置
- offset: 用户要请求的 K 线数目，最大值为 800

> frequency -> K线种类
> 0 => 5分钟K线             => 5m
> 1 => 15分钟K线            => 15m
> 2 => 30分钟K线            => 30m
> 3 => 小时K线              => 1h
> 4 => 日K线 (小数点x100)    => days
> 5 => 周K线                => week
> 6 => 月K线                => mon
> 7 => 1分钟K线(好像一样)     => 1m
> 8 => 1分钟K线(好像一样)     => 1m
> 9 => 日K线                => day
> 10 => 季K线               => 3mon
> 11 => 年K线               => year

使用说明：

** 调用方法：**

```python
from tdxhub.quotes import Quotes
from tdxhub.consts import MARKET_SH

client = Quotes.factory(market='std')
client.index(frequency=9, market=MARKET_SH, symbol='000001', start=1, offset=2)
```

## 06. 查询分时行情

> 此接口复用历史分时协议查询当日数据。协议不携带时间字段，tdxhub 会按 A 股交易时段补齐 `datetime` 列和同名 `DatetimeIndex`。

** 参数说明: **

- symbol: 股票代码

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.minute(symbol='000001')
```

标准 240 个点依次对应 `09:31～11:30` 和 `13:01～15:00`；盘中不足 240 条时从 `09:31` 起顺序映射。`09:30` 集合竞价数据请使用 `minute_241()`。

```python
# 默认仅返回行情节点中的最新交易日；收盘后最多 241 条，盘中少于 241 条
latest = client.minute_241(symbol="600519")

# 显式传入 since 时返回起始日期以来的多个交易日，每个完整交易日最多 241 条
history = client.minute_241(symbol="600519", since="20260901")
```

`minute_241()` 会为每个返回的交易日单独构造 `09:30` 集合竞价柱。方法名中的
“241”表示单个完整交易日的分钟点数量，不表示日期范围查询的结果总行数固定为 241。

## 07. 历史分时行情

** 参数说明: **

- market: 市场代码.
- symbol: 股票代码
- date: 时间

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.minutes(symbol='000001', date='20171010')
```

历史结果同样包含指定日期的 `datetime` 列和同名 `DatetimeIndex`。

注意，在引入 consts 之后， （`from tdxhub import consts`） 我们可以使用 consts.MARKET_SH , consts.MARKET_SZ 常量来代替 1 和 0 作为参数

## 08. 查询分笔成交

** 参数说明: **

- market: 市场代码.
- start: 起始位置
- offset: 数量

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.transaction(symbol='600036', start=0, offset=10)
```

## 09. 查询历史分笔

** 参数说明: **

- symbol: 股票代码.
- start: 起始位置.
- offset: 数量.
- date: 日期.

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.transactions(symbol='000001', start=0, offset=10, date='20170209')
```

## 10. 公司信息目录

** 参数说明: **
市场代码， 股票代码， 如： 0,000001 或 1,600300

** 参数说明: **

- symbol: 股票代码.

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.F10C(symbol='000001')
```

## 11. 公司信息详情

`F10()` 将公司信息目录和正文统一为固定列 `pandas.DataFrame`，不再根据参数返回字符串、
字典或 `None`。

**参数说明：**

- `symbol`：股票代码。
- `name`：可选的公司详情标题，可使用 `F10C()` 查看；标题按去除首尾空白后的值精确匹配。

**调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
all_sections = client.F10(symbol='000001')
latest = client.F10(symbol='000001', name='最新提示')
```

固定列为 `full_code`、`exchange`、`market_id`、`code`、`section`、`filename`、
`start`、`length`、`content`。不传 `name` 时按服务端目录顺序返回全部栏目；指定标题时返回
零行或一行。目录为空或标题不存在时返回具有相同列的空 DataFrame，不会退化为读取全部栏目。

`content` 会统一换行为 `LF`、移除行尾空白与正文首尾空行，并将多个连续空行压缩为一个；
行首缩进和字符表格保持不变。若需要未经整理的目录或原始区间正文，请分别使用 `F10C()` 和
`company_content()`。

## 12. 除权除息信息

**参数说明: **

- symbol: 股票代码.

** 调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.xdxr(symbol='600036')
```

## 13. 读取财务信息

**参数说明: **

- symbol: 股票代码.

**调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.finance(symbol="600300")
```

## 14. 读取 OHLC k线信息

**参数说明: **

- symbol: 股票代码.
- begin: 开始时间.
- end: 结束时间.
- adjust: 复权.

**调用方法：**

```python
from tdxhub.quotes import Quotes

client = Quotes.factory(market='std')
client.k(symbol="600300", begin="2017-07-03", end="2017-07-10")

# 前复权
client.k(symbol="600300", begin="2017-07-03", end="2017-07-10", adjust='qfq')

# 后复权
client.k(symbol="600300", begin="2017-07-03", end="2017-07-10", adjust='hfq')

# ohlc 是k的别名, 功能相同
client.ohlc(symbol="600300", begin="2017-07-03", end="2017-07-10")

# 前复权
client.ohlc(symbol="600300", begin="2017-07-03", end="2017-07-10", adjust='qfq')

# 后复权
client.ohlc(symbol="600300", begin="2017-07-03", end="2017-07-10", adjust='hfq')
```

## 15. 在线查询通达信与申万行业

标准行情客户端可以下载行情服务器发布的 `tdxhy.cfg` 和 `zhb.zip/incon.dat`，关联证券的
通达信行业与申万行业，无需本地通达信安装目录。

```python
from tdxhub.quotes import Quotes

with Quotes.factory(market="std", timeout=5) as client:
    all_industries = client.stock_industries()
    one = client.stock_industries("SH.600519")
    selected = client.stock_industries(["sz000001", "sh600519"])
    refreshed = client.stock_industries("sh600519", refresh=True)
```

- `symbols` 可省略，也可传单个代码或代码列表/元组；批量结果保持输入顺序。
- 输出包含 `market`、`code`、`tdx_industry_code/name/source`、
  `sw_industry_code/name/source`、`sw_level1_code/name`、`sw_level2_code/name`、
  `sw_level3_code/name`、`source` 和 `raw_fields`。
- 新版 `TDXRSHY` 与旧版 `SWHY` 编码都会展开到实际存在的层级；父级名称只在当前命中的
  字典分区内查找。字典缺少父级时保留可推导的父级代码，名称返回空值。
- 完整关联结果在进程内全局共享，并持久化到 `~/.tdxhub/caches/quotes`；默认每 24 小时
  在下一次访问时更新，`refresh=True` 强制重新下载。
- 返回值是缓存的独立副本，调用方修改 DataFrame 或其对象列/`attrs` 不会影响后续查询。
- 自动到期更新失败时临时回退到旧数据并在 5 分钟后重试；显式刷新失败会直接抛错。
- 这是行情服务器发布的行业配置，而非逐笔实时行情；数据新鲜度取决于服务器文件版本。

## 16. 聚合证券信息

`stock_info()` 将证券目录、实时行情、行业、财务、除权除息和集合竞价合并成一行，适合一次
读取展示或筛选所需的常用字段：

```python
from tdxhub.quotes import Quotes

with Quotes.factory(market="std", timeout=5) as client:
    info = client.stock_info(["SH.600519", "sz000001", "bj920001"])

    # 串行诊断，或在 1..16 范围内调整本次调用的并发度
    serial = client.stock_info("sh600519", max_workers=1)

    # 强制刷新当前调用涉及的市场目录和行业配置
    refreshed = client.stock_info(
        "sh600519",
        refresh_directories=True,
        refresh_industries=True,
    )
```

返回固定 37 列的 `pandas.DataFrame`：

- 标识与分类：`full_code`、`exchange`、`market_id`、`code`、`name`、`category`、`board`；
- 行情与衍生值：最新/昨收/开高低、涨跌额/幅、成交量/额、开盘竞价金额、流通/总股本、
  换手率、流通/总市值；
- 财务与行业：`eps`、上市/更新日期、通达信行业和申万一至三级行业。

结果只包含规范化后的标量字段，不保留证券目录、实时行情和财务接口的原始字典。

输入可以是单个代码或列表/元组，结果保持原顺序与重复项；相同证券的底层数据只拉取一次。
北交所证券当前只聚合目录与行业，不调用仅覆盖沪深的实时、财务、XDXR 和集合竞价接口。

默认 `max_workers=4`。沪深证券的 `finance()`、`xdxr()`、`call_auction()` 使用独立 TCP
连接并发请求，连接由当前 `StdQuotes` 实例的有界连接池复用，并在 `close()` 或上下文退出时
释放。`max_workers` 必须是 `1..16` 的非布尔整数；市场目录跨实例共享并持久化，
`refresh_directories=True` 可强制刷新。

## 17. 资金流向与主力监控 (Capital Flow)

基于全量逐笔分笔（Tick）成交数据，与同花顺、东方财富、通达信等主流软件标准算法对齐，提供高精度的超大单、大单、中单、小单切片及主力/散户博弈分析。

### 17.1 实时与单日资金流向 (`capital_flow`)

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    # 盘中实时（默认当日全量逐笔）
    flow = client.capital_flow("002594")

    # 历史单日（自动缓存加速）
    hist_flow = client.capital_flow("600519", date="20260914")

    # 提取核心汇总属性
    print("主力净买入(元):", flow.attrs["main_net"])
    print("主力净流入占比:", f"{flow.attrs['main_net_pct']}%")
    print("散户净买入(元):", flow.attrs["retail_net"])
    print("全天总成交额(元):", flow.attrs["total_turnover"])
```

- **分档标准**（可通过 `thresholds` 自定义，默认 `(40000, 200000, 1000000)`）：
  - 超大单：$\ge 100$ 万元
  - 大单：$20 \sim 100$ 万元
  - 中单：$4 \sim 20$ 万元
  - 小单：$< 4$ 万元
  - 主力 = 超大单 + 大单；散户 = 中单 + 小单
- 返回包含各档位买入额、卖出额、净流入额、净占比、买量、卖量、净量（手数）的 DataFrame，并在 `attrs` 字典中注入核心统计指标。

### 17.2 多日资金流向与主力 5日 / 20日 净流入 (`capital_flow_history`)

```python
with Quotes.factory("std", timeout=5) as client:
    # 回溯近 20 个交易日资金流向
    hist = client.capital_flow_history("002594", days=20)

    # 5日 / 20日 主力汇总指标
    print("5日主力净流入:", f"{hist.attrs['main_5d_net'] / 1e8:.3f} 亿元, 占比: {hist.attrs['main_5d_pct']}%")
    print("20日主力净流入:", f"{hist.attrs['main_20d_net'] / 1e8:.3f} 亿元, 占比: {hist.attrs['main_20d_pct']}%")

    # 逐日明细及滚动累计列
    cols = ["date", "close", "change_pct", "main_net", "main_5d_net", "main_20d_net"]
    print(hist[cols].tail())
```

### 17.3 行业与板块资金流汇总及穿透 (`sector_capital_flow`)

```python
with Quotes.factory("std", timeout=5) as client:
    # 行业名称模糊检索（支持通达信行业及申万一级/二级/三级行业，如 "白酒"、"半导体"、"银行"）
    sector = client.sector_capital_flow("白酒")

    # 板块汇总指标
    print(f"板块主力净流入: {sector.attrs['main_net'] / 1e8:.3f} 亿元")
    print(f"板块主力净占比: {sector.attrs['main_net_pct']}%")
    print(f"资金流入龙头: {sector.attrs['top_inflow_code']}")
    print(f"主力出逃最多: {sector.attrs['top_outflow_code']}")

    # 成分股主力净买入降序明细
    print(sector.head())

    # 自定义成分股池统计
    custom = client.sector_capital_flow(name="自选组合", symbols=["600519", "000858", "002594"])
```

## 18. 通达信官方综合统计与估值指标 (Statistics)

读取并解析通达信官方报告中的个股综合统计数据（`tdxstat.cfg`），提供市盈率TTM、静态市盈率、股息率、连涨连跌天数以及区间涨跌幅：

```python
with Quotes.factory("std", timeout=5) as client:
    # 指定个股（支持单只或列表；不传时返回全市场 8000+ 标的）
    stats = client.statistics(["600519", "002594", "300750", "000001"])
    print(stats[["code", "date", "pe_ttm", "pe_static", "dividend_yield", "trend_days", "change_pct", "change_5d", "change_20d", "change_ytd"]])
```

- `pe_ttm`: 动态市盈率 (TTM)
- `pe_static`: 静态市盈率
- `dividend_yield`: 股息率 (%)
- `trend_days`: 连涨连跌天数（正数代表连涨，负数代表连跌）
- `change_pct`: 当日涨跌幅 (%)
- `change_5d`, `change_10d`, `change_20d`, `change_60d`, `change_ytd`: 5日、10日、20日、60日、年初至今区间涨跌幅 (%)

## 19. 通达信官方盘后资金流数据包 (Money Flow)

```python
with Quotes.factory("std", timeout=5) as client:
    # 读取官方盘后资金流及板块归属报告（tdxstat2.cfg）
    report = client.money_flow()
```

## 20. 新股申购日历与发行信息 (IPO / XGSG)

从通达信官方报告数据包（`xgsg.cfg`）获取全市场近期拟上市及已申购新股（包含沪深主板/科创板/创业板、北交所）的发行日历、发行价格与市场归属：

```python
with Quotes.factory("std", timeout=5) as client:
    # 1. 获取全市场近期新股申购清单（别名 client.ipo() / client.new_stocks()）
    ipos = client.xgsg()
    print(ipos[["market", "code", "name", "date", "issue_price"]].head())

    # 2. 查询指定新股发行信息（支持代码过滤）
    single = client.xgsg("001246")
```

- `market`: 所属市场（`sh` 沪市、`sz` 深市、`bj` 北交所）
- `code`: 股票代码
- `name`: 拟上市新股名称
- `date`: 网上申购日期（YYYYMMDD）
- `issue_price`: 发行价格（元）
- `raw_fields`: 官方原始完整字段（保留总发行量、网上发行量、发行市盈率、中签率、申购代码等）
