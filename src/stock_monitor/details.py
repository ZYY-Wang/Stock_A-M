"""On-demand, bounded daily-price cache; no company documents are downloaded."""
import json
import math
import re
from datetime import datetime, timedelta

import requests
from fastapi import HTTPException

from . import DFCF


def symbol(code):
    if not re.fullmatch(r'[0-9]{6}', code):
        raise HTTPException(422, '股票代码须为6位数字')
    return ('sh' if code.startswith('6') else 'bj' if code.startswith(('4', '8', '92')) else 'sz') + code


def eastmoney_secid(code):
    symbol(code)
    return ('1.' if code.startswith('6') else '0.') + code


def fetch_quote(code):
    response = DFCF.quote(eastmoney_secid(code))
    data = response['raw']['data']
    def number(field):
        value = data.get(field)
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None
    if number('f43') is None:
        raise ValueError('东方财富未返回有效个股行情')
    stamp = data.get('f86')
    quote_time = datetime.fromtimestamp(stamp).astimezone().isoformat(timespec='seconds') if isinstance(stamp, (int, float)) else None
    return {'close': number('f43'), 'pct_change': number('f170'), 'amount': number('f48'),
            'volume_ratio': number('f10'), 'turnover': number('f168'), 'market_cap': number('f116'),
            'float_market_cap': number('f117'), 'pe': number('f162'), 'pb': number('f167'),
            'high': number('f44'), 'low': number('f45'), 'open': number('f46'),
            'prev_close': number('f60'), 'amplitude': number('f171'), 'quote_time': quote_time}


def fetch_daily(ticker):
    code = ticker[2:]
    secid = ('1.' if ticker.startswith('sh') else '0.') + code
    start = (datetime.now() - timedelta(days=800)).strftime('%Y%m%d')
    response = DFCF.history(secid, start, '20500101', adjust=1)
    rows = response['raw']['data'].get('klines') or []
    result = []
    for row in rows:
        parts = row.split(',')
        if len(parts) < 11:
            continue
        date = datetime.strptime(parts[0], '%Y-%m-%d').date().isoformat()
        values = [float(v) for v in parts[1:11]]
        if all(math.isfinite(v) for v in values) and min(values[:4]) > 0:
            result.append(dict(date=date, open=values[0], close=values[1], high=values[2],
                               low=values[3], volume=values[4], amount=values[5],
                               amplitude=values[6], pct_change=values[7], change=values[8],
                               turnover=values[9]))
    if not result:
        raise ValueError('数据源未返回有效日线')
    return sorted({r['date']: r for r in result}.values(), key=lambda r: r['date'])[-260:]


def fetch_daily_fallback(ticker):
    """仅在东方财富历史域名不可达时使用，并在返回页面明确标注来源。"""
    session = requests.Session()
    session.trust_env = False
    response = session.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                           params={'param': f'{ticker},day,,,260,qfq'}, timeout=(5, 15))
    response.raise_for_status()
    data = response.json()['data'][ticker]
    rows = data.get('qfqday') or data.get('day') or []
    result = []
    for row in rows:
        date = datetime.strptime(row[0], '%Y-%m-%d').date().isoformat()
        values = [float(v) for v in row[1:6]]
        if len(values) == 5 and all(math.isfinite(v) for v in values) and min(values[:4]) > 0:
            result.append(dict(date=date, open=values[0], close=values[1], high=values[2],
                               low=values[3], volume=values[4]))
    if not result:
        raise ValueError('备用数据源未返回有效日线')
    return sorted({r['date']: r for r in result}.values(), key=lambda r: r['date'])[-260:]


def register_details(app, connect):
    def initialize(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS detail_cache (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL, accessed_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT '东方财富')")
        columns = {row[1] for row in conn.execute('PRAGMA table_info(detail_cache)')}
        if 'source' not in columns:
            conn.execute("ALTER TABLE detail_cache ADD COLUMN source TEXT NOT NULL DEFAULT '腾讯财经（旧缓存）'")
        conn.execute('''CREATE TABLE IF NOT EXISTS detail_quote_cache (
            code TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL, accessed_at TEXT NOT NULL)''')
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        conn.execute("DELETE FROM detail_cache WHERE accessed_at<? AND ticker<>'sh000300' AND substr(ticker,3) NOT IN (SELECT item_code FROM watchlist WHERE item_type='stock')", (cutoff,))
        conn.execute("DELETE FROM detail_quote_cache WHERE accessed_at<? AND code NOT IN (SELECT item_code FROM watchlist WHERE item_type='stock')", (cutoff,))
        conn.commit()

    def read(code, update_history=False, update_quote=False):
        ticker = symbol(code)
        now = datetime.now().isoformat(timespec='seconds')
        warnings = []
        with connect() as conn:
            initialize(conn)
            if update_quote:
                try:
                    quote = fetch_quote(code)
                    conn.execute('INSERT OR REPLACE INTO detail_quote_cache VALUES (?,?,?,?)',
                                 (code, json.dumps(quote), now, now))
                except Exception:
                    warnings.append('东方财富当前行情更新失败，若有缓存则继续显示缓存')
            if update_history:
                for key in (ticker, 'sh000300'):
                    try:
                        rows = fetch_daily(key)
                        history_source = '东方财富'
                    except Exception:
                        try:
                            rows = fetch_daily_fallback(key)
                            history_source = '腾讯财经（东方财富连接失败后的备用）'
                            warnings.append(('个股' if key == ticker else '沪深300') + '日线使用腾讯备用数据')
                        except Exception:
                            warnings.append(('个股' if key == ticker else '沪深300') + '日线更新失败，若有缓存则继续显示缓存')
                            continue
                    try:
                        # Replace adjusted history as a whole to avoid mixing adjustment bases.
                        conn.execute('''INSERT OR REPLACE INTO detail_cache
                            (ticker,payload,fetched_at,accessed_at,source) VALUES (?,?,?,?,?)''',
                            (key, json.dumps(rows), now, now, history_source))
                    except Exception:
                        warnings.append(('个股' if key == ticker else '沪深300') + '日线更新失败，若有缓存则继续显示缓存')
            cached = conn.execute('SELECT * FROM detail_cache WHERE ticker=?', (ticker,)).fetchone()
            conn.execute('UPDATE detail_cache SET accessed_at=? WHERE ticker=?', (now, ticker))
            quote_cached = conn.execute('SELECT * FROM detail_quote_cache WHERE code=?', (code,)).fetchone()
            conn.execute('UPDATE detail_quote_cache SET accessed_at=? WHERE code=?', (now, code))
            benchmark = conn.execute('SELECT payload,source FROM detail_cache WHERE ticker=?', ('sh000300',)).fetchone()
            watched = conn.execute("SELECT added_at FROM watchlist WHERE item_type='stock' AND item_code=?", (code,)).fetchone()
            info = conn.execute('SELECT * FROM stock_daily WHERE code=? ORDER BY trade_date DESC LIMIT 1', (code,)).fetchone()
            cutoff = (datetime.now() - timedelta(days=400)).date().isoformat()
            rows = json.loads(cached['payload'])[-260:] if cached else []
            snapshot = {}
            if info:
                snapshot = {key: info[key] for key in ('trade_date','close','pct_change','amount','streak')}
                try:
                    snapshot.update(json.loads(info['payload'] or '{}'))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            if quote_cached:
                snapshot.update(json.loads(quote_cached['payload']))
            comparisons = []
            if benchmark:
                comparisons.append({'name': '沪深300', 'source': benchmark['source'],
                                    'rows': json.loads(benchmark['payload'])})
            # Only explicitly observed membership can select a board benchmark.
            boards = conn.execute('SELECT DISTINCT h.code,h.name,h.source FROM sector_history h JOIN sector_membership m ON m.sector_code=h.code WHERE m.stock_code=?', (code,)).fetchall()
            for board in boards:
                history = conn.execute('SELECT trade_date AS date, close FROM sector_history WHERE code=? AND source=? AND trade_date>=? AND close>0 ORDER BY trade_date', (board['code'], board['source'], cutoff)).fetchall()
                comparisons.append({'name': board['name'] + '（' + board['source'] + '）',
                                    'source': board['source'], 'rows': [dict(r) for r in history]})
            memberships = []
            for member in conn.execute('SELECT DISTINCT sector_code FROM sector_membership WHERE stock_code=? ORDER BY observed_at DESC', (code,)):
                board_code = member['sector_code']
                named = conn.execute("SELECT item_name FROM watchlist WHERE item_code=? AND item_type IN ('sector','industry','concept') LIMIT 1", (board_code,)).fetchone()
                if not named:
                    named = conn.execute('SELECT name AS item_name FROM sector_snapshot WHERE code=? ORDER BY collected_at DESC LIMIT 1', (board_code,)).fetchone()
                if not named:
                    named = conn.execute('SELECT name AS item_name FROM sector_history WHERE code=? ORDER BY trade_date DESC LIMIT 1', (board_code,)).fetchone()
                memberships.append({'code': board_code, 'name': named['item_name'] if named else board_code})
            conn.commit()
        return {'code': code, 'name': info['name'] if info else code, 'rows': rows,
                'cached': bool(cached), 'fetched_at': cached['fetched_at'] if cached else None,
                'source': (cached['source'] if cached else '东方财富') + ' · 个股前复权日线 · 成交量单位：手',
                'watch_date': watched['added_at'][:10] if watched else None,
                'snapshot': snapshot, 'memberships': memberships,
                'quote_fetched_at': quote_cached['fetched_at'] if quote_cached else None,
                'comparisons': comparisons, 'warnings': warnings}

    @app.get('/api/stocks/{code}/detail')
    def detail(code: str):
        return read(code)

    @app.post('/api/stocks/{code}/detail/refresh')
    def refresh_detail(code: str):
        return read(code, update_history=True)

    @app.post('/api/stocks/{code}/detail/quote/refresh')
    def refresh_detail_quote(code: str):
        return read(code, update_quote=True)
