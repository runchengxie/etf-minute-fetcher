# etf-minute-fetcher

用 [AKShare](https://akshare.akfamily.xyz/) 抓取 ETF 分钟级行情，并落盘为与
`~/data/market-data-platform/assets/tushare/etf/daily` 对齐的 **`trade_date` 分区 parquet** 结构。

数据来源为东方财富，优先通过 AKShare 的 `fund_etf_hist_min_em` 接口拉取。
如果 AKShare 内部的 Python `requests` 被代理断开，下载器会在重试后自动使用
系统 `curl` 直连同一接口作为回退路径。

## 重要限制

- **1 分钟数据只提供最近 5 个交易日**。这是 AKShare/东方财富上游限制，不能用这个接口做长期 1 分钟历史回填。
- `5/15/30/60` 分钟周期可以查询更长区间，但仍受东方财富接口可用性约束。
- 下载器会把一只 ETF 的日期区间合并成一次上游请求，再按 `trade_date` 拆分落盘，避免逐日重复下载同一份近 5 日数据。
- 裸代码会按 AKShare 当前市场规则补后缀：`5/6` 开头 -> `.SH`，其余 -> `.SZ`。生产任务仍建议显式写完整 `ts_code`。

## 落盘结构

```text
<out>/
  512880.SH/
    trade_date=20260821/
      part.parquet
    trade_date=20260824/
      part.parquet
  159993.SZ/
    trade_date=20260824/
      part.parquet
```

列：

| 列 | 含义 |
|---|---|
| `ts_code` | 带后缀代码，如 `512880.SH` |
| `trade_time` | 分钟时间戳 |
| `open` / `high` / `low` / `close` | 分钟 OHLC |
| `vol` | 成交量 |
| `amount` | 成交额（元） |

## 安装

```bash
uv sync
```

开发/测试环境：

```bash
uv sync --extra dev
uv run pytest
```

项目当前要求 Python 3.11+，并以 AKShare `1.18.94+` 的接口行为为基线。

## 先检查上游是否活着

真实下载前建议先跑：

```bash
uv run etf-min-check
```

指定深市 ETF：

```bash
uv run etf-min-check --symbol 159993.SZ
```

成功时会打印 AKShare 版本、返回行数、实际交易日和时间范围。若网络、东方财富接口或 schema 异常，命令返回非零状态码。

## 下载

抓取最近 5 个自然日窗口内可获得的 1 分钟数据：

```bash
etf-min \
  --symbols 512880.SH,159993.SZ \
  --days 5 \
  --out ~/data/market-data-platform/assets/tushare/etf/minute/fund_min_1m
```

从目标文件读取：

```bash
etf-min \
  --symbols-file symbols_target.txt \
  --days 5 \
  --out ~/data/market-data-platform/assets/tushare/etf/minute/fund_min_1m
```

指定区间：

```bash
etf-min \
  --symbols 512880.SH \
  --start 20260820 \
  --end 20260824 \
  --out ~/data/market-data-platform/assets/tushare/etf/minute/fund_min_1m
```

对于 `period=1`，如果 `--start` 超出最近 5 个交易日，上游不会返回那些旧日期，CLI 会把它们统计为 `empty`。本次完全没有写入或跳过任何数据分区时，CLI 返回非零状态码，避免“什么都没下到但退出码还是成功”的尴尬场面。

## 网络要求

AKShare 的 ETF 分钟接口当前访问：

```text
https://push2his.eastmoney.com/api/qt/stock/trends2/get
```

如果本机出网经过代理而东方财富不可达，需要让对应域名直连。例如 mihomo：

```text
DOMAIN-SUFFIX,push2his.eastmoney.com,DIRECT
DOMAIN-SUFFIX,quote.eastmoney.com,DIRECT
```

下载器的直连回退路径依赖系统已安装 `curl`。正常情况下仍优先使用 AKShare；只有
AKShare 连续请求失败时才会调用 `curl --noproxy '*'`，因此不会改变已有可用环境的
请求路径。

## 数据发布

抓取代码和配置入 Git；落盘行情数据默认不入库，需要共享时单独管理。
