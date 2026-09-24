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
    request_timeout=15,
    failover=True,
    max_failovers=2,
    unhealthy_cooldown=60,
    max_candidates=5,
)
# multithread 启用内置行情客户端锁
# heartbeat 开启心跳包
# bestip 重新测试最快服务器
# server 自行设置服务器 IP，例如 server=('127.0.0.1', 7709)
# timeout 每次 socket 阻塞的超时时间
# request_timeout 单次底层请求的总预算，默认等于 timeout
# failover 请求失败后是否切换服务器，默认 True
# max_failovers 单次请求最多切换的服务器数量，默认 2
# unhealthy_cooldown 故障服务器冷却秒数，默认 60
# max_candidates 构造时最多保留的健康候选服务器数，默认 5
```

默认按 `BESTIP.HQ`、配置服务器的顺序探测，运行时仅保持一个活动连接。网络、连接或
TDX 协议调用失败时，由 FailoverClient 统一切换候选节点并重放当前只读请求，最多
尝试 `max_failovers + 1` 个节点。`auto_retry` 参数仅保留兼容，托管底层不再自行重连；
`failover=False` 表示只尝试一次。空结果和参数校验错误不会触发切换。

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
一个底层连接/协议异常；总预算耗尽抛出 `TimeoutError`。构造阶段所有候选节点均不可用时始终抛出
`TdxhubConnectionError`。

### 主站能力缓存

除连接级冷却外，运行时还会按**主站 + 接口 + 市场集合 + K 线周期**记录请求结果，
默认有效期 300 秒。目前覆盖标准行情的 `get_security_quotes`、`get_security_bars`
和 `get_index_bars`，不做全接口启动探测，也不持久化到配置文件。

- `supported`：观察到非空成功响应，优先复用；不保证该市场所有证券都有数据。
- `unknown`：尚无证据或响应为空；不拉黑、不因空结果自动重试。
- `failed`：发生解析/解压协议异常，暂时跳过该主站的同类请求；其他市场/接口不受影响。
- EOF、发送失败、超时等传输错误仍触发整个主站的冷却；到期允许再次尝试。
- 混合市场批次独立记录，不把沪京混合批次的结果推断为纯北交能力。

`client.server_status()` 中有未过期记录的节点会附带 `capabilities` 列表，包含
`interface`、`markets`、`category`、`status`、`ttl_remaining` 和 `last_error`。
错误信息会保留主站、解析命令和相关长度；记录解析错误还包含偏移和最多 16 字节响应前缀。

### 按目标证券进行启动探测

默认仍用上海 `600000` 日 K 检查标准主站，不代表北交所也可用。需要验证实际目标市场时：

```python
with Quotes.factory(
    'std',
    probe_symbols=['sh600000', 'sz000001', 'bj920002'],
    probe_frequencies=[9, 8],  # 日 K + 1 分钟 K；[] 表示仅探测 quotes
    timeout=3,
    request_timeout=8,
    heartbeat=True,
) as client:
    print(client.server_status())
    data = client.quotes('bj920002', diagnostics=True)
```

样本为示例，请替换为当前有效证券。`probe_symbols` 必须为非空 list/tuple，每个市场一个样本；
代码去除可选市场前缀后必须为 6 位 ASCII 数字，非法探测参数在配置初始化和建连前拒绝。周期为 `0..11` 的整数列表。每个样本分别发起一次 quotes 和各周期 bars，不发送混合市场探针。
协议错误后重连再验证其他能力；至少一次正常响应（含合法空数据）的主站才可入池。
显式探测按已验证能力覆盖优先选择最多 `max_candidates` 个节点，避免有限名额全部被同类节点占用；
有限样本无法保证所有证券可用，`unknown` 仍允许业务请求尝试，未覆盖的能力由运行时继续学习。

### 超时、心跳与边界

- `request_timeout` 必须是正的有限数字，默认等于 `timeout`，标准和扩展行情均支持。
  单次底层调用的连接、握手、锁等待、分片收发及跨节点重试共用预算，不随每个分片或重试重置。
- 托管扩展行情不再叠加外层 tenacity 重试，合法空数据直接返回；独立裸客户端的旧重试机制不变。
- `heartbeat=True` 时，心跳失败会隔离并关闭旧连接，**下次业务请求**再切换，不主动预建备用连接。
  成功响应才刷新 ACK 时间；锁竞争不当作远端故障，过期连接的心跳事件不会误伤新连接。
- 每个启动候选的探测预算独立为 `min(timeout, 3)` 秒；全部候选分批并发，构造总耗时不受一个
  `request_timeout` 限制。`bestip=True` 的前置 TCP 测速也不在该预算内。
- 批量 quotes、历史分页和聚合操作包含多次底层调用，各次独立预算；连接池借用等待和 DataFrame
  处理不在单次协议预算内。该机制限制网络等待，不能强制中断 Python CPU 运算或任意自定义客户端。
- 只能提升公共主站可用性，不能承诺主站 SLA 或行情新鲜度；本次没有新增动态节点发现。

## 01. 查询实时行情

可以获取**多**只股票的行情信息

**参数说明: **

- `symbol`：单个或多个证券代码，如 `"920002"`、`["000001", "600300"]`；
  支持既有市场前缀写法。标准证券代码必须为 6 位 ASCII 数字，不再静默截断超长代码。
- `batch_size`：关键字参数，默认 `80`，允许 `1..80` 的整数；批次顺序发送，不并发请求。
- `diagnostics`：关键字参数，默认 `False`；设为 `True` 后在返回值
  `df.attrs["diagnostics"]` 中提供批次与缺失诊断，不增加行情列。

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

# 北交所 A 股快照，也可以和沪深证券混合查询
client.quotes(symbol="920002")
client.quotes(symbol=["600519", "000001", "920002"])
```

北交所 A 股价格按 `0.01` 系数解析，包含最新价、昨收、开高低、成交量额和五档买卖盘口。
市场映射兼容 `920xxx` 及旧 `4xxxxx` / `8xxxxx` A 股代码；旧代码是否仍有数据取决于主站。
返回值仍是 DataFrame，不因批次含北交所而整批本地拒绝。

**边界：**需使用能正常提供目标证券行情的主站；周末或休市时返回的快照不是实时成交。
此处快照改动只涉及 `quotes()`，不代表所有北交接口均已验证。2026-09-21 已另行验证并解除分时、历史分笔入口的旧市场限制，见下文第 06–09 节；F10 限制仍保留。

### 指数快照字段

指数的五档价格/数量字段在协议中可能被复用，不能当作股票买卖盘。公开 `quotes()` 返回的
`bid1..5/ask1..5/bid_vol1..5/ask_vol1..5` 对指数设为 NaN/None（HTTP 为 null），
沪深指数另提供 `up_count/down_count`（涨/跌家数）。北交家数映射未确认，返回空值。
股票/基金盘口不变；底层 `client.get_security_quotes` 仍保留原始协议记录。

### 分批、去重与诊断

请求按 `(market, code)` 稳定去重，返回行按输入首次出现顺序排列；同码不同市场不合并。
重复响应只保留首条，不属于当前批次的响应被过滤。不会为缺失证券生成虚假的零行情。

```python
df = client.quotes(
    ["600519", "000001", "920002", "920002"],
    batch_size=80,
    diagnostics=True,
)
info = df.attrs["diagnostics"]
print(info["status"], info["missing"])
# requested: 规范化并去重后的 (market, code) 列表
# duplicates_removed: 请求去重数量；batches: 实际调用批次数
# missing: 成功请求但未返回的证券；unexpected: 被过滤的意外证券
```

| status | 含义 |
| --- | --- |
| `ok` | 所有去重后的请求证券均有返回 |
| `missing` | 请求成功，但存在缺失证券；合法空响应也属此类 |
| `empty_input` | 空输入，未发送请求 |
| `request_failed` | 底层在非抛异常模式返回 `None`；附 `failed_batch` |
| `invalid_input` | 底层 `ValidationException`；附 `error`，保持既有空返回契约 |

本地代码格式或批次大小无效会直接抛出 `ValueError` / `TypeError`，不伪装成行情缺失。
若某批请求失败，`raise_exception=True` 时异常直接向上传播；非抛异常模式返回**整次空结果**，
不交付前几批的部分行情。此时 `missing` 留空，需依据 `status` 区分请求失败和正常缺失。
`attrs` 是当前 DataFrame 的辅助元数据，导出或经过其他 pandas 操作后不保证保留。

默认 80 是基于主站实测采用的保守上限，不是对所有主站容量的保证。
详细证据见 [可靠性设计与验证](../design/202609201312-quote-reliability.md)。

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

按日期调用 `get_k_data(code, start_date, end_date)`（或 `k`/`ohlc`）时，区间为
`[start_date, end_date)`，含起始日期、不含结束日期；从最新页按真实日期向前收集，
不使用自然日差推算偏移，周末/历史区间不会因此漏掉末日。返回 `date` 索引。

### 分页完整性与复权口径

- `bars_all` / `index_all` / `transaction_all` / `transactions_all` 自动分页；
  `get_k_data` 使用同一完整性保护。正常空页或短页表示数据结束；连接失败返回的
  `None` 会抛出 `TdxhubConnectionError`，不会把已获取的部分数据当作完整结果。
  单页 `bars` / `index_bars` / `transaction` / `transactions` 同样不再将 `None` 转为空表。
- 若读满到协议偏移上限仍不能确认结束（或覆盖请求区间），抛出
  `TdxhubIncompleteDataError`，而不是静默截断。异常位于 `tdxhub.exceptions`。
- 前/后复权只调整价格，`vol`、`volume`、`amount` 保留实际成交口径。
  `turnover=True` 始终使用实际成交量和对应日期流通股本，不能因送转复权而翻倍。
  本地 `StdReader.daily` 使用相同规则。
- 基金/ETF 的现金分红（category 1）和扩缩股（category 11）按事件日期累计复权；
  同日多个事件按输入顺序生效，不限于最近一次拆分。`suogu` 必须为正有限数。
  基金支持带市场前缀的代码并保留三位价格精度，股票维持两位。

## 03. 查询证券数量

**参数说明：**

- `market`：市场代码，`0` - 深圳、`1` - 上海、`2` - 北京；沪深市场也可使用
  `MARKET_SZ`、`MARKET_SH` 常量。
- `security_type`：可选证券类型。支持 `a_stock`、`b_stock`、`index`、`etf`、
  `fund`、`bond`、`other`；`None` 表示不筛选。

- `raw`：仅 SDK 的关键字参数，默认 `False`。`True` 返回协议原始计数，不能同时指定 `security_type`。

沪深不传 `security_type` 时使用协议快速计数。北交默认按报告目录计数，与 `len(stocks(2))` 一致；
`stock_count(2, raw=True)` 可查询原始值，两者口径不同，不能据差值认定漏股。
指定证券类型时先加载完整目录再过滤；北交默认计数和按类型计数首次加载可能较慢。
HTTP `/count?exchange=bj` 跟随目录口径，不提供 `raw` 参数。

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

> 支持沪、深、北市场（例如 `bj920026`）。此接口复用历史分时协议查询当日数据。协议不携带时间字段，tdxhub 会按 A 股交易时段补齐 `datetime` 列和同名 `DatetimeIndex`。

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

仅支持已校准成交量单位的股票/基金。仅筛选 09:25（含）至 09:30（不含）且价格/量为正有限数、
`buyorsell` 为 0/1/2 的成交；同价记录累加，将分笔手数换算为股/份，再估算金额（元）。
09:15 的零量指示记录及类型 5/8 不用作开盘成交。

新增 `auction_status` 列：

| 状态 | 行为 |
| --- | --- |
| `derived` | 推导的竞价价格/量额，与首分钟范围一致；从 09:31 扣减相应量额 |
| `missing` | 未找到有效竞价；09:30 OHLC 为 NaN（HTTP 为 null），量额为 0；09:31 不变 |
| `inconsistent` | 竞价多价、量额超过首分钟或价格超出其高低范围；同样空值占位，不扣 09:31 |
| `not_applicable` | 普通分钟柱，或原数据已有的未重新推导竞价柱 |

已有 09:30 不重复插入。即使状态为 `derived`，09:31 OHLC 也保留源柱，
不能仅通过量额相减还原“剔除竞价后的 OHLC”；这不是逐笔重建的完整 K 线。

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

历史结果同样包含指定日期的 `datetime` 列和同名 `DatetimeIndex`。支持沪、深、北市场，
例如 `client.minutes("bj920026", date="20260918")`；实际可查询日期取决于行情节点留存。
北交 `minute_241()` 的历史日期路径也使用下文历史分笔接口补充集合竞价。

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

当前分笔接口 `transaction()` / `transaction_all()` 不再按本机时间拦截，午休和收盘后
仍向主站查询；网络或分页失败仍报错，不当作空数据。协议只返回时分、不含交易日期，
非交易日或开盘前可能保留上一交易日记录。需要明确日期时应使用
`transactions()` / `transactions_all(date=...)`，不能据当前分笔接口断言数据属于今天。

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

历史分笔及 `transactions_all()` 支持沪、深、北市场，例如
`client.transactions_all("bj920026", date="20260918")`。基于它们的
`capital_flow("bj920026", date="20260918")` 同样可用；真实空响应不等于市场不支持，
网络/分页失败仍会报错。此范围不包含 F10。

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

### 单位与字段迁移（`finance_schema="tdx_finance_v2"`）

SDK、底层 `StandardClient.get_finance_info()` 与 HTTP `/finance` 使用相同的解析结果：
金额槽位从**千元转换为元（×1000）**，总/流通/B/H 股本从**万股转换为股（×10000）**，
每股收益/每股净资产不缩放。此前金额误乘 10000，放大了 10 倍；**新结果不可再次除以 10**。
股本、每股指标不能跟随金额统一缩放。协议 float32 和摘要截断会有小量精度损失。

| 错误旧字段（现在返回 `None` / JSON `null`） | 正确新字段 | 含义/单位 |
|---|---|---|
| `zhigonggu` | `meigushouyi` | 基本每股收益，元/股 |
| `faqirenfarengu` | `shangniantongqijinglirun` | 上年同期归母净利润，元 |
| `farengu` | `shangniantongqiyingyeshouru` | 上年同期营业收入，元 |
| `changqifuzhai` | `shaoshugudongquanyi` | 少数股东权益，元 |
| `zhuyinglirun` | `yingyechengben` | 营业成本，元，不是利润 |
| `guojiagu` | 无 | 槽位含义未确认，不能当作国家股 |

保留名称但明确口径：`jingzichan` 为归母股东权益，`jinglirun` 为归母净利润，
`shuihoulirun` 为合并净利润，`zhuyingshouru` 为营业收入。
`zongxianjinliu` 为经营/投资/筹资现金流净额之和，**不含汇率变动影响**，不是现金及现金等价物净增加额。
`updated_date` 是源更新日期，不是报告期；`baoliu2` 是未定性的原始保留值，不应据此拼接报告日期。
`province/industry/ipo_date` 保持协议值；零值保留为零，不额外推断为“缺失”。

`raw_fields` 为未换算的全部原始槽位字典，键沿用旧槽位名，**不代表这些旧名含义正确**。
需要复盘旧数据时可读取它，但不可把原始槽位直接作为规范化指标。
专业财务 `Affair` 的编号列/文件解析契约未改变，也不因本次修复而再次缩放。

### 质量状态

`data_quality` 字典列（HTTP 为 JSON 对象）：

- `status="normalized"`：已应用字段表和单位换算；不是所有证券/历史协议/财报准确性的认证。
- `status="inconsistent"`：真实股本字段存在大于总股本的分量，`issues` 包含 `share_components_exceed_total`。
- `warnings` 可包含 `net_assets_per_share_basis_difference`；`net_assets_per_share_ratio` 为归母权益/总股本/每股净资产的比值。
  银行普通股口径可能扣除其他权益，差异只提示，不自动修正倍率，也不一律判作坏数据。
- `unverified_fields=["guojiagu", "baoliu2"]`：未定性槽位。
- 未携带新 schema 的旧记录/自定义客户端仍标为 `legacy_unverified`，仅诊断、不猜测其单位进行二次换算。

已与同一提供方 20260630/20250630 专业财务文件交叉核验沪/深/北四只证券（含银行、保险），
并固定为离线回归。**尚未完成发行人公告逐项审计及所有证券/历史协议验证**；详见
[财务校准证据与边界](../design/202609201940-finance-field-correction.md)。

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
北交所证券同时聚合目录、行业、实时行情、财务与 XDXR；集合竞价覆盖尚未确认，
不在汇总中调用，`open_amount_yuan` 保持空值。`attrs["skipped_sources"]` 记录跳过的来源。

股本优先采用最近的有效 XDXR 股本事件，缺失或非正数时逐项回退至财务股本。
XDXR 的万股值先乘 10000，再取整到股，不会先丢弃万股的小数部分；市值和换手率
使用这份股本计算。它与财务报告的时点和源端精度可能不同，不保证逐股相同，
也不能代替发行人的最新股本公告。底层 `get_equity_snapshot()` 对标记
`equity_unit="ten_thousand_shares"` 的数据执行同样转换，返回值统一为股；
调用方不应再对快照重复乘 10000。未标记的本地 GBBQ 数据仍按股处理。


默认 `max_workers=4`。支持的 `finance()`、`xdxr()`、`call_auction()` 来源使用独立 TCP
连接并发请求，连接由当前 `StdQuotes` 实例的有界连接池复用，并在 `close()` 或上下文退出时
释放。`max_workers` 必须是 `1..16` 的非布尔整数；市场目录跨实例共享并持久化，
`refresh_directories=True` 可强制刷新。

## 17. 资金流向与主力监控 (Capital Flow)

基于分笔（Tick）成交金额分档的估算，不是交易所官方资金流，不保证与同花顺、东方财富等软件算法一致。
分笔可能包含聚合/舍入，估算总额与日 K 成交额也不保证严格相等。

### 17.1 实时与单日资金流向 (`capital_flow`)

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    # 盘中实时（默认当日全量逐笔）
    flow = client.capital_flow("002594")

    # 历史单日
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
- 当前只支持股票/基金，金额按价格 × 分笔手数 × 100 估算。债券、B 股、指数及未知品种的单位/币种未校准，会抛 `TdxhubValidationException`（HTTP 400）；不限制原始分笔查询。
- 只计入价格/量为正有限数且 `buyorsell` 为 0/1/2 的成交。0/1 分别为主动买/卖；2 为中性，计入 `total_turnover/total_volume`，不计入主动买卖额与净额，因此买入额+卖出额不一定等于总额。
- SDK `attrs` 新增 `method="tick_estimate"`、`volume_unit="lot"`、`volume_multiplier=100`、`neutral_turnover`、`excluded_trade_count`、`unknown_side_counts`。5/8 等仅记录排除数量，不推断未确认的协议语义。
- HTTP 维持行列表契约，不序列化 DataFrame `attrs`；需完整统计诊断请使用 SDK。

### 17.2 多日资金流向与主力 5日 / 20日 净流入 (`capital_flow_history`)

**窗口规则：** `days` 是返回天数，必须为正整数，不是累计窗口长度。
SDK 会额外读取最多 19 个资金流预热交易日，并多取一根日 K 用于昨收；超过 800 根时分页获取。
因此同一截止日、同一数据源的 `days=5` 和 `days=20` 会得到相同的末日 20 日指标。
窗口基于该证券的日 K 交易记录，不把无成交记录的日期补成零。

- 只有完整的 5/20 日窗口才计算相应累计净额及占比；历史不足时返回 `NaN`
  （HTTP JSON 为 `null`），不以部分天数的合计冒充完整窗口，也不填 0。
- 每行及末日 `attrs` 均有 `window_5d_days` / `window_20d_days`（实际覆盖天数）和
  `window_5d_complete` / `window_20d_complete`（是否完整）。未取得首日前收盘时，首日涨跌幅也为缺失值。
- 无可用日 K，或计算范围内任一天缺少成交数据，抛出 `TdxhubIncompleteDataError`；
  分页连接失败传播异常，不返回残缺汇总。有效成交形成的净额 0 则正常保留。
- 预热会增加首次请求量；历史成交数据使用现有缓存。`adjust` 仅影响日 K 价格，
  不作用于 Tick 成交金额。HTTP 的 `days` 范围仍为 1..100。


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

成分股按“市场 + 裸代码”去重，例如 `600519` / `SH.600519` 只计一次；
相同数字但不同市场的代码不合并，输出保留第一次出现的代码写法。
空列表会报参数错误。任一成分股查询失败或无有效成交数据时，整体抛出
`TdxhubIncompleteDataError`，包含失败证券和原因，不再跳过失败成分后返回看似完整的板块总量。
HTTP 沿用错误包络 `code=1, data=null`（不应仅凭 HTTP 200 判断成功）。


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

官方统计中的空白、无效及非有限数值保留为空值（DataFrame 中 NaN/None，JSON 中 null），
不再用 0 代替未知或不适用；原始的有效 0 仍保留。

## 19. 通达信官方盘后资金流数据包 (Money Flow)

```python
with Quotes.factory("std", timeout=5) as client:
    # 读取官方盘后资金流及板块归属报告（tdxstat2.cfg）
    report = client.money_flow()
```

- `date` 是官方报告日期，可能滞后于当前交易日，不会重标为今天。
- `amount` 为报告日成交额，`amount_prev` 为前一交易日成交额，**统一为元**，
  与日 K 和分笔估算资金流的金额单位一致；它们不是主力净流入。
- **兼容性提示**：原文件单位为万元，旧版本原样返回；现在这两个字段已乘以 10,000，
  调用方应移除重复换算。`raw_fields[3]` / `[5]` 保留原始万元字符串，
  `attrs["amount_unit"]="yuan"`、`attrs["source_amount_unit"]="ten_thousand_yuan"`。
- 源金额通常只有万元小数点后两位，转换不增加精度；与日 K 金额可能存在舍入差。
- 金额和价格的空白/无效/非有限值返回空值，不再补 0；有效 0 保留。

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
- `issue_price`: 发行价格（元）；尚未公布或源值无效时为空值（JSON null），不是 0
- `raw_fields`: 官方原始完整字段（保留总发行量、网上发行量、发行市盈率、中签率、申购代码等）
