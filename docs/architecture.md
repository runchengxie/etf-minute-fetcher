# 架构

`etf-minute-fetcher` 把“选择哪些 ETF、怎样批量调度、从哪里取分钟行情、如何落盘”拆成独立边界。公开 CLI 负责组装这些能力，不承载具体网络或存储实现。

## 数据流

```text
CLI
 │
 ├─ UniverseProvider
 │    ├─ ExplicitUniverse
 │    ├─ FileUniverse
 │    └─ AkshareETFUniverse
 │
 ▼
DownloadEngine
 │
 │ bounded concurrency / rate limit / retry queue
 │ checkpoint / resume / batch summary
 ▼
fetch_symbol_range()
 │
 ├─ MinuteDataProvider
 │    └─ FallbackMinuteProvider
 │         ├─ AkshareMinuteProvider
 │         ├─ EastMoneyCurlMinuteProvider
 │         └─ SinaCurlMinuteProvider
 │
 └─ BarStorage
      └─ ParquetBarStorage
```

## Universe 层

Universe 层只回答“本次任务包含哪些标的”。输出统一为 `Instrument`，下载层只消费规范化后的 `ts_code`。

- `ExplicitUniverse`：显式代码。
- `FileUniverse`：文本文件中的代码。
- `AkshareETFUniverse`：当前市场或历史 point-in-time ETF membership，并支持交易所、名称和基金类型筛选。

这层不抓分钟行情，也不决定输出目录。

## DownloadEngine

`DownloadEngine` 负责跨 ETF 的任务调度：

- 有界线程池并发；
- ETF 任务启动级限速；
- 失败标的进入下一轮重试队列；
- 原子 checkpoint；
- 中断后恢复已成功标的；
- 批量统计持久化。

它把 `fetch_symbol_range()` 当作单标的执行单元，因此不依赖具体行情源和 parquet 细节。

当前限速是 ETF 任务启动级。单个 provider 内部可能继续发生请求重试或 fallback；如果未来需要严格的 HTTP request quota，应在具体 Provider 或共享 transport 层实现。

## Provider 层

`MinuteDataProvider` 定义统一的分钟行情读取接口：

```python
provider.fetch(
    ts_code,
    start_trade_date,
    end_trade_date,
    period="1",
)
```

默认 `FallbackMinuteProvider` 保留原有数据源顺序：

1. `AkshareMinuteProvider`
2. `EastMoneyCurlMinuteProvider`
3. `SinaCurlMinuteProvider`（仅 5/15/30/60 分钟）

Provider 返回统一 schema 的 `DataFrame`，网络请求、源级重试、源特有字段解释和 fallback 都封装在这一层。新增数据源时实现 `MinuteDataProvider` 即可，不需要修改 `DownloadEngine`。

## 标准化边界

不同上游数据在 Provider 模块中规范为：

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

`amount` 在新浪回退源缺失时保留为空值，不把成交量冒充成交额。

## Storage 层

`BarStorage` 只负责分区是否存在和数据写入：

```python
storage.exists(output_dir, trade_date)
storage.write(frame, output_dir, trade_date)
```

默认 `ParquetBarStorage` 保持现有 Hive 风格目录：

```text
<out>/<ts_code>/trade_date=YYYYMMDD/part.parquet
```

写入使用临时文件再原子替换。以后需要对象存储、DuckDB 或其他布局时，可以新增 Storage adapter，而不用改 Provider。

## 兼容边界

以下公开函数继续保留：

- `fetch_etf_minute_range()`
- `fetch_etf_minute()`
- `fetch_symbol_range()`
- `write_partition()`

它们默认使用当前 Provider/Storage 实现，同时允许注入替代实现。这样旧调用方不需要因内部重构立即迁移。

## 尚未覆盖

- 精确、对称的沪深 ETF 官方上市/退市生命周期元数据；
- HTTP 请求级统一 quota/rate-limit transport；
- 正式数据平台中的 ETF 日线注册、reader 和 Dashboard 展示。

最后一项属于 `market-data-platform` 的共享数据控制面与消费接口，应在该仓单独设计和实现，避免让抓取器反过来承担 Dashboard 职责。
