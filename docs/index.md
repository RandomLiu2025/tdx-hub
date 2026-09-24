# 项目概述

`tdxhub` 是一款面向 Python 3.11+ 的通达信本地数据、行情和财务数据工具包。

- 项目仓库: [https://github.com/RandomLiu2025/tdx-hub](https://github.com/RandomLiu2025/tdx-hub)

## 项目特点

- `tdxhub/tdx` 内置基于 `tdxpy 0.2.7` 的纯 Python 协议与文件读取实现，由本项目维护。
- 支持 Python `3.11+`
- 支持全平台 `Windows / MacOS / Linux`
- 更加友好的API接口
- 自动匹配最优服务器

## 运行环境

- 操作系统: `Windows / MacOS / Linux` 都可以运行.
- Python: `3.11` 以及以上版本.
- 协议依赖: 无需安装外部 `tdxpy` / `pytdx` 或 Cython；其他依赖见 `pyproject.toml`。

## 快速安装

```shell
pip install -U tdxhub-sdk
```

## 多种运行

我们提供了方便命令行调试和导出数据的命令行工具。

## 设计文档
