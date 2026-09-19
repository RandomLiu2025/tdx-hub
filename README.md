# tdxhub

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/tdxhub-sdk.svg)](https://pypi.org/project/tdxhub-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`tdxhub` 是面向 Python 3.11+ 的通达信市场数据工具包。它将本地 VIPDOC 文件、标准/扩展在线行情、官方配置与财务文件、复权与换手率、增量拉取和可选 HTTP 服务统一到一套现代化 Python API 中。

> **提示**：本项目专注于金融市场数据的高效读取、协议解析与本地存储，不包含任何交易与下单功能。

---

## 目录

- [功能概览](#功能概览)
- [安装指南](#安装指南)
- [快速开始](#快速开始)
  - [1. 读取本地 VIPDOC 文件](#1-读取本地-vipdoc-文件)
  - [2. 在线行情与指数获取](#2-在线行情与指数获取)
  - [3. 个股与指数区分说明](#3-个股与指数区分说明)
  - [4. 资金流向与主力监控](#4-资金流向与主力监控-capital-flow)
- [复权、GBBQ 与历史换手率](#复权gbbq-与历史换手率)
- [官方配置与财务数据](#官方配置与财务数据)
- [增量同步与 SQLite 持久化](#增量同步与-sqlite-持久化)
- [HTTP API 服务](#http-api-服务)
- [命令行工具 (CLI)](#命令行工具-cli)
- [测试与本地开发](#测试与本地开发)
- [文档索引](#文档索引)
- [License](#license)

---

## 功能概览

| 功能模块 | 核心入口 | 核心能力说明 |
|---|---|---|
| **本地行情** | `tdxhub.reader.Reader` | 读取日线、1/5分钟线、扩展市场、退市股缓存（`ds_cache`）、板块与官方配置文件 |
| **在线行情** | `tdxhub.quotes.Quotes` | 实时切片、全量/分页 K 线、大盘指数、分时、逐笔分笔、集合竞价、财务与扩展行情 |
| **资金流向** | `capital_flow*` / `sector_capital_flow` | 逐笔切片（超大/大/中/小单）、主力5日/20日净流入、行业板块资金流汇总及成分股穿透 |
| **品种分类** | `tdxhub.security` | 自动识别区分 A/B 股、指数、ETF、普通基金、债券等，支持多市场统一过滤 |
| **复权与换手率** | `tdxhub.gbbq` | GBBQ/XDXR 规范化、高精度前复权/后复权、历史流通股本快照与日 K 换手率计算 |
| **官方配置** | `tdxhub.official` | 解析板块 (`spblock`)、行业 (`tdxhy`/`incon`)、北交所目录、估值统计与新股申购配置 |
| **专业财务** | `tdxhub.affair.Affair` | 财务数据包清单获取、自动下载、MD5 校验与结构化解析 |
| **增量同步** | `tdxhub.pull` | 自动规划缺口区间、分页拉取、逐笔分钟线补齐、SQLite 事务与幂等持久化 |
| **HTTP 服务** | `tdxhub.http` | 基于 FastAPI 提供轻量 RESTful API，涵盖行情、K 线、逐笔、资金流与财务路由 |
| **CLI 命令行** | `tdxhub` | 提供离线读取、行情查询、优选测速节点、财务管理等终端命令 |

---

## 安装指南

PyPI 发行包名为 **`tdxhub-sdk`**；安装后直接使用 `import tdxhub`，CLI 命令为 `tdxhub`。

```bash
# 基础安装
python -m pip install -U tdxhub-sdk
```

### 可选能力扩展

根据业务需求安装扩展依赖：

```bash
# 1. 支持节假日日历解析
python -m pip install -U "tdxhub-sdk[holiday]"

# 2. 支持 FastAPI HTTP 服务端
python -m pip install -U "tdxhub-sdk[server]"

# 3. 安装全部可选依赖
python -m pip install -U "tdxhub-sdk[all]"
```

### 源码开发

```bash
git clone https://github.com/RandomLiu2025/tdx-hub.git
cd tdx-hub
uv sync --extra server --extra test
```

---

## 快速开始

### 1. 读取本地 VIPDOC 文件

`tdxdir` 支持通达信客户端安装根目录，或直接指向 `vipdoc` 目录。代码支持纯数字或带前缀形式（如 `600000`、`SH600000`、`SH.600000`），自动判定沪、深、北三大市场。

```python
from tdxhub.reader import Reader

# 标准市场本地读取
reader = Reader.factory("std", tdxdir=r"D:\new_tdx")

# 日线、1分钟、5分钟 K 线
daily = reader.daily("SH.600000")
minute = reader.minute("600000")
five_minute = reader.fzline("600000")
print(daily.tail())

# 退市证券缓存（ds_cache/*.~~~day）
retired = reader.delisted_daily("sz000003")

# 本地板块与官方配置
concepts = reader.block("block_gn.dat")
beijing = reader.beijing_stocks()
industries = reader.stock_industries()
```

扩展市场本地文件（期货、期权等）使用独立 factory：

```python
ext_reader = Reader.factory("ext", tdxdir=r"D:\new_tdx")
future_daily = ext_reader.daily("4#CF7D0LAO")
```

---

### 2. 在线行情与指数获取

`Quotes` 是统一的行情工厂，推荐使用 `with` 上下文管理器管理连接生命周期：

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    # 1. 实时切片快照（支持个股与指数）
    quotes = client.quotes(["sh000001", "399001", "sh600000", "sz000001"])

    # 2. 个股 K 线（bars）与全量历史回溯（bars_all）
    daily_bars = client.bars("sh600000", frequency=9, offset=100)
    all_bars = client.bars_all("sh600000", frequency=9, since="20250101")

    # 3. 指数专用 K 线（index / index_bars / index_all）
    # 自动识别沪、深、北交易所核心指数及行业板块指数，支持带前缀代码
    sh_idx = client.index("000001", frequency=9, offset=100)      # 上证指数 (沪市)
    sz_idx = client.index("399001", frequency=9, offset=100)      # 深证成指 (深市)
    bj_idx = client.index("899050", frequency=9, offset=100)      # 北证50 (北交所)
    bk_idx = client.index("880491", frequency=9, offset=100)      # 通达信板块指数
    idx_all = client.index_all("sh000001", frequency=9, since="20250101")

    # 4. 盘中分时与逐笔成交
    minute = client.minute("sz300394")
    minute_241 = client.minute_241("sh600000")                     # 241 根规范化分钟线
    history_trades = client.transactions_all("sh600000", date="20250910")
    auction = client.call_auction("sh600000")                     # 早盘集合竞价

    # 5. 资金流向与主力监控
    flow = client.capital_flow("sz002594")                        # 当日实时资金流分档与主力净流入
    hist_flow = client.capital_flow("sh600519", date="20260914") # 指定历史日资金流

    # 6. 证券分类与综合聚合
    etfs = client.stocks(market=1, security_type="etf")            # 筛选沪市所有 ETF
    summary = client.stock_info(["sh600519", "sz000001"])          # 37 列规范化聚合详情
```

#### 常用 K 线频率说明

| 参数值 | 频率 | 参数值 | 频率 |
| :---: | :---: | :---: | :---: |
| `8` / `7` | 1 分钟 | `9` / `4` | 日线 |
| `0` | 5 分钟 | `5` | 周线 |
| `1` | 15 分钟 | `6` | 月线 |
| `2` | 30 分钟 | `10` | 季线 |
| `3` | 60 分钟 / 1 小时 | `11` | 年线 |

#### 容灾与节点热备机制
标准与扩展行情客户端默认内置**有界自动故障转移**（Failover）：
* 内部维护健康节点池，发生断线或协议错误时自动切换可用节点（默认冷却 60 秒）；
* 支持通过 `server=(ip, port)` 锁定特定服务器，或使用 `client.server_status()` 检查节点状态。

---

### 3. 个股与指数区分说明

通达信底层协议严格区分股票与指数，调用时请注意：

1. **同代码歧义（如 `000001`）**：
   * `client.quotes("000001")`：默认判定为深市股票 **平安银行**（`000001.SZ`）。
   * `client.quotes("sh000001")`：显式指定沪市前缀，获取 **上证综合指数**。
2. **接口专业分工**：
   * **指数专用 K 线**：使用 `client.index(...)` 或 `client.index_bars(...)`。
   * **个股/ETF K 线**：使用 `client.bars(...)`。
3. **程序化判定证券类型**：
   使用内置分类器 [`classify_security`](file:///Users/bytedance/work/project/person/tdx-hub/tdxhub/security.py#L56) 判断品种：
   ```python
   from tdxhub.security import classify_security

   classify_security(0, "000001")  # 'a_stock' (平安银行)
   classify_security(1, "000001")  # 'index'   (上证指数)
   classify_security(2, "899050")  # 'index'   (北证50)
   classify_security(1, "510300")  # 'etf'     (沪深300ETF)
   ```

---

### 4. 资金流向与主力监控 (Capital Flow)

资金流向模块基于全量逐笔分笔（Tick）成交数据，与主流机构软件（同花顺、东方财富、通达信）标准算法对齐，提供高精度、细颗粒度的主力与散户资金博弈监控工具。

#### 4.1 划分标准与计算逻辑

按单笔成交金额严格切片划分四个档位（默认阈值可自定义）：
- **超大单**：单笔成交额 $\ge 100$ 万元（机构核心大单）
- **大单**：$20 \text{ 万元} \le$ 单笔成交额 $< 100$ 万元（主力活跃资金）
- **中单**：$4 \text{ 万元} \le$ 单笔成交额 $< 20$ 万元（大散户 / 中户资金）
- **小单**：单笔成交额 $< 4$ 万元（散户游资）
- **聚合分类**：
  - **主力资金** = 超大单 + 大单
  - **散户资金** = 中单 + 小单
- **主动买卖判定**：基于外盘（主动买入，成交于卖档）与内盘（主动卖出，成交于买档）判定资金进出方向：
  $$\text{主力净流入} = \text{主力主动买入额} - \text{主力主动卖出额}$$
  $$\text{主力净流入占比} = \frac{\text{主力净流入额}}{\text{全天总成交金额}} \times 100\%$$

#### 4.2 实时与单日个股资金流向 (`capital_flow`)

支持盘中实时切片统计（默认当日）与历史单日资金流分析，内置历史交易日内存高速缓存：

```python
with Quotes.factory("std", timeout=5) as client:
    # 1. 盘中实时个股资金流向（默认拉取当日全量逐笔实时聚合）
    flow = client.capital_flow("002594")  # 比亚迪
    print(flow)
    #                   buy_amount   sell_amount    net_amount  net_pct  buy_volume  sell_volume  net_volume
    # level
    # 超大单          1.458316e+08  1.782017e+08 -3.237013e+07    -3.01      4910.0       6012.0     -1102.0
    # 大单            2.946369e+08  3.716379e+08 -7.700098e+07    -7.17      9946.0      12534.0     -2588.0
    # 中单            3.568444e+08  3.328329e+08  2.401155e+07     2.24     12053.0      11244.0       809.0
    # 小单            2.766787e+08  1.913191e+08  8.535956e+07     7.95      9353.0       6459.0      2894.0
    # 主力(超大+大单) 4.404685e+08  5.498396e+08 -1.093711e+08   -10.18     14856.0      18546.0     -3690.0
    # 散户(中+小单)   6.335231e+08  5.241520e+08  1.093711e+08    10.18     21406.0      17703.0      3703.0
    # 合计            1.073992e+09  1.073992e+09  0.000000e+00     0.00     36262.0      36249.0        13.0

    # 快捷提取核心属性（存储于 DataFrame attrs 中）
    print("主力净买入(元):", flow.attrs["main_net"])
    print("主力净买入占比:", f"{flow.attrs['main_net_pct']}%")
    print("散户净买入(元):", flow.attrs["retail_net"])
    print("全天总成交额(元):", flow.attrs["total_turnover"])

    # 2. 查询指定历史单日资金流向（自动命中本地缓存加速）
    hist_flow = client.capital_flow("sh600519", date="20260914")
```

#### 4.3 多日资金流向与主力 5日 / 20日 累计净流入 (`capital_flow_history`)

回溯指定个股近 N 个交易日（默认 20 日，可指定 5、10、60 等任意天数），逐日计算成交额与各档位资金流，并输出 **5日/20日主力滚动累计净额及占比**：

```python
with Quotes.factory("std", timeout=5) as client:
    # 回溯近 20 个交易日资金流向
    hist = client.capital_flow_history("002594", days=20)

    # 1. 查看 5日 / 20日 主力汇总指标（attrs 属性字典）
    print("5日主力净流入:", f"{hist.attrs['main_5d_net'] / 1e8:.3f} 亿元, 占比: {hist.attrs['main_5d_pct']}%")
    print("20日主力净流入:", f"{hist.attrs['main_20d_net'] / 1e8:.3f} 亿元, 占比: {hist.attrs['main_20d_pct']}%")

    # 2. 查看逐日明细与滚动累计列
    cols = ["date", "close", "change_pct", "main_net", "main_5d_net", "main_20d_net"]
    print(hist[cols].tail())
    #          date   close  change_pct      main_net   main_5d_net  main_20d_net
    # 15 2026-09-08  108.50        0.84  1.250321e+07  3.541200e+07  1.120540e+08
    # 16 2026-09-09  107.20       -1.20 -2.105400e+07  1.845000e+07  9.840210e+07
    # 17 2026-09-10  109.00        1.68  3.412050e+07  4.512000e+07  1.254100e+08
    # 18 2026-09-11  110.10        1.01  1.840200e+07  5.120400e+07  1.320450e+08
    # 19 2026-09-14  111.50        1.27 -1.093711e+07  2.898160e+07  1.152439e+08
```

#### 4.4 行业板块资金流向汇总及成分股穿透 (`sector_capital_flow`)

支持按行业名称模糊检索（覆盖通达信 110 个细分行业及申万一级/二级/三级行业，如 "白酒"、"半导体"、"银行"、"汽车整车"），或传入自定义成分股代码列表。输出板块主力净流入汇总、领涨龙头与出逃股，以及所有成分股降序明细：

```python
with Quotes.factory("std", timeout=5) as client:
    # 1. 行业板块资金流汇总（别名 block_capital_flow）
    sector = client.sector_capital_flow("白酒")

    # 板块汇总指标（attrs 属性字典）
    print(f"板块名称: {sector.attrs['sector_name']} (成分股数量: {sector.attrs['stock_count']})")
    print(f"主力净流入: {sector.attrs['main_net'] / 1e8:.3f} 亿元 (占比: {sector.attrs['main_net_pct']}%)")
    print(f"资金流入龙头: {sector.attrs['top_inflow_code']}")
    print(f"主力出逃最多: {sector.attrs['top_outflow_code']}")

    # 成分股主力资金流排行（按 main_net 降序排列）
    print(sector[["code", "main_net", "main_pct", "super_net", "large_net", "total_amount"]].head())

    # 2. 自定义成分股池统计（例如自选股主力流向）
    custom_sector = client.sector_capital_flow(
        name="核心资产",
        symbols=["600519", "000858", "002594", "300750"],
    )
```

#### 4.5 资金流向接口速查

| Python API | 核心参数 | 返回结构 | 核心指标与 attrs |
|---|---|---|---|
| `capital_flow(symbol, date=None)` | `symbol`: 股票代码<br>`date`: 日期 (YYYYMMDD，默认当日) | 7行分档明细 DataFrame<br>(超大/大/中/小/主力/散户/合计) | `main_net`, `main_net_pct`, `retail_net`, `total_turnover`, `trade_count` |
| `capital_flow_history(symbol, days=20)` | `symbol`: 股票代码<br>`days`: 回溯交易日数 (默认20) | N行逐日明细 DataFrame<br>(含 5/20 日滚动列) | `main_5d_net`, `main_5d_pct`, `main_20d_net`, `main_20d_pct` |
| `sector_capital_flow(name, symbols=None)` | `name`: 行业/板块名<br>`symbols`: 自选成分股列表 | 成分股排行 DataFrame<br>(按主力净买入降序) | `sector_name`, `stock_count`, `main_net`, `main_net_pct`, `top_inflow_code` |
| `money_flow(symbol=None, days=None)` | `symbol`: 可选，为 None 时返回官方报告 | 兼容入口，自动按参数路由至对应资金流接口 | - |

> **HTTP API 对应路由**：
> - 实时/单日个股资金流：`GET /capital_flow?code=002594&date=20260914`
> - 多日累计与逐日明细：`GET /capital_flow/history?code=002594&days=20`
> - 行业/板块资金流汇总：`GET /capital_flow/sector?name=白酒`


---

## 复权、GBBQ 与历史换手率

全量日 K 线可在分页合并后自动执行前复权/后复权，并结合历史流通股本计算换手率：

```python
from tdxhub.quotes import Quotes

with Quotes.factory("std", timeout=5) as client:
    # 自动计算前复权 (qfq) 及历史换手率 (turnover)
    qfq_bars = client.bars_all(
        "sh600000",
        frequency=9,
        since="20200101",
        adjust="qfq",
        turnover=True,
    )
```

底层复权与股本快照模块亦可独立调用：

```python
from tdxhub.gbbq import adjust_prices, get_equity_snapshot, normalize_gbbq

events = normalize_gbbq(actions)
adjusted = adjust_prices(prices, events, method="qfq")
snapshot = get_equity_snapshot(events, at="2026-09-10")
```

---

## 官方配置与财务数据

### 1. 官方配置解析

通达信客户端 `hq_cache` 目录下的二进制配置文件可直接读取为结构化数据：

```python
from tdxhub.official import associate_industries, parse_official

# 板块与北交所配置
blocks = parse_official(r"D:\new_tdx\T0002\hq_cache\spblock.dat")
beijing = parse_official(r"D:\new_tdx\T0002\hq_cache\tdxbjmore.cfg")

# 行业匹配
assignments = parse_official(r"D:\new_tdx\T0002\hq_cache\tdxhy.cfg")
dictionary = parse_official(r"D:\new_tdx\T0002\hq_cache\incon.dat")
industries = associate_industries(assignments, dictionary)
```

无本地客户端时，也支持在线从行情站下载最新行业配置文件：
```python
with Quotes.factory("std", timeout=5) as client:
    industries = client.stock_industries(["sh600519", "sz000001"])
```

### 2. 个股综合统计与估值指标 (Statistics)

直接获取通达信官方报告中的全市场个股综合统计数据（`tdxstat.cfg`），包含**市盈率TTM、静态市盈率、股息率、当日涨跌幅、连涨连跌天数、区间涨跌幅（5日/10日/20日/60日/年初至今）**：

```python
with Quotes.factory("std", timeout=5) as client:
    # 查询指定个股（支持单个代码或列表；为 None 时返回全市场 8000+ 只证券）
    stats = client.statistics(["600519", "002594", "300750", "000001"])
    print(stats[["code", "date", "pe_ttm", "pe_static", "dividend_yield", "trend_days", "change_pct", "change_5d", "change_20d", "change_ytd"]])
    #      code      date  pe_ttm  pe_static  dividend_yield  trend_days  change_pct  change_5d  change_20d  change_ytd
    # 0  000001  20260914    5.29     5.3939            5.14           1        0.94       1.28        6.76        7.24
    # 1  002594  20260914   26.46    23.8782            0.42           2        1.70      -1.25       -4.95      -12.25
    # 2  300750  20260914   18.35    21.6027            2.44           1        2.00      -3.18      -15.72       -6.07
    # 3  600519  20260914   19.62    19.4066            4.07           1        0.22      -2.89       -1.17       -5.28
```

> **HTTP API**：`GET /tdx/stat`（支持 `?codes=600519,002594` 过滤）。

### 3. 新股申购日历与发行信息 (IPO / XGSG)

直接从通达信官方报告归档（`xgsg.cfg`）获取全市场近期拟上市及已申购新股（包含沪市主板/科创板、深市主板/创业板、北交所）的申购日期、发行价格与市场归属：

```python
with Quotes.factory("std", timeout=5) as client:
    # 1. 获取全市场近期新股申购日历（别名 client.ipo() / client.new_stocks()）
    ipos = client.xgsg()
    print(ipos[["market", "code", "name", "date", "issue_price"]].head())
    #    market    code      name      date  issue_price
    # 0      sz  001246  力勤资源  20260918         5.15
    # 1      sz  301716   鸿富诚  20260916         0.00
    # 2      bj  920025  凯达重工  20260914         4.26
    # 3      sz  301686  中塑股份  20260910        55.28
    # 4      bj  920229  世纪数码  20260909        15.67

    # 2. 查询指定新股发行信息
    single_ipo = client.xgsg("001246")  # 支持纯数字或 "sz001246"
```

> **HTTP API**：`GET /tdx/xgsg` 或 `GET /ipo`（支持 `?code=001246` 过滤）。

### 4. 专业财务文件管理（Affair）


```python
from tdxhub.affair import Affair

# 获取官方财务数据压缩包清单
manifest = Affair.files()

# 下载并解析单季财务数据
archive = Affair.fetch(downdir="output", filename="gpcw19960630.zip")
finance_df = Affair.parse(downdir="output", filename="gpcw19960630.zip")
```

---

## 增量同步与 SQLite 持久化

`tdxhub.pull` 模块支持按半开区间 `[start, end)` 智能计算缺失区间并增量同步至 SQLite，事务保证幂等写入：

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
    )
```

---

## HTTP API 服务

安装 `tdxhub[server]` 后，可通过依赖注入快速启动高性能 FastAPI 数据服务：

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

启动命令：
```bash
uvicorn serve_tdxhub:make_app --factory --host 127.0.0.1 --port 8000 --workers 1
```
启动后访问交互式 Swagger UI 文档：<http://127.0.0.1:8000/docs>。

### 核心接口路由速查

| 分类 | 请求方式与路径 | 查询参数 | 功能说明 |
|---|---|---|---|
| **资金流向** | `GET /capital_flow` | `code` (必需), `date` (可选, YYYYMMDD) | 单日/实时逐笔分档资金流向与主力净流入 |
| **资金流向** | `GET /capital_flow/history` | `code` (必需), `days` (可选, 默认20) | 历史逐日资金流明细及 5日/20日主力累计净流入 |
| **资金流向** | `GET /capital_flow/sector` | `name` (板块名) 或 `codes` (代码列表), `date` | 行业/板块主力资金流汇总、龙头股与成分股穿透 |
| **官方统计** | `GET /tdx/stat` | `codes` (可选, 多代码逗号分隔) | 官方估值与综合统计（市盈TTM、股息率、连涨天数等） |
| **新股申购** | `GET /tdx/xgsg` 或 `GET /ipo` | `code` (可选) | 全市场拟上市及已申购新股日历与发行信息 |
| **官方报告** | `GET /tdx/stat2` | 无 | 官方盘后资金流数据包 |
| **实时行情** | `GET /quotes` | `codes` (如 `sh600000,000001`) | 多标的实时切片快照 |
| **分时逐笔** | `GET /minute` / `GET /trade/all` | `code` | 盘中分时与当日逐笔成交明细 |
| **K 线行情** | `GET /kline/day/all` | `code`, `since`, `adjust` (qfq/hfq) | 全量历史日 K 线（支持自动前/后复权） |
| **指数行情** | `GET /index/day/all` | `code`, `since` | 沪深北大盘与行业指数全量日 K 线 |

#### 资金流向接口调用示例

```bash
# 1. 查询个股实时资金流分档切片（主力净额、散户净额及占比）
curl -s "http://127.0.0.1:8000/capital_flow?code=002594"

# 2. 查询个股 20 日历史资金流明细与 5日/20日主力累计净流入
curl -s "http://127.0.0.1:8000/capital_flow/history?code=002594&days=20"

# 3. 查询白酒行业板块主力资金流向及成分股净买入排行
curl -s "http://127.0.0.1:8000/capital_flow/sector?name=白酒"

# 4. 查询指定股票估值统计指标（市盈TTM、静态市盈、股息率、连涨天数、区间涨跌幅）
curl -s "http://127.0.0.1:8000/tdx/stat?codes=600519,002594"
```

---

## 命令行工具 (CLI)

```bash
# 查看全局帮助与版本
tdxhub --help
tdxhub --version

# 读取本地日 K 线
tdxhub reader --tdxdir D:\new_tdx --symbol 600000 --action daily

# 查询在线行情日 K 线
tdxhub quotes --symbol 600000 --action daily

# 测试并优选最快的前 5 个行情服务器节点
tdxhub bestip --limit 5

# 查看与下载财务文件
tdxhub affair --listfile

# 批量打包导出指定股票数据
tdxhub bundle --symbol 600000,000001 --action daily
```

---

## 测试与本地开发

```bash
# 运行单元测试（排除外网依赖）
uv run pytest -q -m "not network"

# 运行代码规范检查
uv run ruff check tdxhub tests

# 执行完整构建
uv build
```

---

## 文档索引

更多深度用法与接口规范请参阅项目完整文档库：

- **快速上手**：[快速上手指南](docs/quick.md) · [环境安装与配置](docs/setup.md)
- **在线行情 API**：[标准行情接口 (StdQuotes)](docs/api/quote1.md) · [扩展行情接口 (ExtQuotes)](docs/api/quote2.md) · [辅助函数说明](docs/api/extras.md)
- **本地读取与财务**：[VIPDOC 本地文件读取](docs/api/reader.md) · [专业财务数据 (Affair)](docs/api/affair.md) · [财务字段映射表](docs/api/fields.md)
- **命令行使用**：[在线行情 CLI](docs/cli/quotes.md) · [本地读取 CLI](docs/cli/reader.md) · [财务下载 CLI](docs/cli/affair.md) · [行情测速 CLI](docs/cli/bestip.md) · [离线批量导出 CLI](docs/cli/bundle.md)
- **设计与架构**：[ETF 与指数行情准确性设计](docs/design/202609132344-etf-index-accuracy-fix.md)

---

## License

本项目遵循 [MIT License](LICENSE) 开源协议。仅供个人学习、量化研究及合法的数据合规处理使用。
