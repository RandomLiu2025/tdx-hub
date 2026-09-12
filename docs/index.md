# 项目概述

`tdxhub` 是一款面向 Python 3.11+ 的通达信本地数据、行情和财务数据工具包。

- 在线文档: [https://www.tdxhub.com](https://www.tdxhub.com)
- 国内镜像: [https://gitee.com/ibopo/tdxhub](https://gitee.com/ibopo/tdxhub)
- 项目仓库: [https://github.com/RandomLiu2025/tdx-hub](https://github.com/RandomLiu2025/tdx-hub)

## 项目特点

- 基于 `tdxpy` 二次封装。
- 支持 Python `3.11+`
- 支持全平台 `Windows / MacOS / Linux`
- 更加友好的API接口
- 自动匹配最优服务器

## 运行环境

- 操作系统: `Windows / MacOS / Linux` 都可以运行.
- Python: `3.11` 以及以上版本.
- 依赖库: `tdxpy>=0.2.7,<1`

## 快速安装

```shell
pip install -U tdxhub-sdk
```

## 多种运行

我们提供了方便命令行调试和导出数据的命令行工具。

## 迁移能力

- [Go tdx 迁移使用指南](api/migration.md)：GBBQ、官方文件、退市、Pull/SQLite、可选 HTTP 服务及当前限制。

## 设计文档

- [Go tdx 能力迁移到 tdxhub](design/202609101744-port-go-data-capabilities.md)
