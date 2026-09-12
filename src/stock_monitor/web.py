from __future__ import annotations

import argparse
import calendar
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .cli import run
from .core import Store, today_string
from .sectors import fetch_sector_constituents, fetch_sector_snapshot
from .dfcf_provider import fund_flow_sectors


class WatchItem(BaseModel):
    item_type: str
    item_code: str
    item_name: str
    note: str = ""


def add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def create_app(root: Path | None = None) -> FastAPI:
    project_root = (root or Path.cwd()).resolve()
    db_path = project_root / "data" / "market.db"
    static_dir = Path(__file__).with_name("static")
    app = FastAPI(title="板块雷达")

    def connect() -> sqlite3.Connection:
        store = Store(db_path)
        store.initialize()
        store.close()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/app.css")
    def css():
        return FileResponse(static_dir / "app.css", media_type="text/css", headers={"Cache-Control": "no-store"})

    @app.get("/app.js")
    def js():
        return FileResponse(static_dir / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get('/detail.js')
    def detail_js():
        return FileResponse(static_dir / 'detail.js', media_type='text/javascript', headers={"Cache-Control": "no-store"})

    @app.get('/api/market-summary')
    def market_summary():
        with connect() as conn:
            row=conn.execute("SELECT value FROM app_metadata WHERE key='market_summary'").fetchone()
        return json.loads(row[0]) if row else None

    @app.get("/api/overview")
    def overview():
        with connect() as conn:
            latest_stock = conn.execute("SELECT MAX(trade_date) d FROM stock_daily").fetchone()["d"]
            latest_sector = conn.execute("SELECT MAX(collected_at) d FROM sector_snapshot").fetchone()["d"]
            market = None
            if latest_stock:
                market = dict(conn.execute("""
                  SELECT COUNT(*) stocks,
                    SUM(CASE WHEN pct_change > 0 THEN 1 ELSE 0 END) up,
                    SUM(CASE WHEN pct_change < 0 THEN 1 ELSE 0 END) down,
                    SUM(CASE WHEN pct_change = 0 THEN 1 ELSE 0 END) flat,
                    SUM(amount) amount
                  FROM stock_daily WHERE trade_date = ?
                """, (latest_stock,)).fetchone())
            metadata = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_metadata")}
            sector_code = conn.execute(
                "SELECT code FROM sector_snapshot WHERE collected_at=? LIMIT 1", (latest_sector,)
            ).fetchone() if latest_sector else None
            sector_source = metadata.get("sectors_source") or ("东方财富" if sector_code and str(sector_code["code"]).startswith("BK") else None)
            return {"trade_date": latest_stock, "sector_time": latest_sector, "market": market,
                    "sources": {"stocks": metadata.get("stocks_source", "东方财富" if latest_stock else None),
                                "indices": metadata.get("indices_source", "东方财富" if latest_stock else None),
                                "sectors": metadata.get("sectors_source", sector_source)}}

    @app.get("/api/sectors")
    def sectors(period: int = 1, sector_type: str = "industry"):
        if period not in (1,5,10) or sector_type not in ('industry','concept'):
            raise HTTPException(422, detail='板块资金周期或类型无效')
        with connect() as conn:
            row=conn.execute("SELECT value FROM app_metadata WHERE key=?",
                             (f'fund_flow_{sector_type}_{period}',)).fetchone()
        if row:
            return json.loads(row[0])
        try:
            frame=fund_flow_sectors(sector_type,period)
        except Exception as exc:
            raise HTTPException(502,detail='东方财富板块资金流读取失败') from exc
        view=frame.astype(object).where(pd.notna(frame),None)
        return {'collected_at':frame['collected_at'].max(),'items':view.to_dict('records'),
                'period':period,'source':frame.attrs['source'],
                'source_url':frame.attrs['source_url'],'endpoint':frame.attrs['endpoint']}

    @app.get('/api/market-signals')
    def market_signals():
        with connect() as conn:
            index = conn.execute("SELECT * FROM index_daily WHERE code='000001' ORDER BY trade_date DESC LIMIT 1").fetchone()
            date = conn.execute('SELECT MAX(trade_date) FROM stock_daily').fetchone()[0]
            counts = conn.execute('''SELECT COUNT(pct_change) total,
                SUM(CASE WHEN pct_change>0 THEN 1 ELSE 0 END) up,
                SUM(CASE WHEN pct_change<0 THEN 1 ELSE 0 END) down,
                SUM(CASE WHEN pct_change>=5 THEN 1 ELSE 0 END) strong,
                SUM(CASE WHEN pct_change<=-5 THEN 1 ELSE 0 END) weak
                FROM stock_daily WHERE trade_date=?''', (date,)).fetchone()
            alerts = []
            change = index['pct_change'] if index else None
            if change is not None and abs(change)>=1:
                alerts.append(f"上证指数{'上涨' if change>0 else '下跌'} {abs(change):.2f}%（阈值：±1%）")
            total = counts['total']
            if total:
                for field, label in [('up','上涨'),('down','下跌')]:
                    share = counts[field]/total
                    if share>=0.7:
                        alerts.append(f'{label}家数占比 {share:.1%}（阈值：70%，含平盘股票作为分母）')
                if index and index['trade_date']==date and change is not None and change>0 and counts['down']/total>=0.6:
                    alerts.append('指数与个股表现分化：上证上涨，但至少60%的个股下跌')
                for field,label in [('strong','涨幅≥5%'),('weak','跌幅≥5%')]:
                    if counts[field]/total>=0.1:
                        alerts.append(f"{label}的股票 {counts[field]} 只，占 {counts[field]/total:.1%}（阈值：10%）")
            return {'index': dict(index) if index else None, 'stock_date': date,
                    'alerts': alerts, 'available': bool(total or change is not None),
                    'note': '按本地最新快照检测，并非盘中实时预警。成交额暂不判定异动：未具备同一盘中时点或确认收盘的可比数据。'}

    @app.get('/api/stocks/search')
    def search_stocks(q: str = ''):
        q = q.strip()
        if len(q) > 80:
            raise HTTPException(422, detail='搜索关键词过长')
        with connect() as conn:
            date = conn.execute('SELECT MAX(trade_date) FROM stock_daily').fetchone()[0]
            if not q or not date:
                return {'items': [], 'trade_date': date, 'total': 0}
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            where = "trade_date=? AND (code LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')"
            params = (date, pattern, pattern)
            total = conn.execute('SELECT COUNT(*) FROM stock_daily WHERE ' + where, params).fetchone()[0]
            rows = conn.execute('SELECT code,name,close,pct_change FROM stock_daily WHERE ' + where +
                                ' ORDER BY CASE WHEN code=? THEN 0 WHEN name=? THEN 1 ELSE 2 END, code LIMIT 50',
                                (*params, q, q)).fetchall()
            return {'items': [dict(r) for r in rows], 'trade_date': date, 'total': total}

    @app.post("/api/refresh")
    def refresh():
        from .refresh import refresh_spot
        return refresh_spot(project_root)

    def legacy_refresh():
        errors = []
        try:
            run(project_root, today_string())
        except Exception as exc:
            errors.append(f"个股行情：{exc}")
        try:
            sectors = fetch_sector_snapshot()
            sector_source = sectors.attrs.get("source", "未知")
            store = Store(db_path)
            try:
                store.initialize()
                store.save_sectors(sectors)
                store.set_metadata("sectors_source", sector_source)
            finally:
                store.close()
        except Exception as exc:
            errors.append(f"板块行情：{exc}")
        if len(errors) == 2:
            raise HTTPException(502, detail="；".join(errors))
        return {"ok": True, "warnings": errors}

    @app.get("/api/sectors/{code}/stocks")
    def sector_stocks(code: str):
        try:
            frame = fetch_sector_constituents(code)
            cache_members(code, frame)
            cols = ["code", "name", "close", "pct_change", "amount", "turnover", "market_cap", "pe", "pb"]
            view = frame.reindex(columns=cols).astype(object)
            view = view.where(pd.notna(view), None)
            return {"items": view.to_dict("records")}
        except Exception as exc:
            raise HTTPException(502, detail=str(exc)) from exc

    @app.get("/api/watchlist")
    def watchlist(quotes: bool = False):
        with connect() as conn:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY pinned DESC, added_at DESC").fetchall()
            items=[dict(x) for x in rows]
            links = conn.execute("""SELECT m.* FROM sector_membership m
                WHERE EXISTS (SELECT 1 FROM watchlist w WHERE w.item_type IN ('sector','industry','concept') AND w.item_code=m.sector_code)
                AND EXISTS (SELECT 1 FROM watchlist w WHERE w.item_type='stock' AND w.item_code=m.stock_code)
                """).fetchall()
            latest_stock=conn.execute('SELECT MAX(trade_date) FROM stock_daily').fetchone()[0]
            market={}
            if latest_stock:
                for x in conn.execute('SELECT code,close,pct_change FROM stock_daily WHERE trade_date=?',(latest_stock,)):
                    market[('stock',x['code'])]={'current_price':x['close'],'current_pct':x['pct_change'],
                                                 'quote_time':latest_stock,'quote_live':False}
            for key in ('fund_flow_industry_1','fund_flow_concept_1'):
                row=conn.execute('SELECT value FROM app_metadata WHERE key=?',(key,)).fetchone()
                if row:
                    for x in json.loads(row[0]).get('items',[]):
                        market[('sector',x.get('code'))]={'current_price':x.get('close'),
                            'current_pct':x.get('pct_change'),'quote_time':x.get('collected_at'),
                            'quote_live':False}
            for x in conn.execute('SELECT code,pct_change,collected_at FROM sector_snapshot ORDER BY collected_at DESC'):
                market.setdefault(('sector',x['code']),{'current_price':None,'current_pct':x['pct_change'],
                                                        'quote_time':x['collected_at'],'quote_live':False})
        sector_items=[x for x in items if x['item_type']!='stock' and str(x['item_code']).startswith('BK')]
        if quotes and sector_items:
            try:
                from . import DFCF
                response=DFCF.quotes(['90.'+x['item_code'] for x in sector_items])
                for x in response['raw']['data'].get('diff') or []:
                    stamp=datetime.fromtimestamp(x['f124']).astimezone().isoformat(timespec='seconds') if x.get('f124') else None
                    market[('sector',x.get('f12'))]={'current_price':x.get('f2'),'current_pct':x.get('f3'),
                                                      'quote_time':stamp,'quote_live':True}
            except Exception:
                pass
        for item in items:
            group='stock' if item['item_type']=='stock' else 'sector'
            item.update(market.get((group,item['item_code']),{'current_price':None,'current_pct':None,
                                                               'quote_time':None,'quote_live':False}))
        return {"items":items,"links":[dict(x) for x in links],"stock_trade_date":latest_stock}

    def cache_members(code, frame):
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        members = []
        for value in frame.get('code', []):
            text = str(value).removesuffix('.0')
            for prefix in ('sh', 'sz', 'bj'):
                text = text.removeprefix(prefix)
            if text.isdigit() and len(text) <= 6:
                members.append((code, text.zfill(6), now))
        with connect() as conn:
            conn.executemany('INSERT OR REPLACE INTO sector_membership VALUES (?, ?, ?)', members)
            conn.commit()

    @app.post('/api/watchlist/refresh-links')
    def refresh_watch_links():
        with connect() as conn:
            boards = conn.execute("SELECT DISTINCT item_code FROM watchlist WHERE item_type IN ('sector','industry','concept')").fetchall()
        warnings = []
        for board in boards:
            code = board['item_code']
            try:
                frame = fetch_sector_constituents(code)
                if frame.empty:
                    raise ValueError('未返回成分股')
                cache_members(code, frame)
            except Exception:
                warnings.append(f'{code} 关联读取失败，保留已有记录')
        return {'warnings': warnings}

    @app.post("/api/watchlist")
    def add_watch(item: WatchItem):
        now = datetime.now().astimezone()
        expires = add_calendar_months(now, 3)
        with connect() as conn:
            conn.execute("""INSERT INTO watchlist
                (item_type,item_code,item_name,added_at,expires_at,note) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_type,item_code) DO UPDATE SET item_name=excluded.item_name,
                added_at=excluded.added_at, expires_at=excluded.expires_at, note=excluded.note""", (
                item.item_type, item.item_code, item.item_name, now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"), item.note,
            ))
            conn.commit()
        return {"ok": True}

    @app.post("/api/watchlist/{item_type}/{item_code}/extend")
    def extend_watch(item_type: str, item_code: str, period: str):
        if period not in ("15d", "1m"):
            raise HTTPException(422, detail="延期选项无效")
        now = datetime.now().astimezone()
        with connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM watchlist WHERE item_type=? AND item_code=?",
                (item_type, item_code),
            ).fetchone()
            if not row:
                raise HTTPException(404, detail="关注记录不存在")
            try:
                current = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else now
            except ValueError:
                current = now
            if current.tzinfo is None:
                current = current.replace(tzinfo=now.tzinfo)
            base = max(current, now)
            expires = base + timedelta(days=15) if period == "15d" else add_calendar_months(base, 1)
            value = expires.isoformat(timespec="seconds")
            conn.execute(
                "UPDATE watchlist SET expires_at=? WHERE item_type=? AND item_code=?",
                (value, item_type, item_code),
            )
            conn.commit()
        return {"ok": True, "expires_at": value}

    @app.post("/api/watchlist/{item_type}/{item_code}/pin")
    def pin_watch(item_type: str, item_code: str, pinned: bool = True):
        with connect() as conn:
            result = conn.execute(
                "UPDATE watchlist SET pinned=? WHERE item_type=? AND item_code=?",
                (int(pinned), item_type, item_code),
            )
            if not result.rowcount:
                raise HTTPException(404, detail="关注记录不存在")
            conn.commit()
        return {"ok": True, "pinned": pinned}

    @app.delete("/api/watchlist/{item_type}/{item_code}")
    def remove_watch(item_type: str, item_code: str):
        with connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE item_type=? AND item_code=?", (item_type, item_code))
            conn.commit()
        return {"ok": True}

    from .details import register_details
    register_details(app, connect)
    from .activity import register_activity
    register_activity(app, connect)
    from .dfcf_diagnostics import register_dfcf_diagnostics
    register_dfcf_diagnostics(app, connect, static_dir)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="启动板块雷达仪表盘")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(create_app(args.root), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
