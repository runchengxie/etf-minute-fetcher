# etf-minute-fetcher

用 [AKShare](https://akshare.akfamily.xyz/) 抓取 ETF 分钟级行情，并落盘为与现有
日线数据结构对齐的 **`trade_date` 分区 parquet**。项目数据默认放在
`~/data/etf-minute-fetcher/minute/`，不与 `market-data-platform` 的正式数据目录混用。

数据来源优先使用东方财富，通过 AKShare 的 `fund_etf_hist_min_em` 接口拉取。
如果 AKShare 内部的 Python `requests` 被代理断开，下载器会在重试后使用系统
`curl` 直连东方财富；5/15/30/60 分钟周期还会继续回退到新浪历史分钟接口。

## 重要限制

- **1 分钟数据只提供最近 5 个交易日**。这是 AKShare/东方财富上游限制，不能用这个接口做长期 1 分钟历史回填。
- `5/15/30/60` 分钟周期可以查询更长区间。东方财富不可用时，新浪回退会返回其允许的最近一批 K 线，实测单次约 5000 根；新浪响应没有成交额，因此这些回退数据的 `amount` 为空。
- 下载器会把一只 ETF 的日期区间合并成一次上游请求，再按 `trade_date` 拆分落盘，避免逐日重复下载同一份近 5 日数据。
- 裸代码会按 AKShare 当前市场规则补后缀：`5/6` 开头 -> `.SH`，其余 -> `.SZ`。生产任务仍建议显式写完整 `ts_code`。
- `--universe cn-etf` 默认使用 `ak.fund_etf_spot_em()` 获取当前沪深 ETF；指定 `--as-of YYYYMMDD` 时改用 AKShare/同花顺的历史 ETF 快照，避免直接拿当前列表回填历史数据造成幸存者偏差。
- 批量下载默认使用 4 个 worker，并以每秒启动 2 个 ETF 任务做粗粒度限速。单只 ETF 内部仍可能执行 AKShare/东方财富/新浪自己的重试，因此这不是 HTTP 请求级限流器。

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

当 `period` 为 `5/15/30/60` 且东方财富不可用时，命令会自动尝试新浪历史分钟接口；`amount` 为空属于该回退源的字段限制，不代表 OHLC 或成交量缺失。

## 下载

抓取最近 5 个自然日窗口内可获得的 1 分钟数据：

```bash
etf-min \
  --symbols 512880.SH,159993.SZ \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

从目标文件读取：

```bash
etf-min \
  --symbols-file symbols_target.txt \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

下载当前沪深全市场 ETF：

```bash
etf-min \
  --universe cn-etf \
  --days 5 \
  --workers 4 \
  --rate-limit 2 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

默认会在输出目录维护：

```text
.download-checkpoint.json
.download-summary.json
```

checkpoint 记录逐 ETF 完成/失败状态。命令中断后以相同 `period`、日期范围和输出目录重新执行，会跳过已经成功完成的 ETF；使用 `--no-resume` 可忽略 checkpoint。失败 ETF 会进入下一轮重试队列，轮次数由 `--symbol-attempts` 控制。可用 `--checkpoint` 和 `--stats-file` 改写两个 JSON 的位置。

按交易所和名称筛选：

```bash
etf-min \
  --universe cn-etf \
  --exchange SH \
  --name-contains 红利 \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

按历史时点获取当时存在的 ETF universe：

```bash
etf-min \
  --universe cn-etf \
  --as-of 20240620 \
  --fund-type 股票型 \
  --start 20240620 \
  --end 20240620 \
  --period 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_5m
```

`--symbols`、`--symbols-file` 和 `--universe` 可以组合使用；最终标的会按规范化后的 `ts_code` 去重。
`--exchange`、`--name-contains`、`--fund-type`、`--as-of` 只用于筛选 `--universe` 自动发现的标的。

指定区间：

```bash
etf-min \
  --symbols 512880.SH \
  --start 20260820 \
  --end 20260824 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

对于 `period=1`，如果 `--start` 超出最近 5 个交易日，上游不会返回那些旧日期，CLI 会把它们统计为 `empty`。本次完全没有写入或跳过任何数据分区时，CLI 返回非零状态码，避免“什么都没下到但退出码还是成功”的尴尬场面。

## Universe 设计

CLI 的标的输入统一经过 universe 层，最终产出标准化 `Instrument`：

- `ExplicitUniverse`：处理 `--symbols`。
- `FileUniverse`：处理 `--symbols-file`。
- `AkshareETFUniverse`：默认通过 `fund_etf_spot_em()` 发现当前沪深 ETF；使用 `--as-of` 或 `--fund-type` 时通过 `fund_etf_spot_ths()` 获取可按日期查询、带基金类型的快照。

这层负责“下载哪些标的”。`--as-of` 提供 point-in-time membership，解决历史回测直接使用当前 ETF 列表的幸存者偏差问题。精确官方上市/退市日期目前没有从沪深两市获得对称、稳定的 AKShare 元数据，因此本项目暂不伪造这两个字段；后续可单独接入交易所生命周期元数据源。

## DownloadEngine

`DownloadEngine` 负责批量任务调度，当前提供：

- 有界线程池并发；
- ETF 任务启动级限速；
- 失败 ETF 重试队列；
- 原子写入 checkpoint；
- 中断后的全量任务恢复；
- 最终批量统计 JSON 持久化。

分钟源内部仍保留自己的请求级重试和 fallback。后续 Provider 抽象完成后，可以把更细粒度的 HTTP 限速下沉到具体 Provider。

## 网络要求

AKShare 的 ETF 分钟接口当前访问：

```text
https://push2his.eastmoney.com/api/qt/stock/trends2/get
```

如果本机出网经过代理而东方财富不可达，需要让对应域名直连。例如 mihomo：

```text
DOMAIN-SUFFIX,push2his.eastmoney.com,DIRECT
DOMAIN-SUFFIX,quote.eastmoney.com,DIRECT
DOMAIN-SUFFIX,money.finance.sina.com.cn,DIRECT
```

下载器的直连回退路径依赖系统已安装 `curl`。正常情况下仍优先使用 AKShare；只有
AKShare 连续请求失败时才会调用 `curl --noproxy '*'`，因此不会改变已有可用环境的
请求路径。新浪回退只对 `5/15/30/60` 周期启用；当前没有可用的新浪 1 分钟历史
回退。

## 数据发布

抓取代码和配置入 Git；落盘行情数据默认不入库，需要共享时单独管理。
