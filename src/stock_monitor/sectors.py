from __future__ import annotations

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO

import pandas as pd
import requests
import time


def fetch_sector_period(kind: str, period: int) -> pd.DataFrame:
    """东方财富板块周期涨幅；接口已直接提供1/3/5/20日字段。"""
    from . import DFCF
    fields = {1:'f3', 3:'f127', 5:'f109', 20:'f110'}
    response = DFCF.boards(kind=kind, page=1, size=100, period=period)
    data = response['raw']['data']
    rows = data.get('diff') or []
    if not rows:
        raise ValueError('东方财富未返回板块周期排行')
    field = fields[period]
    collected_at = datetime.fromtimestamp(max(x.get('f124') or 0 for x in rows)).astimezone().isoformat(timespec='seconds')
    frame = pd.DataFrame([{
        'collected_at':collected_at, 'sector_type':kind, 'code':x.get('f12'),
        'name':x.get('f14'), 'pct_change':pd.to_numeric(x.get(field),errors='coerce'),
        'amount':pd.to_numeric(x.get('f6'),errors='coerce'),
        'company_count':sum(int(x.get(k) or 0) for k in ('f104','f105','f106')),
        'leader_code':x.get('f140'), 'leader_name':x.get('f128'),
        'leader_pct':pd.to_numeric(x.get('f136'),errors='coerce')
    } for x in rows]).dropna(subset=['code','name','pct_change'])
    frame.attrs['source'] = '东方财富 · 接口直接字段'
    frame.attrs['total'] = int(data.get('total') or len(frame))
    frame.attrs['endpoint'] = response['endpoint']
    return frame.sort_values('pct_change',ascending=False).reset_index(drop=True)


def fetch_sector_snapshot() -> pd.DataFrame:
    """Fetch both current snapshot categories from Eastmoney."""
    result = pd.concat([fetch_sector_period('industry',1), fetch_sector_period('concept',1)], ignore_index=True)
    result.attrs['source'] = '东方财富'
    return result


def _legacy_sector_snapshot() -> pd.DataFrame:
    import akshare as ak

    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
    frames = []
    try:
        raw = ak.stock_board_industry_name_em()
        source = "东方财富"
        frame = raw.rename(columns={
            "板块代码": "code", "板块名称": "name", "涨跌幅": "pct_change",
            "成交额": "amount", "上涨家数": "up_count", "下跌家数": "down_count",
            "领涨股票": "leader_name", "领涨股票-涨跌幅": "leader_pct",
        }).copy()
        frame["company_count"] = frame.get("up_count", 0).fillna(0) + frame.get("down_count", 0).fillna(0)
        frame["leader_code"] = None
    except Exception:
        raw = ak.stock_sector_spot(indicator="新浪行业")
        source = "新浪财经"
        frame = raw.rename(columns={
            "label": "code", "板块": "name", "涨跌幅": "pct_change",
            "总成交额": "amount", "公司家数": "company_count", "股票代码": "leader_code",
            "股票名称": "leader_name", "个股-涨跌幅": "leader_pct",
        }).copy()
    frame["sector_type"] = "industry"
    frames.append(frame)
    concept_raw = ak.stock_sector_spot(indicator="概念")
    concept = concept_raw.rename(columns={
        "label": "code", "板块": "name", "涨跌幅": "pct_change", "总成交额": "amount",
        "公司家数": "company_count", "股票代码": "leader_code", "股票名称": "leader_name",
        "个股-涨跌幅": "leader_pct",
    }).copy()
    concept["sector_type"] = "concept"
    frames.append(concept)
    result = pd.concat(frames, ignore_index=True)
    result["collected_at"] = collected_at
    for col in ["pct_change", "amount", "company_count", "leader_pct"]:
        result[col] = pd.to_numeric(result.get(col), errors="coerce")
    result = result[["collected_at", "sector_type", "code", "name", "pct_change", "amount",
                     "company_count", "leader_code", "leader_name", "leader_pct"]].dropna(subset=["code", "name"])
    result.attrs["source"] = source
    return result


def fetch_sector_constituents(code: str) -> pd.DataFrame:
    if str(code).startswith('BK'):
        from .dfcf_provider import constituents
        return constituents(str(code))
    import akshare as ak
    if str(code).startswith("881") or str(code).startswith(("308", "309", "301")):
        headers = {"User-Agent": "Mozilla/5.0"}
        board_path = "thshy" if str(code).startswith("881") else "gn"
        url = f"http://q.10jqka.com.cn/{board_path}/detail/code/{code}/"
        last_error = None
        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=20)
                response.raise_for_status()
                raw = pd.read_html(StringIO(response.text))[0].drop_duplicates("代码")
                break
            except Exception as exc:
                last_error = exc
                time.sleep(attempt + 1)
        else:
            raise RuntimeError(f"同花顺成分股页面暂时不可用: {last_error}")
        raw["代码"] = raw["代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        def parse_amount(value):
            text = str(value).strip()
            if text.endswith("亿"):
                return float(text[:-1]) * 1e8
            if text.endswith("万"):
                return float(text[:-1]) * 1e4
            return pd.to_numeric(text, errors="coerce")
        raw["成交额"] = raw["成交额"].map(parse_amount)
        return raw.rename(columns={
            "代码": "code", "名称": "name", "现价": "close", "涨跌幅(%)": "pct_change",
            "成交额": "amount", "换手(%)": "turnover", "流通市值": "float_market_cap",
            "市盈率": "pe",
        })
    raw = ak.stock_sector_detail(sector=code)
    return raw.rename(columns={
        "code": "code", "name": "name", "trade": "close", "changepercent": "pct_change",
        "amount": "amount", "turnoverratio": "turnover", "mktcap": "market_cap",
        "nmc": "float_market_cap", "per": "pe", "pb": "pb",
    })


def backfill_sector_history(days: int = 90, workers: int = 6) -> pd.DataFrame:
    """Backfill THS industry indices; 90 calendar days is roughly 60 trading days."""
    import akshare as ak

    names = ak.stock_board_industry_name_ths()
    end = datetime.now().date()
    start = end - pd.Timedelta(days=days)

    def fetch(row: tuple[str, str]) -> pd.DataFrame:
        name, code = row
        raw = ak.stock_board_industry_index_ths(
            symbol=name, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d")
        )
        raw = raw.rename(columns={"日期": "trade_date", "开盘价": "open", "最高价": "high",
                                  "最低价": "low", "收盘价": "close", "成交量": "volume", "成交额": "amount"})
        raw["trade_date"] = raw["trade_date"].astype(str)
        raw["source"] = "同花顺"
        raw["code"] = str(code)
        raw["name"] = name
        return raw[["trade_date", "source", "code", "name", "open", "high", "low", "close", "volume", "amount"]]

    frames = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, (r["name"], r["code"])): r["name"] for _, r in names.iterrows()}
        for future in as_completed(futures):
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except Exception as exc:
                print(f"跳过 {futures[future]}：{exc}")
    if not frames:
        raise RuntimeError("没有取得行业历史数据")
    return pd.concat(frames, ignore_index=True)


def backfill_concept_history(days: int = 90, workers: int = 8) -> pd.DataFrame:
    """Backfill THS concept indices for multi-period concept ranking."""
    import akshare as ak

    names = ak.stock_board_concept_name_ths()
    end = datetime.now().date()
    start = end - pd.Timedelta(days=days)

    def fetch(row: tuple[str, str]) -> pd.DataFrame:
        name, code = row
        raw = ak.stock_board_concept_index_ths(
            symbol=name, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d")
        )
        raw = raw.rename(columns={"日期": "trade_date", "开盘价": "open", "最高价": "high",
                                  "最低价": "low", "收盘价": "close", "成交量": "volume", "成交额": "amount"})
        raw["trade_date"] = raw["trade_date"].astype(str)
        raw["source"] = "同花顺概念"
        raw["code"] = str(code)
        raw["name"] = name
        return raw[["trade_date", "source", "code", "name", "open", "high", "low", "close", "volume", "amount"]]

    frames = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, (r["name"], r["code"])): r["name"] for _, r in names.iterrows()}
        for future in as_completed(futures):
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except Exception as exc:
                print(f"跳过概念 {futures[future]}：{exc}")
    if not frames:
        raise RuntimeError("没有取得概念历史数据")
    return pd.concat(frames, ignore_index=True)
