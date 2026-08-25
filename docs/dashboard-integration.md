# Dashboard 接入

`etf-minute-fetcher` 和 Dashboard 通过本地 Parquet 目录连接，不需要让 Dashboard 直接调用本项目的 Python 函数。

## 目录契约

默认建议使用：

```text
~/data/etf-minute-fetcher/minute/fund_min_1m/
└── 512880.SH/
    └── trade_date=20260824/
        └── part.parquet
```

也可以通过 Dashboard 自己的配置把读取根目录指向其他 `--out` 目录。下游读取时应使用完整 `ts_code`，例如 `512880.SH`，不要只使用裸代码作为目录名。

## 读取建议

下游 reader 通常按以下步骤工作：

1. 把用户输入标准化为 `ts_code`；
2. 把交易日期转换为 `YYYYMMDD`；
3. 拼接 `<root>/<ts_code>/trade_date=<date>/part.parquet`；
4. 检查文件存在并读取 Parquet；
5. 验证 `trade_time`、价格和成交量字段；
6. 如果本地分区不存在，再决定是否调用在线回退源。

## 数据源边界

本项目只负责抓取和落盘分钟数据。Dashboard 是否提供日线、在线分钟回退、CSV 缓存或前端展示，应该由 Dashboard 自己负责；不要把 Dashboard 的业务逻辑倒灌进 fetcher。

本地 Parquet 优先的好处是结果可复现，也能覆盖 AKShare 只提供近期 1 分钟数据的限制。在线回退适合临时查看，不适合作为长期历史归档。

## 最小读取示例

```python
from pathlib import Path

import pandas as pd


def read_etf_minute(root: str | Path, ts_code: str, trade_date: str) -> pd.DataFrame:
    path = Path(root).expanduser() / ts_code / f"trade_date={trade_date}" / "part.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)
```
