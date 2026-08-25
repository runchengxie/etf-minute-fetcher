# 架构

项目把“选择哪些 ETF、怎样调度、从哪里取分钟行情、如何落盘”拆成四个边界。CLI 只负责解析参数和组装组件。

```text
CLI
 │
 ▼
UniverseProvider
 ├─ ExplicitUniverse
 ├─ FileUniverse
 └─ AkshareETFUniverse
 │
 ▼
DownloadEngine
 │  有界并发 / 任务启动级限速 / 重试队列 / checkpoint
 │
 ▼
fetch_symbol_range()
 ├─ MinuteDataProvider
 │  └─ FallbackMinuteProvider
 │      ├─ AkshareMinuteProvider
 │      ├─ EastMoneyCurlMinuteProvider
 │      └─ SinaCurlMinuteProvider
 │
 └─ BarStorage
    └─ ParquetBarStorage
```

## Universe 层

Universe 层只回答“本次任务包含哪些标的”，输出标准化的 `Instrument`。它不抓分钟数据，也不决定输出目录。

- `ExplicitUniverse`：处理 `--symbols`。
- `FileUniverse`：处理 `--symbols-file`。
- `AkshareETFUniverse`：发现当前或历史 ETF，并支持交易所、名称和基金类型筛选。

`--as-of` 使用历史 ETF 快照提供 point-in-time membership，避免直接用当前 ETF 列表做历史回测。当前仍没有独立、对称的官方 `list_date` / `delist_date` 生命周期表。

## DownloadEngine

`DownloadEngine` 负责跨 ETF 的任务调度：

- 使用有界 `ThreadPoolExecutor`；
- 把失败标的放入下一轮重试队列；
- 原子写入 checkpoint；
- 任务中断后跳过已经成功的 ETF；
- 将最终统计写入 JSON。

它把 `fetch_symbol_range()` 当作单 ETF 执行单元，因此不依赖具体行情源和 Parquet 细节。

当前 `--rate-limit` 只限制 ETF 任务启动速率。一个任务内部可能继续产生 AKShare 重试、东方财富回退或新浪回退请求；严格的 HTTP request quota 需要在 Provider 或共享 transport 层实现。

## Provider 层

`MinuteDataProvider` 定义统一接口：

```python
provider.fetch(
    ts_code,
    start_trade_date,
    end_trade_date,
    period="1",
)
```

默认 `FallbackMinuteProvider` 按以下顺序尝试：

1. `AkshareMinuteProvider`
2. `EastMoneyCurlMinuteProvider`
3. `SinaCurlMinuteProvider`（仅 `5/15/30/60` 分钟）

Provider 负责网络请求、源级重试、字段解释、标准化和 fallback。它返回统一 schema：

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

不同源之间当前是源级切换，不会自动把多个源的部分窗口拼接成一个结果。新浪没有成交额时，`amount` 保持为空。

## Storage 层

`BarStorage` 只负责分区是否存在和数据写入。默认实现 `ParquetBarStorage` 使用：

```text
<out>/<ts_code>/trade_date=YYYYMMDD/part.parquet
```

写入先写临时文件，再原子替换目标文件。以后增加 DuckDB、对象存储或其他目录布局时，可以新增 Storage adapter，而不修改 Provider。

## 兼容边界

以下公开函数继续保留：

- `fetch_etf_minute_range()`
- `fetch_etf_minute()`
- `fetch_symbol_range()`
- `write_partition()`

它们默认使用当前 Provider 和 Storage，也允许注入替代实现，旧调用方不需要立即迁移。

## 与其他项目的边界

Dashboard 通过本地 Parquet 目录读取分钟数据，具体 reader、日线数据源、在线回退和前端展示属于 Dashboard 仓库。数据平台的正式 ETF daily current contract 也属于 `market-data-platform` 的发布职责，不由本项目直接管理。
