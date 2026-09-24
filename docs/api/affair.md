## 01. 财务数据列表

> 财务数据相关字段，请参见 [财务数据字段对照表](fields.md)

实现了历史财务数据列表的读取，使用方式

```python
from tdxhub.affair import Affair

Affair.files()
```

结果:

```
Out[17]:
 [{'filename': 'gpcw19990630.zip',
  'hash': '65228d9db21d42e683698ac8dd72ef57',
  'filesize': 443065},
 {'filename': 'gpcw19981231.zip',
  'hash': 'adbed98b12cbc1c4ac312ff9d0fd4b69',
  'filesize': 639007},
 {'filename': 'gpcw19980630.zip',
  'hash': 'eddfbcc712aae4f3f79acee4afba6787',
  'filesize': 385920}

  .....]
```

其中，`filename` 字段为具体的财务数据文件名（不含目录）， 后面的分别是哈希值和文件大小，在同步到本地时，可以作为是否需要更新本地数据的参考

## 02. 历史数据内容

获取历史专业财务数据内容

使用上面返回的`filename`字段作为参数即可

```python
from tdxhub.affair import Affair

Affair.fetch(downdir='output', filename='gpcw20170930.zip')
```

### 下载路径与安全边界

- `filename` 只允许普通文件名，不接受绝对路径、`../`、子目录、反斜杠、Windows 盘符/设备名、
  控制字符及尾部点或空格。需要子目录时通过 `downdir` 指定，例如
  `Affair.fetch(downdir='output/finance', filename='gpcw20260630.zip')`。
- 下载、缓存校验和 `Affair.parse` 拒绝目标文件的符号链接（包括悬空链接）以及非普通文件。
  批量下载会在启动 worker 前检查全部清单文件名；写入前再次检查目标。
- 下载先写入同目录临时文件，校验临时文件的实际长度与 MD5 后再原子替换目标目录项；
  已有硬链接不会导致目录外的原文件被截断。下载、校验、写入或替换失败不会主动删除旧文件，
  临时文件会被清理；这不代表旧文件一定有效，也不承诺断电后的持久性。
- 调用者选择的 `downdir` 及其祖先目录必须可信；允许调用者显式使用目录符号链接。
  这不是沙箱，也不防御能同时替换父目录或文件项的本地恶意进程。
  底层爬虫显式指定的 `path_to_download`、`FinancialList` 的完整输出路径和
  `FinancialReader.to_data` 的完整输入路径仍由调用者负责，不应直接传入不可信路径。
- 路径安全和传输完整性不等于数据真实性：MD5 不是数字签名，无法防御清单与文件同时被篡改，
  也不能证明财务数值、字段映射或报告版本正确。

### 单文件与批量下载的完整性校验

- `Affair.fetch(filename=...)`、`Affair.fetch()`、`download()` 共用清单校验流程。
  指定单文件现在也会先获取清单；清单不可用、指定文件不在清单中，或校验信息无效时明确报错，
  不回退到无校验下载。因此下载缓存命中也需要获取清单；仅解析本地文件无需查询清单。
- 清单必须提供非空普通文件名、正整数 `filesize` 和 32 位十六进制 `hash`（MD5，大小写均可）。
  `fetch_file(downdir, file_obj)` 使用调用者传入的清单条目，也要求这三项完整；不再接受无摘要/长度的条目。
- 缓存只有长度和 MD5 都一致才复用。不一致时重新下载，但保留旧副本直到新文件校验通过；
  下载内容损坏、清单过期或网络失败会报错，不会将失败当成成功返回，也不会删除旧副本。
- 批量任务启动前预检全部条目；相同文件名、长度、摘要的重复项只下载一次。
  同名条目的校验信息冲突，或存在大小写/Unicode 规范化后的文件名别名时，整批启动前报错，
  避免跨平台多个 worker 竞争同一文件。单文件请求也会预检同一份清单。
- 原子替换是**单文件**级别，批量下载不是事务；其他文件失败前已经完成的有效下载不会回滚。
  校验失败不自动刷新清单重试，调用者可重新发起下载以取得新的清单快照。
- 底层 `Financial.content/fetch_only/fetch_and_parse` 不自动查询清单。自行管理元数据时可传
  `filesize=<正整数>`、`expected_md5=<摘要>`，同样先校验再发布；未提供时不承诺完整性校验。
  `filesize=0` 仅在这些低层入口表示未知长度；非法长度或摘要会在连接前被拒绝。
  直接调用其他低层爬虫或指定完整路径的接口不属于上述统一清单流程。

```python
from tdxhub.financial.financial import Financial

# trusted_entry 是调用者已保存并确认来源的清单条目；不要自行伪造摘要。
Financial().fetch_only(
    downdir='output',
    filename=trusted_entry['filename'],
    filesize=trusted_entry['filesize'],
    expected_md5=trusted_entry['hash'],
)
```

## 03. 解析本地数据

如果您自己管理文件的下载或者本地已经有对应的数据文件，同时支持`.zip`和解压后的`.dat`文件. 如果扩展名不写，则自动判断存在的文件.

```python
from tdxhub.affair import Affair

data = Affair.parse(downdir='output', filename='gpcw20170930.zip')
```

### 字段名称与兼容性

- 默认 `header='zh'` 使用唯一中文列名，避免转成字典时同名字段被覆盖，或 JSON 导出失败。
- FINVALUE 230–237 的表头统一增加“单季度”前缀，例如 `单季度归属于母公司所有者的净利润`；
  累计字段 FINVALUE 96 仍叫 `归属于母公司所有者的净利润`，两者不再互相覆盖。
- FINVALUE 142 改为 `财务费用(现金流量表补充资料)`，区别于利润表中的 FINVALUE 80。
- 暂未确认细分口径的重名字段只用编号区分：FINVALUE 197 为 `净资产收益率(FINVALUE197)`，
  FINVALUE 580 为 `信用减值损失(万元、FINVALUE580)`。不据此推断其与其他同名指标的计算关系。
- FINVALUE 200 根据本仓库的[字段对照表](fields.md)统一为 `总资产净利率`，不再标为“总资产报酬率”；
  这是名称一致性修正，不涉及数值重算，也不代表已经完成最新官方口径核验。
- 依赖上述旧中文名称的调用方需要迁移。建议程序使用 `header='en'`，按 `colN` 对应 FINVALUE 编号；
  字段顺序、数值和单位不变。超出已知字段表的列保留 `col581` 等编号，不猜测含义。

```python
data = Affair.parse(downdir='output', filename='gpcw20170930.zip', header='en')
cumulative_profit = data['col96']    # 累计归母净利润
quarter_profit = data['col232']      # 单季度归母净利润
# code 是索引，导出 records 时 reset_index() 以保留证券代码
records = data.reset_index().to_dict('records')
```

### 重复记录与文件完整性

`Affair.parse`、`Financial.parse/to_df`、底层 `HistoryFinancialCrawler.parse/to_df` 和旧工具
`tdxhub.utils.gpcw` 使用相同的重复记录规则：

- 同一 `(code, report_date)` 的全部财务字段完全相同（同位置的 NaN 也视为相同）时，保留第一条、
  删除后续重复项，并发出 `tdxhub.tdx.financial_data.FinancialDataWarning`，包含删除条数。
- 同一键的数据存在任何数值或长度冲突时抛出 `ValueError`，不取最后一条、不平均、不用误差容限合并。
  不同报告期的数据不会合并，因此合并多期数据后 `code` 索引仍可能重复，应以 `(code, report_date)` 为键。
- 文件记录长度按头部声明解析；支持旧版 264 字段、584 字段及更长记录。旧工具 `gpcw()` 仍返回
  `[(code, values_tuple), ...]`，但不再截断为 264 个值。
- 文件头、索引、记录截断，非法长度或指向头部/索引区的记录偏移均会报错，避免输出损坏数据。

这些校验不代表数据源数值经过审计；源数据中的 0 也可能表示缺失或不适用，而非真实的零值。

### 数值口径与核对限制

- 金额需按具体字段单位解释：例如 FINVALUE 95–97 为元，429 为万元；不能对整行统一缩放。
- 95–97 是报告期累计利润字段，不是 230–237 的单季度字段。72 是包含少数股东权益的总权益，
  不能当作归母净资产。
- **不要把 `col95 == col96 + col97` 设为通用硬约束。** 兖矿能源的官方合并利润表另列
  “归属于母公司其他权益工具持有者的净利润”；两期原始数据中的差额已按此口径核实。
  不得把该差额直接填入少数股东损益，或修改归母值以强行配平。
- DAT 使用 float32。升级为 DataFrame 的 float64 不会恢复原来精度；核对要考虑源单位、
  披露舍入及 float32 舍入。零值也可能表示缺失。
- 对比不同期文件必须区分原报数与追溯调整后的比较数；SDK 的 `report_date` 不提供
  公告日/数据版本，不保证跨期自动形成同一重述口径，也不保证历史回测的时点可得性。

本轮已确认与仍待确认的样本、官方来源及文件摘要见
[财务数据口径核实记录](../local/financial-verification.md)。本轮没有回写或重算源财务数值。

## 04. 保存到文件

代码方式

```python
from tdxhub.affair import Affair

result = Affair.parse(downdir='output', filename='gpcw20170930.zip')

# 保存 csv 文件
result.to_csv('gpcw20170930.csv')

# 保存 Excel 文件
result.to_excel('gpcw20170930.xls')
```

命令行方式

写入到文件 : `gpcw20170930.csv`

```shell
tdxhub affair -f gpcw20000930.zip -o gpcw20170930.csv
```
