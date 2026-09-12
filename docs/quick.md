# 快速上手

## 使用最快的服务器

```shell
python -m tdxhub bestip -vv
```

## 离线数据读取

```python
from tdxhub.reader import Reader

# market: 参数 `std` 为标准市场(就是股票), `ext` 为扩展市场(期货，黄金等)
# tdxdir: 是通达信的数据目录, 根据自己的情况修改

reader = Reader.factory(market='std', tdxdir='C:/new_tdx')

# 读取日线数据
reader.daily(symbol='600036')

# 读取分钟数据
reader.minute(symbol='600036')

# 读取时间线数据
reader.fzline(symbol='600036')
```

## 线上行情读取

```python

from tdxhub.quotes import Quotes

# 标准市场
client = Quotes.factory(market='std', multithread=True, heartbeat=True, bestip=True, timeout=15)

# k 线数据
client.bars(symbol='600036', frequency=9, offset=10)

# 指数
client.index(symbol='000001', frequency=9)

# 当日分时；返回 datetime 列及同名 DatetimeIndex
# 标准 240 点对应 09:31～11:30、13:01～15:00
client.minute(symbol='000001')

```

## 财务数据读取

```python

from tdxhub.affair import Affair

# 远程文件列表
files = Affair.files()

# 下载单个
Affair.fetch(downdir='tmp', filename='gpcw19960630.zip')

# 下载全部
Affair.fetch(downdir='tmp')
```
