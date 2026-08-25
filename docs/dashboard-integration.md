# 仪表盘接入

`etf-minute-fetcher` 通过本地 Parquet 文件向其他项目提供分钟行情。下游通常只需要知道数据根目录和分区规则，无需直接调用本项目的 Python 函数。

## 目录约定

推荐目录结构：

```text
~/data/etf-minute-fetcher/minute/fund_min_1m/
└── 512880.SH/
    └── trade_date=20260824/
        └── part.parquet
```

实际根目录由下载时的 `--out` 决定。下游应使用完整 `ts_code` 作为 ETF 目录名，例如 `512880.SH`。

分区路径规则为：

```text
<root>/<ts_code>/trade_date=YYYYMMDD/part.parquet
```

## 固定字段

每个分区包含：

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

需要注意：

- `trade_time` 应按时间戳读取
- `open`、`high`、`low`、`close` 和 `vol` 是核心行情字段
- 新浪回退数据没有成交额，`amount` 可能为空
- 一个分区对应一只 ETF 的一个交易日

下游如果要求成交额完整，应自行决定是否拒绝 `amount` 为空的分区。不要用 `vol` 填充 `amount`。

## 最小读取示例

```python
from pathlib import Path

import pandas as pd


def read_etf_minute(
    root: str | Path,
    ts_code: str,
    trade_date: str,
) -> pd.DataFrame:
    path = Path(root).expanduser() / ts_code / f"trade_date={trade_date}" / "part.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)
```

## 下游读取建议

一个简单的读取流程可以按下面处理：

1. 把用户输入转换为完整 `ts_code`
2. 把交易日期转换为 `YYYYMMDD`
3. 生成对应 `part.parquet` 路径
4. 检查文件是否存在
5. 读取 Parquet
6. 验证固定字段和时间范围
7. 根据下游产品需求处理缺失分区

是否提供在线查询、日线补充、缓存、指标计算或页面展示，都由下游项目决定。

## 缺失分区

本地文件不存在可能有多种原因：

- 目标日期是周末或节假日
- ETF 当时还没有上市或已经停止交易
- 上游历史范围不足
- 下载任务尚未覆盖该日期
- 下载失败后仍待重试

因此下游不要把文件不存在直接解释成 ETF 当天没有交易。需要更严格的数据完整性时，应结合交易日历、ETF 生命周期和下载汇总判断。

## 更新中的文件

`ParquetBarStorage` 先写临时文件，再原子替换正式的 `part.parquet`。下游只读取正式文件名，可以降低读到半成品的概率。

如果下载器和仪表盘同时访问同一数据目录，下游仍应把单次文件读取视为可能失败的 I/O 操作，并处理文件被移动、磁盘异常或权限变化。

## 项目边界

本仓库不包含仪表盘实现，也没有 Git submodule 指向某个仪表盘仓库。其他项目只需遵循 Parquet 目录和字段约定即可接入。

如果将来需要稳定的跨仓库数据契约，建议把字段、版本和兼容策略明确写成独立规范，并在生产者与消费者两边分别增加契约测试。现阶段直接读取固定字段的 Parquet 已经足够，额外引入服务接口会增加部署和维护成本。
