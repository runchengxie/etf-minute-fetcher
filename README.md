# ETF Minute Fetcher

一个把沪深 ETF 分钟行情下载为 Parquet 的小工具。

如果你只想开始下载，按下面三步即可；数据源、回退规则、完整参数和故障排查都放在 [`docs/`](docs/README.md) 中。

## 快速开始

项目需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
# 安装依赖
uv sync

# 可选：先检查上游接口
uv run etf-min-check --symbol 510050.SH

# 下载最近 5 个自然日内可获得的 1 分钟数据
uv run etf-min \
  --symbols 510050.SH \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

代码建议带交易所后缀：

```text
510050.SH   # 上交所
159915.SZ   # 深交所
```

## 常用下载方式

下载多只 ETF：

```bash
uv run etf-min \
  --symbols 510050.SH,512880.SH,159915.SZ \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

从文件读取代码：

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

自动发现当前沪深 ETF：

```bash
uv run etf-min \
  --universe cn-etf \
  --exchange SH \
  --name-contains 红利 \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

下载其他周期或指定日期：

```bash
uv run etf-min \
  --symbols 510050.SH \
  --period 15 \
  --start 20250501 \
  --end 20260825 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_15m
```

支持的周期是 `1`、`5`、`15`、`30`、`60` 分钟。完整参数见[命令行参考](docs/cli-reference.md)。

## 输出结果

默认按 ETF 和交易日分区：

```text
<out>/
└── 510050.SH/
    └── trade_date=20260825/
        └── part.parquet
```

Parquet 字段：`ts_code`、`trade_time`、`open`、`high`、`low`、`close`、`vol`、`amount`。

批量任务还会在输出目录保存 `.download-checkpoint.json` 和 `.download-summary.json`，支持中断后继续执行。

## 使用前请注意

- `1` 分钟公开接口通常只能提供最近 5 个交易日，不适合直接做多年历史回填。
- 其他周期的历史范围由上游实际返回决定；新浪回退数据可能没有 `amount`。
- `--as-of` 可以选择历史 ETF 快照，但不是独立的上市/退市生命周期表。
- 数据是否完整应检查实际交易日分区，不能只看命令是否成功退出。

详细说明见[数据可用范围](docs/data-availability.md)。

## 文档

- [文档目录](docs/README.md)
- [命令行参考](docs/cli-reference.md)
- [数据可用范围](docs/data-availability.md)
- [架构](docs/architecture.md)
- [故障排查](docs/troubleshooting.md)
- [Dashboard 接入](docs/dashboard-integration.md)

## 开发

```bash
uv sync --extra dev
uv run pytest
```

本项目只负责行情抓取和 Parquet 落盘，不构成投资建议。
