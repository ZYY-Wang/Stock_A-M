from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

import pandas as pd


STOCK_COLUMNS = {
    "代码": "code", "名称": "name", "最新价": "close", "涨跌幅": "pct_change",
    "涨跌额": "change", "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
    "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
    "换手率": "turnover", "量比": "volume_ratio", "总市值": "market_cap",
    "流通市值": "float_market_cap", "市盈率": "pe", "市净率": "pb",
}


@dataclass(frozen=True)
class Settings:
    streak_threshold: int = 3
    top_n: int = 30
    exclude_st: bool = False


def normalize_stocks(raw: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    missing = {"代码", "名称", "最新价"} - set(raw.columns)
    if missing:
        raise ValueError(f"个股数据缺少必要字段: {', '.join(sorted(missing))}")
    frame = raw.rename(columns={k: v for k, v in STOCK_COLUMNS.items() if k in raw.columns}).copy()
    keep = [v for v in STOCK_COLUMNS.values() if v in frame.columns]
    frame = frame[keep]
    frame["code"] = frame["code"].astype(str).str.replace(r"\D", "", regex=True).str[-6:].str.zfill(6)
    frame["trade_date"] = trade_date
    for col in set(keep) - {"code", "name"}:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=["close"]).drop_duplicates("code")


def calculate_streaks(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    result = current.copy()
    if previous is None or previous.empty:
        change = result.get("pct_change", pd.Series(0.0, index=result.index)).fillna(0)
        result["direction"] = change.map(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        result["streak"] = result["direction"]
        return result

    prior = previous[["code", "close", "streak"]].rename(
        columns={"close": "stored_prev_close", "streak": "previous_streak"}
    )
    result = result.merge(prior, on="code", how="left")
    # Prefer the provider's previous close, because it remains correct after missed run days.
    comparable = result.get("prev_close", result["stored_prev_close"]).fillna(result["stored_prev_close"])
    delta = result["close"] - comparable
    result["direction"] = delta.map(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    def next_streak(row: pd.Series) -> int:
        direction = int(row["direction"])
        old = 0 if pd.isna(row["previous_streak"]) else int(row["previous_streak"])
        if direction == 0:
            return 0
        return old + direction if old * direction > 0 else direction

    result["streak"] = result.apply(next_streak, axis=1)
    return result.drop(columns=["stored_prev_close", "previous_streak"])


def market_summary(stocks: pd.DataFrame) -> dict[str, float | int]:
    pct = stocks["pct_change"].fillna(0) if "pct_change" in stocks else pd.Series(0, index=stocks.index)
    amount = stocks["amount"].fillna(0) if "amount" in stocks else pd.Series(0, index=stocks.index)
    return {
        "stocks": int(len(stocks)), "up": int((pct > 0).sum()), "down": int((pct < 0).sum()),
        "flat": int((pct == 0).sum()), "limit_up_approx": int((pct >= 9.8).sum()),
        "limit_down_approx": int((pct <= -9.8).sum()), "amount": float(amount.sum()),
        "median_pct": float(pct.median()),
    }


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)

    def initialize(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock_daily (
          trade_date TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
          close REAL NOT NULL, pct_change REAL, amount REAL, streak INTEGER NOT NULL,
          direction INTEGER NOT NULL, payload TEXT, PRIMARY KEY (trade_date, code)
        );
        CREATE TABLE IF NOT EXISTS index_daily (
          trade_date TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
          close REAL, pct_change REAL, amount REAL, PRIMARY KEY (trade_date, code)
        );
        CREATE TABLE IF NOT EXISTS sector_snapshot (
          collected_at TEXT NOT NULL, sector_type TEXT NOT NULL, code TEXT NOT NULL,
          name TEXT NOT NULL, pct_change REAL, amount REAL, company_count INTEGER,
          leader_code TEXT, leader_name TEXT, leader_pct REAL,
          PRIMARY KEY (collected_at, sector_type, code)
        );
        CREATE TABLE IF NOT EXISTS sector_history (
          trade_date TEXT NOT NULL, source TEXT NOT NULL, code TEXT NOT NULL,
          name TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
          volume REAL, amount REAL, PRIMARY KEY (trade_date, source, code)
        );
        CREATE TABLE IF NOT EXISTS watchlist (
          item_type TEXT NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL,
          added_at TEXT NOT NULL, expires_at TEXT, note TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (item_type, item_code)
        );
        CREATE TABLE IF NOT EXISTS app_metadata (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sector_membership (
          sector_code TEXT NOT NULL, stock_code TEXT NOT NULL, observed_at TEXT NOT NULL,
          PRIMARY KEY (sector_code, stock_code)
        );
        """)
        watch_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(watchlist)")}
        if "pinned" not in watch_columns:
            self.conn.execute("ALTER TABLE watchlist ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def latest_stocks_before(self, trade_date: str) -> pd.DataFrame | None:
        row = self.conn.execute(
            "SELECT MAX(trade_date) FROM stock_daily WHERE trade_date < ?", (trade_date,)
        ).fetchone()
        if not row or not row[0]:
            return None
        return pd.read_sql_query(
            "SELECT code, close, streak FROM stock_daily WHERE trade_date = ?",
            self.conn, params=(row[0],), dtype={"code": str},
        )

    def save_stocks(self, stocks: pd.DataFrame) -> None:
        cols = ["trade_date", "code", "name", "close", "pct_change", "amount", "streak", "direction"]
        data = stocks.reindex(columns=cols).copy()
        detail_cols = ["change", "volume", "amplitude", "high", "low", "open", "prev_close",
                       "turnover", "volume_ratio", "market_cap", "float_market_cap", "pe", "pb"]
        payloads = []
        for _, row in stocks.iterrows():
            values = {}
            for key in detail_cols:
                value = row.get(key)
                if value is not None and not pd.isna(value):
                    values[key] = value.item() if hasattr(value, "item") else value
            payloads.append(json.dumps(values, ensure_ascii=False) if values else None)
        data["payload"] = payloads
        with self.conn:
            dates = [str(x) for x in data["trade_date"].dropna().unique()]
            self.conn.executemany("DELETE FROM stock_daily WHERE trade_date = ?", ((x,) for x in dates))
            self.conn.executemany(
                "INSERT OR REPLACE INTO stock_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                data.itertuples(index=False, name=None),
            )

    def save_indices(self, indices: pd.DataFrame) -> None:
        cols = ["trade_date", "code", "name", "close", "pct_change", "amount"]
        data = indices.reindex(columns=cols)
        with self.conn:
            dates = [str(x) for x in data["trade_date"].dropna().unique()]
            self.conn.executemany("DELETE FROM index_daily WHERE trade_date = ?", ((x,) for x in dates))
            self.conn.executemany(
                "INSERT OR REPLACE INTO index_daily VALUES (?, ?, ?, ?, ?, ?)",
                data.itertuples(index=False, name=None),
            )

    def save_sectors(self, sectors: pd.DataFrame) -> None:
        cols = ["collected_at", "sector_type", "code", "name", "pct_change", "amount",
                "company_count", "leader_code", "leader_name", "leader_pct"]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO sector_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                sectors.reindex(columns=cols).itertuples(index=False, name=None),
            )

    def set_metadata(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO app_metadata VALUES (?, ?)", (key, value))

    def save_sector_history(self, history: pd.DataFrame) -> None:
        cols = ["trade_date", "source", "code", "name", "open", "high", "low", "close", "volume", "amount"]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO sector_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                history.reindex(columns=cols).itertuples(index=False, name=None),
            )

    def close(self) -> None:
        self.conn.close()


def select_indices(raw_frames: list[pd.DataFrame], wanted: Mapping[str, str], trade_date: str) -> pd.DataFrame:
    raw = pd.concat(raw_frames, ignore_index=True).drop_duplicates("代码")
    raw["代码"] = raw["代码"].astype(str).str.replace(r"\D", "", regex=True).str[-6:].str.zfill(6)
    selected = raw[raw["代码"].isin(wanted)].rename(columns={
        "代码": "code", "名称": "name", "最新价": "close", "涨跌幅": "pct_change", "成交额": "amount"
    }).copy()
    selected["trade_date"] = trade_date
    for code, name in wanted.items():
        if code not in set(selected["code"]):
            selected.loc[len(selected)] = {"code": code, "name": name, "trade_date": trade_date}
    return selected


def today_string() -> str:
    return date.today().isoformat()
