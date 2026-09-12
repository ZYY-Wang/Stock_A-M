from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import pandas as pd

from .core import Settings, Store, calculate_streaks, normalize_stocks, select_indices, today_string
from .report import write_report


def load_config(path: Path) -> tuple[Settings, dict[str, str]]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    settings = Settings(**data.get("monitor", {}))
    indices = {str(k).zfill(6): str(v) for k, v in data.get("indices", {}).items()}
    return settings, indices


def fetch_data() -> tuple[pd.DataFrame, list[pd.DataFrame], dict[str, str]]:
    from . import dfcf_provider as provider
    stocks = provider.stocks()
    frame = provider.indices().rename(columns={'code':'代码','name':'名称','close':'最新价','pct_change':'涨跌幅','amount':'成交额'})
    return stocks, [frame], {'stocks':'东方财富','indices':'东方财富'}


def run(root: Path, trade_date: str) -> Path:
    settings, wanted = load_config(root / "config.toml")
    raw_stocks, raw_indices, sources = fetch_data()
    trade_date = raw_stocks.attrs['trade_date']
    stocks = normalize_stocks(raw_stocks, trade_date)
    if settings.exclude_st:
        stocks = stocks[~stocks["name"].str.contains("ST", case=False, na=False)]
    indices = select_indices(raw_indices, wanted, trade_date)
    store = Store(root / "data" / "market.db")
    try:
        store.initialize()
        stocks = calculate_streaks(stocks, store.latest_stocks_before(trade_date))
        store.save_stocks(stocks)
        store.save_indices(indices)
        store.set_metadata("stocks_source", sources["stocks"])
        store.set_metadata("indices_source", sources["indices"])
    finally:
        store.close()
    return write_report(root / "reports", trade_date, indices, stocks, settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="A 股每日行情与连续涨跌监测")
    parser.add_argument("--date", default=today_string(), help="交易日，格式 YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目目录")
    args = parser.parse_args()
    try:
        report = run(args.root.resolve(), args.date)
        print(f"完成：{report}")
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
