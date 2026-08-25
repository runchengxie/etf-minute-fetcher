# 命令行参考

项目提供两个命令：

```bash
uv run etf-min --help
uv run etf-min-check --help
```

## `etf-min`

### 选择 ETF

至少需要提供一种标的来源。可以组合多个来源，程序会把代码标准化为 `ts_code` 后去重。

| 参数 | 说明 |
| --- | --- |
| `--symbols CODE1,CODE2` | 逗号分隔的 ETF 代码，例如 `512880.SH,159915.SZ` |
| `--symbols-file PATH` | 每行一个代码，空行和 `#` 开头的注释会忽略 |
| `--universe cn-etf` | 自动发现当前沪深 ETF |
| `--exchange SH/SZ` | 只保留指定交易所，需要与 `--universe` 一起使用 |
| `--name-contains TEXT` | 按名称包含关系筛选，需要与 `--universe` 一起使用 |
| `--fund-type TEXT` | 按基金类型精确筛选，需要与 `--universe` 一起使用 |
| `--as-of YYYYMMDD` | 使用指定日期的历史 ETF 快照，需要与 `--universe` 一起使用 |

推荐使用 `512880.SH` 这样的完整代码。裸 6 位代码会按当前规则推断交易所。

`--as-of` 和 `--fund-type` 会使用带查询日期的 ETF 历史快照。项目当前没有独立的上市退市生命周期表，历史快照只能作为历史标的范围的一项依据。

### 日期和周期

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `--start YYYYMMDD` | 由 `--days` 推导 | 起始日期，包含当天 |
| `--end YYYYMMDD` | 今天 | 结束日期，包含当天 |
| `--days N` | `5` | 未指定 `--start` 时，从 `--end` 向前覆盖的自然日数 |
| `--period` | `1` | 分钟粒度，可选 `1`、`5`、`15`、`30`、`60` |

同时指定 `--start` 和 `--end` 后，`--days` 不参与日期计算。目标日期按自然日生成，周末和节假日也会进入列表。上游没有返回数据的日期会记为 `empty`。

### 输出和调度

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `--out PATH` | 必填 | 输出根目录 |
| `--workers N` | `4` | 最大并发 ETF 任务数 |
| `--rate-limit N` | `2` | 每秒最多启动的 ETF 任务数，`0` 表示不限速 |
| `--symbol-attempts N` | `2` | 单只 ETF 的批量级最大尝试轮数 |
| `--retry-delay N` | `2` | 重试轮次之间的基础等待秒数 |
| `--checkpoint PATH` | `<out>/.download-checkpoint.json` | 断点文件位置 |
| `--stats-file PATH` | `<out>/.download-summary.json` | 下载汇总文件位置 |
| `--no-resume` | 关闭 | 忽略已有断点状态，重新调度所有 ETF |
| `--no-skip` | 关闭 | 对本次已调度 ETF 覆盖已有交易日分区 |

`--rate-limit` 作用在 ETF 任务启动处。单个任务内部仍可能发生 AKShare 重试或切换数据源，因此这个值不能直接换算成 HTTP 请求总速率。

断点文件会绑定以下信息：

- `period`
- 目标日期列表
- 输出目录
- 是否跳过已有分区

改变其中任意一项后，旧断点不会继续复用。完整重抓通常同时使用 `--no-resume` 和 `--no-skip`。

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

下载当前沪深 ETF，并筛选上交所名称中包含红利的 ETF：

```bash
uv run etf-min \
  --universe cn-etf \
  --exchange SH \
  --name-contains 红利 \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

重新调度并覆盖已有分区：

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --no-resume \
  --no-skip \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

### 退出码

| 退出码 | 含义 |
| ---: | --- |
| `0` | 任务完成，并且至少写入或跳过一个分区 |
| `1` | 至少一只 ETF 最终失败 |
| `2` | 参数、断点文件或本地文件错误 |
| `3` | 任务完成，但没有写入或跳过任何数据分区 |

## `etf-min-check`

这是在线健康检查，不写入 Parquet：

```bash
uv run etf-min-check \
  --symbol 512880.SH \
  --period 1 \
  --lookback-days 14
```

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `--symbol` | `512880.SH` | 用于探测的 ETF |
| `--period` | `1` | 分钟粒度 |
| `--lookback-days` | `14` | 向前探测的自然日数 |

健康检查会通过默认数据源链路抓取数据，并检查行数、交易日期、时间范围和固定字段。价格与成交量字段的空值会计入 `core_nulls`，成交额空值单独计入 `amount_nulls`。新浪回退数据出现 `amount_nulls` 属于已知数据源限制。
