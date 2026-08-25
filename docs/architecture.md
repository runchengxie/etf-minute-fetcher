# 架构

项目保持四个主要边界：标的选择、批量调度、行情获取和数据存储。命令行只负责解析参数并组装这些组件。

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
 │  有限并发 / 任务启动限速 / 失败重试 / 断点状态
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

## 标的选择

`UniverseProvider` 负责生成本次任务需要处理的 `Instrument` 列表。

- `ExplicitUniverse` 处理 `--symbols`
- `FileUniverse` 处理 `--symbols-file`
- `AkshareETFUniverse` 获取当前或历史 ETF 列表，并支持交易所、名称和基金类型筛选

这一层不抓分钟行情，也不处理输出目录。

`--as-of` 使用指定日期的 ETF 历史快照。它适合减少直接使用当前 ETF 列表回填历史数据造成的幸存者偏差。当前项目没有独立、完整的 `list_date` 和 `delist_date` 生命周期数据源，因此历史快照仍有边界。

## 批量调度

`DownloadEngine` 负责多只 ETF 的任务调度，主要职责包括：

- 使用有上限的 `ThreadPoolExecutor`
- 控制 ETF 任务启动速度
- 把失败标的放入下一轮重试
- 原子写入断点文件
- 从已完成状态继续执行
- 写出最终下载汇总

`DownloadEngine` 把 `fetch_symbol_range()` 视为单只 ETF 的执行单元，因此它不需要知道具体行情源和 Parquet 写入细节。

断点文件会绑定以下任务条件：

```text
period
trade_dates
output_dir
skip_existing
```

修改其中任意一项后，旧断点不会继续复用。早期 `0.2.0` 断点没有 `skip_existing` 字段，读取时按默认的 `True` 兼容处理。

`--rate-limit` 控制 ETF 任务开始执行的频率。单个任务内部仍可能发生 AKShare 重试或切换行情源，因此它不能作为统一的 HTTP 请求速率上限。

## 行情源

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
3. `SinaCurlMinuteProvider`，仅用于 `5/15/30/60` 分钟

AKShare 抛出异常或返回空表时会继续尝试东方财富直连。较长周期下，东方财富请求失败或没有返回目标区间数据时，再尝试新浪。

各行情源都会返回统一字段：

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

当前按完整结果切换行情源，不会自动把多个来源的局部时间窗口拼接。新浪没有成交额，使用新浪数据时 `amount` 保持为空。

行情源层同时负责上游字段解释和标准化。这样可以把第三方接口变化控制在适配器附近，避免网络细节扩散到调度和存储代码。

## 数据存储

`BarStorage` 负责判断分区是否存在并写入数据。默认实现 `ParquetBarStorage` 使用以下目录结构：

```text
<out>/<ts_code>/trade_date=YYYYMMDD/part.parquet
```

写入时先生成临时文件，成功后再原子替换正式文件。下载中断时不会留下已经命名为正式分区的半成品。

以后确实需要 DuckDB、对象存储或其他目录布局时，可以新增 `BarStorage` 实现。当前只有 Parquet 一种正式存储方式，因此没有继续增加中间抽象层。

## 模块依赖方向

主要依赖关系保持单向：

```text
cli
 ├─ engine
 └─ universe

engine
 └─ fetcher

fetcher
 ├─ providers
 └─ storage

universe
 └─ models
```

`providers` 和 `storage` 不依赖 CLI 或批量调度器。这个结构已经能把网络、调度和持久化分开，继续增加服务层、仓储层或工厂层只会增加导航成本。

## 兼容边界

以下公开函数继续保留：

- `fetch_etf_minute_range()`
- `fetch_etf_minute()`
- `fetch_symbol_range()`
- `write_partition()`

它们仍然返回原有的数据形态，并允许注入 `MinuteDataProvider` 或 `BarStorage`。已有调用方无需为了内部重构立即迁移。

## 文件规模

`providers.py` 是当前最大的实现文件，但里面的行情源类本身都很小，并共享字段标准化和 curl 辅助函数。现阶段继续拆成多个文件会增加来回跳转，收益有限。

以后出现以下情况时，再拆分更合适：

- 新增更多独立行情源
- 某个行情源出现大量专属解析逻辑
- 不同行情源开始拥有独立依赖或配置
- 单个行情源类本身变得难以测试或阅读

## 与其他项目的关系

其他项目可以直接读取本项目生成的 Parquet。仪表盘、日线数据、指标计算、在线展示和数据平台发布流程都属于外部系统的职责。

当前仓库没有 Git submodule，也不依赖 `market-data-platform` 或其他仓库才能完成安装、测试和分钟行情下载。
