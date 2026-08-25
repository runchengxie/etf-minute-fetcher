# etf-minute-fetcher

一个用于下载沪深 ETF 分钟行情并保存为 Parquet 的小型工具。

项目目前支持：

- 下载指定 ETF、代码文件或自动发现的沪深 ETF 集合
- 抓取 `1/5/15/30/60` 分钟行情
- AKShare 失败或返回空数据时依次尝试东方财富直连和新浪历史分钟接口
- 按 ETF 和交易日写入 Parquet 分区
- 批量并发、任务启动限速、失败重试和断点续传
- 按交易所、名称、基金类型和历史日期筛选 ETF
- 用 `etf-min-check` 检查在线数据链路和返回字段

项目只负责标的选择、分钟行情抓取、数据规范化和落盘。指标、策略、回测和前端展示由下游项目处理。

## 使用前先了解两个限制

- `1` 分钟数据受上游限制，通常只能获取最近 5 个交易日。项目无法用公开接口补出长期 1 分钟历史。
- `5/15/30/60` 分钟数据可追溯范围由上游实际返回决定。新浪回退源没有成交额，因此 `amount` 会为空。

更详细的范围说明见[数据可用范围](docs/data-availability.md)。

## 快速开始

### 1. 安装

项目需要 Python 3.11 或更高版本，推荐使用 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
```

还没有安装 uv 时，可以先执行：

```bash
python -m pip install uv
```

### 2. 下载一只 ETF

下面的命令下载 `512880.SH` 最近 5 个自然日内可获得的 1 分钟数据：

```bash
uv run etf-min \
  --symbols 512880.SH \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

推荐使用带交易所后缀的完整代码：

```text
512880.SH   # 上交所
159915.SZ   # 深交所
```

也可以输入裸 6 位代码。项目会按当前规则推断交易所，`5` 或 `6` 开头归到上交所，其余归到深交所。长期任务建议显式写完整 `ts_code`，避免未来代码规则变化带来歧义。

### 3. 查看结果

目录结构如下：

```text
~/data/etf-minute-fetcher/minute/fund_min_1m/
└── 512880.SH/
    └── trade_date=20260824/
        └── part.parquet
```

用 pandas 读取：

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

每个分区固定包含这些字段：

```text
ts_code
trade_time
open
high
low
close
vol
amount
```

## 选择要下载的 ETF

### 直接指定代码

```bash
uv run etf-min \
  --symbols 512880.SH,510300.SH,159915.SZ \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

### 从文件读取

代码文件每行一个 ETF。空行和 `#` 开头的注释会被忽略：

```text
# 红利类 ETF
512880.SH
159915.SZ
```

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

### 自动发现沪深 ETF

```bash
uv run etf-min \
  --universe cn-etf \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

可以继续按交易所、名称或基金类型筛选：

```bash
uv run etf-min \
  --universe cn-etf \
  --exchange SH \
  --name-contains 红利 \
  --days 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

### 按历史日期选择 ETF

`--as-of YYYYMMDD` 使用指定日期的 ETF 历史快照：

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

这种方式可以降低直接用当前 ETF 列表回填历史数据造成的幸存者偏差。当前项目没有独立的 `list_date` 和 `delist_date` 生命周期数据源，因此历史快照不能替代完整的上市退市元数据。

## 日期和周期

指定日期区间：

```bash
uv run etf-min \
  --symbols 512880.SH \
  --start 20260820 \
  --end 20260824 \
  --period 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_5m
```

日期格式为 `YYYYMMDD`。`--period` 可选 `1`、`5`、`15`、`30`、`60`。

未指定 `--start` 时，程序会用 `--days` 从 `--end` 向前计算自然日范围。默认 `--days 5`。周末和节假日仍会出现在目标日期列表中，上游没有返回数据的日期会记为 `empty`。

## 数据源回退顺序

默认使用 `FallbackMinuteProvider`，顺序如下：

1. `AkshareMinuteProvider`
2. `EastMoneyCurlMinuteProvider`
3. `SinaCurlMinuteProvider`，仅用于 `5/15/30/60` 分钟

AKShare 抛出异常或返回空表时会进入下一层。东方财富直连仍然失败，或者较长周期没有返回目标区间数据时，再尝试新浪。

各数据源按完整结果切换，当前不会自动拼接多个来源的局部时间窗口。新浪不提供成交额，落盘时 `amount` 保持为空。

## 批量下载和断点续传

批量任务默认使用 4 个并发任务，每秒最多启动 2 个 ETF 任务。程序会在输出目录写入：

```text
.download-checkpoint.json
.download-summary.json
```

相同的周期、日期范围、输出目录和覆盖策略可以复用断点状态。已经成功的 ETF 会跳过。

常用调度参数：

```bash
uv run etf-min \
  --universe cn-etf \
  --workers 4 \
  --rate-limit 2 \
  --symbol-attempts 3 \
  --retry-delay 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

`--rate-limit` 限制 ETF 任务的启动速度。一次 ETF 任务内部仍可能发生 AKShare 重试或数据源切换，因此它不代表统一的 HTTP 请求速率上限。

需要重新调度所有 ETF 时使用 `--no-resume`。需要覆盖已有交易日分区时再加 `--no-skip`：

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --no-resume \
  --no-skip \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

`--no-skip` 会改变断点文件绑定的覆盖策略。已有断点使用其他覆盖策略时，程序会拒绝复用，避免成功状态把本应重抓的 ETF 直接跳过。

完整参数见[命令行参考](docs/cli-reference.md)。

## 下载前检查数据链路

```bash
uv run etf-min-check --symbol 512880.SH --period 1
```

健康检查会验证网络请求、返回行数、交易日期、时间范围和字段结构。它会分别统计价格与成交量字段空值，以及 `amount` 空值。新浪回退数据允许 `amount` 为空。

失败时先看[故障排查](docs/troubleshooting.md)。

## 开发和质量检查

安装开发依赖：

```bash
uv sync --extra dev
```

本地建议依次运行：

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --cov=etf_minute_fetcher --cov-report=term-missing
uv run pip-audit
uv build
```

CI 会执行相同的静态检查、类型检查、依赖审计和构建，并在 Python 3.11 与 3.14 上运行测试。覆盖率下限为 80%。

## 文档导航

- [命令行参考](docs/cli-reference.md)：参数、默认值和常见组合
- [数据可用范围](docs/data-availability.md)：周期、历史窗口、空数据和数据源限制
- [架构](docs/architecture.md)：标的选择、调度、行情源和存储职责
- [故障排查](docs/troubleshooting.md)：网络、curl、断点文件和空数据问题
- [仪表盘接入](docs/dashboard-integration.md)：其他项目如何读取 Parquet
- [开发约定](AGENTS.md)：代码、测试、文档和提交前检查要求

## 数据目录和项目边界

建议把生成的数据放在 `~/data/etf-minute-fetcher/` 或其他独立数据目录。Parquet、断点文件和统计文件不应提交到 Git。

当前仓库没有 Git submodule。文档中提到的仪表盘或数据平台都属于外部项目，本仓库不依赖它们完成安装、测试和分钟数据下载。
