# etf-minute-fetcher

一个把中国沪深 ETF 分钟行情下载为 Parquet 文件的小工具。

它适合两类场景：

- 临时下载几只 ETF，做研究或检查行情；
- 批量下载当前 ETF universe，并用 checkpoint 断点续传。

项目使用 AKShare 获取行情，必要时回退到东方财富和新浪的直连接口。输出按 ETF 和交易日分区保存，方便 pandas、DuckDB、Polars 或 Dashboard 继续读取。

## 先了解两个限制

- `1` 分钟数据受上游限制，通常只能获取最近 5 个交易日；它不是长期 1 分钟历史库。
- `5/15/30/60` 分钟数据的可用历史范围取决于上游接口。回退源可能返回较短窗口，新浪回退不提供成交额。

更完整的数据范围说明见[数据可用范围](docs/data-availability.md)。

## 30 秒开始

### 1. 安装

项目需要 Python 3.11 或更高版本，并推荐使用 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
```

如果还没有安装 uv，可以先执行：

```bash
python -m pip install uv
```

### 2. 下载一只 ETF

下面的例子下载 512880.SH 最近 5 个自然日内可获得的 1 分钟数据：

```bash
uv run etf-min \
  --symbols 512880.SH \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

代码建议写成带交易所后缀的形式：

```text
512880.SH   # 上交所
159915.SZ   # 深交所
```

裸代码也可以使用，但项目需要根据代码规则推断交易所。生产任务建议始终写完整的 `ts_code`。

### 3. 查看结果

下载目录类似这样：

```text
~/data/etf-minute-fetcher/minute/fund_min_1m/
└── 512880.SH/
    └── trade_date=20260824/
        └── part.parquet
```

用 Python 读取：

```python
from pathlib import Path

import pandas as pd

path = (
    Path("~/data/etf-minute-fetcher/minute/fund_min_1m").expanduser()
    / "512880.SH/trade_date=20260824/part.parquet"
)
frame = pd.read_parquet(path)
print(frame.head())
```

标准字段是：`ts_code`、`trade_time`、`open`、`high`、`low`、`close`、`vol`、`amount`。

## 常用操作

### 下载多只 ETF

```bash
uv run etf-min \
  --symbols 512880.SH,510300.SH,159915.SZ \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

### 从文件读取代码

`symbols.txt` 每行一个代码，空行和 `#` 开头的注释会被忽略：

```text
# dividend ETFs
512880.SH
159915.SZ
```

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

### 自动发现 ETF

下载当前沪深 ETF：

```bash
uv run etf-min \
  --universe cn-etf \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

也可以按交易所、名称或基金类型筛选：

```bash
uv run etf-min \
  --universe cn-etf \
  --exchange SH \
  --name-contains 红利 \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

按历史时点选择当时的 ETF universe：

```bash
uv run etf-min \
  --universe cn-etf \
  --as-of 20240620 \
  --fund-type 股票型 \
  --start 20240620 \
  --end 20240620 \
  --period 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_5m
```

`--as-of` 使用历史快照降低幸存者偏差，但它不是独立的官方上市/退市生命周期表。详见[数据可用范围](docs/data-availability.md)。

### 下载指定日期区间或其他周期

```bash
uv run etf-min \
  --symbols 512880.SH \
  --start 20260820 \
  --end 20260824 \
  --period 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_5m
```

日期格式是 `YYYYMMDD`，`period` 可选 `1`、`5`、`15`、`30`、`60`。

## 批量下载和断点续传

批量任务默认使用 4 个 worker、每秒启动 2 个 ETF 任务，并在输出目录写入：

```text
.download-checkpoint.json
.download-summary.json
```

任务中断后，用相同的日期范围、周期和输出目录重新执行即可恢复；已经成功的 ETF 会跳过。常用调度参数：

```bash
uv run etf-min \
  --universe cn-etf \
  --workers 4 \
  --rate-limit 2 \
  --symbol-attempts 3 \
  --retry-delay 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

完整参数说明见[命令行参考](docs/cli-reference.md)。

## 下载前检查上游

真实下载前，可以先检查 AKShare、网络和返回 schema：

```bash
uv run etf-min-check --symbol 512880.SH
```

如果失败，先看[故障排查](docs/troubleshooting.md)。

## 开发和测试

```bash
uv sync --extra dev
uv run pytest
```

## 文档导航

- [命令行参考](docs/cli-reference.md)：所有参数和组合方式。
- [数据可用范围](docs/data-availability.md)：周期、历史窗口、空分区和数据源限制。
- [架构](docs/architecture.md)：Universe、DownloadEngine、Provider 和 Storage 的职责。
- [故障排查](docs/troubleshooting.md)：网络、curl、checkpoint 和空数据问题。
- [Dashboard 接入](docs/dashboard-integration.md)：如何让其他项目读取 Parquet。

## 数据目录约定

行情数据默认建议放在 `~/data/etf-minute-fetcher/` 下，不要直接提交到 Git。代码、配置和文档入库，生成的 Parquet、checkpoint 和统计文件按项目需要单独备份。
