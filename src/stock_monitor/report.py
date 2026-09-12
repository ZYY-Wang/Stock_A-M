from __future__ import annotations

from pathlib import Path

import pandas as pd

from .core import Settings, market_summary


def _table(frame: pd.DataFrame, columns: list[str]) -> str:
    view = frame.reindex(columns=columns).copy()
    return view.to_markdown(index=False) if not view.empty else "（无）"


def write_report(output_dir: Path, trade_date: str, indices: pd.DataFrame,
                 stocks: pd.DataFrame, settings: Settings) -> Path:
    target = output_dir / trade_date
    target.mkdir(parents=True, exist_ok=True)
    stocks.sort_values("code").to_csv(target / "stocks.csv", index=False, encoding="utf-8-sig")
    indices.to_csv(target / "indices.csv", index=False, encoding="utf-8-sig")
    summary = market_summary(stocks)
    rising = stocks[stocks["streak"] >= settings.streak_threshold].nlargest(settings.top_n, "streak")
    falling = stocks[stocks["streak"] <= -settings.streak_threshold].nsmallest(settings.top_n, "streak")
    leaders = stocks.nlargest(settings.top_n, "pct_change")
    laggards = stocks.nsmallest(settings.top_n, "pct_change")
    text = f"""# A 股监测日报 · {trade_date}

## 市场概况

- 上涨 / 下跌 / 平盘：{summary['up']} / {summary['down']} / {summary['flat']}
- 涨停 / 跌停（近似）：{summary['limit_up_approx']} / {summary['limit_down_approx']}
- 两市成交额：{summary['amount'] / 1e8:.2f} 亿元
- 个股涨跌幅中位数：{summary['median_pct']:.2f}%

## 主要指数

{_table(indices, ['code', 'name', 'close', 'pct_change', 'amount'])}

## 连续上涨（至少 {settings.streak_threshold} 天）

{_table(rising, ['code', 'name', 'close', 'pct_change', 'streak'])}

## 连续下跌（至少 {settings.streak_threshold} 天）

{_table(falling, ['code', 'name', 'close', 'pct_change', 'streak'])}

## 当日涨幅榜

{_table(leaders, ['code', 'name', 'close', 'pct_change'])}

## 当日跌幅榜

{_table(laggards, ['code', 'name', 'close', 'pct_change'])}
"""
    path = target / "report.md"
    path.write_text(text, encoding="utf-8")
    return path

