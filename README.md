# etf-minute-fetcher

用 [akshare](https://akshare.akfamily.xyz/) 抓取 ETF 分钟级行情，并落盘为与
`~/data/market-data-platform/assets/tushare/etf/daily` 对齐的
**`trade_date` 分区 parquet** 结构。

数据来源：东方财富（`push2his.eastmoney.com` / `quote.eastmoney.com`），经 akshare
的 `fund_etf_hist_min_em` 拉取。

> 注：本机出网需让东方财富域名走直连（见下方「网络要求」）。tushare 的 `fund_min`
> 接口在当前账号未订阅，故采用 akshare 方案。

## 落盘结构

```
<out>/
  512880.SH/
    trade_date=20260818/
      part.parquet
    trade_date=20260819/
      part.parquet
  ...
```

列（对齐 tushare 风格）：

| 列 | 含义 |
|----|------|
| `ts_code` | 带后缀代码，如 `512880.SH` |
| `trade_time` | 分钟时间戳（datetime） |
| `open` / `high` / `low` / `close` | 分钟 OHLC |
| `vol` | 成交量（股） |
| `amount` | 成交额（元） |

## 安装

```bash
uv sync            # 或 pip install -e .
```

## 使用

```bash
# 证券 ETF 512880，最近约 5 个交易日，1 分钟线
etf-min --symbols 512880.SH --days 5 \
  --out ~/data/market-data-platform/assets/tushare/etf/minute/fund_min_1m

# 目标集合（红利低波 6 只 + 证券类）
etf-min --symbols-file symbols_target.txt --start 20260811 --end 20260818 \
  --out ~/data/market-data-platform/assets/tushare/etf/minute/fund_min_1m
```

## 网络要求

akshare 拉东方财富需要这两个域名本机可达。若出网走代理且该代理不可达，需在
代理（如 mihomo）的 rules 里把东方财富设为直连：

```
DOMAIN-SUFFIX,push2his.eastmoney.com,DIRECT
DOMAIN-SUFFIX,quote.eastmoney.com,DIRECT
```

## 数据发布

抓取脚本与配置入 Git；落盘数据（`data/`）默认不入库。需要共享数据时单独管理。
