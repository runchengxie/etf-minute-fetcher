# 故障排查

## 先运行健康检查

```bash
uv run etf-min-check --symbol 512880.SH --period 1
```

健康检查会走项目默认的数据源链路，并验证返回字段和时间范围。它需要访问上游网络。

全市场任务出现问题时，先用一只 ETF 和较短日期范围复现。直接拿几百只 ETF 压接口，只会让网络问题、限流和代码问题混在一起，排查成本迅速膨胀。

## `uv` 或依赖安装失败

确认 Python 版本：

```bash
python --version
```

项目需要 Python 3.11 或更高版本。

重新同步运行依赖：

```bash
uv sync --reinstall
```

开发环境需要安装额外的质量检查工具：

```bash
uv sync --extra dev
```

如果 `uv sync --locked` 提示锁文件与 `pyproject.toml` 不一致，说明依赖声明发生了变化但 `uv.lock` 没有同步更新。维护者应运行 `uv lock` 并提交新的锁文件。

## AKShare 请求失败

默认链路会先尝试 AKShare。AKShare 抛出异常或返回空表后，项目会继续尝试东方财富 curl 直连。`5/15/30/60` 分钟下，后续还可以尝试新浪。

先确认系统存在 curl：

```bash
curl --version
```

再检查东方财富接口能否连通：

```bash
curl --noproxy '*' --max-time 15 \
  'https://push2his.eastmoney.com/api/qt/stock/trends2/get'
```

项目的 curl 回退依赖系统可执行文件。系统没有 curl 时，对应的直连回退无法工作。

## 代理导致连接中断

某些环境把 Python 请求和 curl 都导向代理，公开行情接口可能因此断开或返回异常。

常见相关域名包括：

```text
push2his.eastmoney.com
quote.eastmoney.com
money.finance.sina.com.cn
```

如果网络环境要求这些域名直连，应在系统或代理工具中配置。仓库本身不写死用户代理规则，也不应该为了某台机器的网络配置在代码里加入全局代理副作用。

## 下载完成但没有数据

常见原因包括：

1. `1` 分钟请求已经超出最近 5 个交易日的上游窗口
2. 日期落在周末或节假日
3. ETF 代码、交易所后缀或日期格式错误
4. ETF 在目标日期尚未上市或已经停止交易
5. 上游当前没有返回目标日期数据
6. 公开接口发生临时限流或字段变化

先缩小到单只 ETF 和最近日期：

```bash
uv run etf-min \
  --symbols 512880.SH \
  --days 3 \
  --period 1 \
  --out /tmp/etf-minute-smoke
```

如果命令以退出码 `3` 结束，说明本次没有写入或跳过任何分区。查看[数据可用范围](data-availability.md)确认请求日期是否仍在公开接口可用范围内。

## 健康检查显示 `amount_nulls`

新浪历史分钟接口没有成交额。使用新浪回退结果时，`amount` 为空属于已知限制。

健康检查会把价格和成交量空值统计为 `core_nulls`，把成交额空值单独统计为 `amount_nulls`。重点关注 `core_nulls` 是否异常增加，同时结合数据源限制判断 `amount_nulls`。

## 断点文件提示条件不匹配

断点文件绑定：

```text
period
trade_dates
output_dir
skip_existing
```

修改周期、日期范围、输出目录或覆盖策略后，程序会拒绝复用旧断点。

可以采用以下处理方式：

- 使用新的 `--checkpoint` 路径
- 移动或删除旧断点文件
- 使用 `--no-resume` 重新调度全部 ETF

需要完整重抓并覆盖已有分区时，通常同时使用：

```bash
uv run etf-min \
  --symbols-file symbols.txt \
  --no-resume \
  --no-skip \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

不要把不同日期范围或不同输出目录生成的断点内容手工拼在一起。断点文件属于任务状态，不适合作为长期业务数据编辑。

## 全市场任务失败较多

先降低并发和任务启动速度：

```bash
uv run etf-min \
  --universe cn-etf \
  --workers 2 \
  --rate-limit 1 \
  --symbol-attempts 3 \
  --retry-delay 5 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

`--rate-limit` 只控制 ETF 任务启动。每个任务内部仍可能产生多次网络请求，因此把它设成 `2` 并不代表整个进程严格限制为每秒两个 HTTP 请求。

频繁出现上游限流时，优先降低 `--workers` 和 `--rate-limit`。继续提高重试次数通常只会延长拥堵。

## Parquet 读取失败

确认读取的是实际文件：

```text
<root>/<ts_code>/trade_date=YYYYMMDD/part.parquet
```

示例：

```python
from pathlib import Path

import pandas as pd

path = (
    Path("~/data/etf-minute-fetcher/minute/fund_min_1m").expanduser()
    / "512880.SH/trade_date=20260824/part.parquet"
)
frame = pd.read_parquet(path)
```

如果 pandas 无法读取，确认已经安装 `pyarrow`，并检查目标文件是否来自完整下载结果。

项目采用临时文件加原子替换，正常写入路径可以降低留下半成品 Parquet 的概率。手工复制、磁盘故障或外部程序修改仍可能造成文件损坏。

## 测试通过但 CI 失败

本地提交前运行与 CI 对齐的命令：

```bash
uv sync --locked --extra dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check
uv run --locked pytest -q --cov=etf_minute_fetcher --cov-report=term-missing
uv run --locked pip-audit
uv build
```

测试任务会覆盖 Python 3.11 和 3.14。只在本机当前 Python 版本上运行 pytest，仍可能遗漏版本兼容问题。

## 上游字段变化

如果错误集中出现字段缺失、列数变化或解析失败，先确认是否属于第三方接口变更。行情适配逻辑集中在 `providers.py`，修复时应补充一个最小响应样本测试，避免把新的第三方格式假设散落到 CLI 或调度代码中。
