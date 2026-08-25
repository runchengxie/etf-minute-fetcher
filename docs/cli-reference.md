# 命令行参考

项目提供两个命令：

```bash
uv run etf-min --help
uv run etf-min-check --help
```

## `etf-min`

### 标的选择

至少提供一种标的来源；多个来源可以组合，最终按标准化后的 `ts_code` 去重。

| 参数 | 说明 |
|---|---|
| `--symbols CODE1,CODE2` | 逗号分隔的 ETF 代码，例如 `512880.SH,159915.SZ` |
| `--symbols-file PATH` | 每行一个代码；空行和 `#` 注释会忽略 |
| `--universe cn-etf` | 自动发现当前沪深 ETF |
| `--exchange SH/SZ` | 只保留指定交易所；只能和 `--universe` 一起使用 |
| `--name-contains TEXT` | 按名称包含关系筛选；只能和 `--universe` 一起使用 |
| `--fund-type TEXT` | 按基金类型精确筛选；只能和 `--universe` 一起使用 |
| `--as-of YYYYMMDD` | 使用指定日期的历史 ETF 快照；只能和 `--universe` 一起使用 |

代码格式建议使用 `512880.SH` 这样的完整形式。裸代码会按当前项目规则推断交易所。

### 日期和周期

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--start YYYYMMDD` | 由 `--days` 推导 | 起始日期，包含当天 |
| `--end YYYYMMDD` | 今天 | 结束日期，包含当天 |
| `--days N` | `5` | 未指定 `--start` 时，从 `--end` 向前覆盖的自然日数 |
| `--period` | `1` | 分钟粒度，可选 `1`、`5`、`15`、`30`、`60` |

`--start` 和 `--end` 都指定时，`--days` 不参与计算。项目会保留自然日范围，但上游只会返回交易日数据。

### 输出和调度

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--out PATH` | 必填 | 输出根目录 |
| `--workers N` | `4` | 最大并发 ETF 任务数 |
| `--rate-limit N` | `2` | 每秒最多启动的 ETF 任务数；`0` 表示不限速 |
| `--symbol-attempts N` | `2` | 单个 ETF 的批量级尝试轮数 |
| `--retry-delay N` | `2` | 重试轮次之间的基础等待秒数 |
| `--checkpoint PATH` | `<out>/.download-checkpoint.json` | checkpoint 文件位置 |
| `--stats-file PATH` | `<out>/.download-summary.json` | 批量统计文件位置 |
| `--no-resume` | 关闭 | 忽略已有 checkpoint，重新调度成功过的 ETF |
| `--no-skip` | 关闭 | 不跳过已经存在的交易日分区 |

`--rate-limit` 当前限制的是 ETF 任务启动，不是每一次底层 HTTP 请求。单个 Provider 内部仍可能重试或切换数据源。

### 常用命令

下载几只 ETF：

```bash
uv run etf-min \
  --symbols 512880.SH,159915.SZ \
  --start 20260820 \
  --end 20260824 \
  --period 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_5m
```

下载当前全市场 ETF，并限制为上交所红利类 ETF：

```bash
uv run etf-min \
  --universe cn-etf \
  --exchange SH \
  --name-contains 红利 \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

忽略旧状态重新跑一遍：

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --no-resume \
  --no-skip \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

## `etf-min-check`

这是一个在线健康检查，不写入 Parquet：

```bash
uv run etf-min-check \
  --symbol 512880.SH \
  --period 1 \
  --lookback-days 14
```

它会检查 AKShare 版本、返回行数、交易日、时间范围和标准字段。该命令需要访问上游网络，因此不能在完全离线环境中使用。
