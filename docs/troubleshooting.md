# 故障排查

## 第一步：运行健康检查

```bash
uv run etf-min-check --symbol 512880.SH --period 1
```

如果健康检查失败，先不要直接启动全市场下载。先确认 Python 依赖、网络和 curl。

## `uv` 或依赖安装失败

确认 Python 版本：

```bash
python --version
```

项目需要 Python 3.11+。重新同步依赖：

```bash
uv sync --reinstall
```

开发环境再安装测试依赖：

```bash
uv sync --extra dev
```

## AKShare 请求失败或代理断开

默认会先重试 AKShare，再尝试东方财富 curl。检查：

```bash
curl --version
curl --noproxy '*' --max-time 15 \
  'https://push2his.eastmoney.com/api/qt/stock/trends2/get'
```

如果网络经过代理，通常需要让下面的域名直连：

```text
push2his.eastmoney.com
quote.eastmoney.com
money.finance.sina.com.cn
```

curl 回退依赖系统 curl；没有 curl 时，AKShare 失败后无法使用对应的直连回退。

## 下载成功但没有数据

常见原因：

1. `1` 分钟请求超出了上游最近 5 个交易日的窗口；
2. 日期落在周末或节假日；
3. ETF 代码、交易所后缀或日期格式错误；
4. 上游返回了空结果或临时限流。

先用最近日期和单只 ETF 重试：

```bash
uv run etf-min \
  --symbols 512880.SH \
  --days 3 \
  --period 1 \
  --out /tmp/etf-minute-smoke
```

## checkpoint 报日期范围不匹配

checkpoint 会绑定 `period`、日期范围和输出目录。你修改了这些参数后，项目会拒绝复用旧 checkpoint。

可选处理方式：

- 指定新的 `--checkpoint` 路径；
- 删除或移动旧 checkpoint；
- 使用 `--no-resume` 忽略已有状态。

不要为了绕过错误，把不同日期范围的 checkpoint 复制到一起。

## 全市场任务太慢或失败较多

先降低规模验证单只 ETF，再逐步增加并发：

```bash
uv run etf-min \
  --universe cn-etf \
  --workers 2 \
  --rate-limit 1 \
  --symbol-attempts 3 \
  --out ~/data/etf-minute-fetcher/minute/fund_min_1m
```

`--rate-limit` 限制的是 ETF 任务启动速度，不是所有底层 HTTP 请求的统一 quota；并发过高仍可能触发上游限流。

## 读取 Parquet 失败

确认读取的是 `part.parquet`，而不是交易日目录本身：

```python
import pandas as pd

path = "~/data/etf-minute-fetcher/minute/fund_min_1m/512880.SH/trade_date=20260824/part.parquet"
frame = pd.read_parquet(path)
```

如果使用 pandas 读取失败，确认已经安装 `pyarrow`，并检查文件是否在下载过程中被中断。
