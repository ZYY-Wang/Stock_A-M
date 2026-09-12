"""东方财富页面数据适配层：把原始 f 字段转换为项目现有结构。"""
from __future__ import annotations

import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from . import DFCF


INDEX_NAMES = {
    '1.000001':'上证指数', '0.399001':'深证成指', '0.399006':'创业板指',
    '1.000300':'沪深300', '1.000905':'中证500', '1.000852':'中证1000'
}


def _valid(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _date_from_timestamps(values) -> str:
    dates=[]
    for value in values:
        if isinstance(value,(int,float)) and value > 0:
            dates.append(datetime.fromtimestamp(value).astimezone().date().isoformat())
    if not dates:
        raise ValueError('东方财富未返回有效行情日期')
    return Counter(dates).most_common(1)[0][0]


def indices() -> pd.DataFrame:
    response=DFCF.quotes(INDEX_NAMES)
    rows=response['raw']['data'].get('diff') or []
    by_id={f"{x.get('f13')}.{x.get('f12')}":x for x in rows}
    trade_date=_date_from_timestamps(x.get('f124') for x in rows)
    output=[]
    for secid,name in INDEX_NAMES.items():
        x=by_id.get(secid)
        if not x or _valid(x.get('f2')) is None:
            raise ValueError(f'东方财富指数返回不完整：{name}')
        output.append(dict(code=secid.split('.')[1],name=name,trade_date=trade_date,
                           close=x['f2'],pct_change=_valid(x.get('f3')),amount=_valid(x.get('f6'))))
    frame=pd.DataFrame(output)
    frame.attrs.update(source='东方财富',endpoint=response['endpoint'],trade_date=trade_date)
    return frame


def market_summary() -> dict:
    # 与东方财富“大盘星图”的极速版行情页保持相同口径：
    # 涨跌家数取上证A股、深证A股、北证A股；成交额取上证综指、
    # 深证成指、北证A股。这里只汇总源端指数统计，不逐只统计股票。
    response=DFCF.quotes(['1.000001','1.000002','0.399001','0.399002','0.899050'])
    rows=response['raw']['data'].get('diff') or []
    by_id={f"{x.get('f13')}.{x.get('f12')}":x for x in rows}
    sh=by_id.get('1.000001')
    breadth_rows=[by_id.get(x) for x in ('1.000002','0.399002','0.899050')]
    amount_rows=[by_id.get(x) for x in ('1.000001','0.399001','0.899050')]
    if not sh or any(x is None for x in breadth_rows+amount_rows):
        raise ValueError('东方财富沪深京极速行情返回不完整')
    counts={key:sum(int(x.get(field) or 0) for x in breadth_rows)
            for key,field in [('up','f104'),('down','f105'),('flat','f106')]}
    if sum(counts.values()) <= 0:
        raise ValueError('东方财富沪深京涨跌平家数为空')
    amount_yuan=sum(float(x.get('f6') or 0) for x in amount_rows)
    amount_change=None
    amount_change_error=None
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            changes=list(pool.map(_intraday_amount_change,
                                  ('1.000001','0.399001','0.899050')))
        if all(x is not None for x in changes):
            amount_change=sum(changes)
    except Exception as exc:
        # 历史分时节点偶尔与实时节点可用性不同；不因此丢弃整组行情。
        amount_change_error=f'{type(exc).__name__}: {exc}'[:500]
    source_time=datetime.fromtimestamp(sh['f124']).astimezone().isoformat(sep=' ',timespec='seconds')
    return {'close':float(sh['f2']),'change_points':float(sh['f4']),
            'pct_change':float(sh['f3']),'amount_yuan':amount_yuan,
            'amount_change_yuan':amount_change,'amount_change_cached':False,
            'amount_change_error':amount_change_error,**counts,
            'reference_time':source_time,'fetched_at':datetime.now().astimezone().isoformat(timespec='seconds'),
            'source':'东方财富','scope':'东方财富大盘星图 · 极速版行情页面',
            'endpoint':response['endpoint']}


def _intraday_amount_change(secid: str) -> float | None:
    """按大盘星图页面算法比较当前时刻与昨日同一时刻累计成交额。"""
    response=DFCF.trends(secid,2)
    raw=response['raw']['data'].get('trends') or []
    rows=[]
    for value in raw:
        parts=value.split(',')
        if len(parts) >= 2:
            try:
                rows.append((parts[0],float(parts[1])))
            except (TypeError,ValueError):
                continue
    if len(rows) < 2:
        return None
    latest_date=rows[-1][0].split(' ')[0]
    if rows[0][0].split(' ')[0] == latest_date:
        return None
    latest_clock=rows[-1][0].split(' ',1)[-1]
    yesterday_cut=next((i for i,(stamp,_) in enumerate(rows) if latest_clock in stamp),None)
    today_start=next((i for i,(stamp,_) in enumerate(rows) if latest_date in stamp),None)
    if yesterday_cut is None or today_start is None:
        return None
    end=len(rows)-1
    if today_start == end:
        today_start=end-1
    yesterday=sum(amount for _,amount in rows[:yesterday_cut])
    today=sum(amount for _,amount in rows[today_start:end])
    return today-yesterday


def stocks(workers: int=4) -> pd.DataFrame:
    first=DFCF.stocks(page=1,size=100)
    data=first['raw']['data']; total=int(data.get('total') or 0)
    if total <= 0:
        raise ValueError('东方财富A股总数为空')
    pages=math.ceil(total/100); rows=list(data.get('diff') or [])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(DFCF.stocks,page,100):page for page in range(2,pages+1)}
        for future in as_completed(futures):
            result=future.result()['raw']['data'].get('diff') or []
            if not result:
                raise ValueError(f'东方财富A股第{futures[future]}页为空')
            rows.extend(result)
    unique={str(x.get('f12')):x for x in rows if x.get('f12')}
    if len(unique) != total:
        raise ValueError(f'东方财富A股分页不完整：应有{total}，实得{len(unique)}')
    trade_date=_date_from_timestamps(x.get('f124') for x in unique.values())
    frame=pd.DataFrame([{'代码':code,'名称':x.get('f14'),'最新价':x.get('f2'),
        '涨跌幅':x.get('f3'),'涨跌额':x.get('f4'),'成交量':x.get('f5'),'成交额':x.get('f6'),
        '振幅':x.get('f7'),'换手率':x.get('f8'),'市盈率':x.get('f9'),'量比':x.get('f10'),
        '最高':x.get('f15'),'最低':x.get('f16'),'今开':x.get('f17'),'昨收':x.get('f18'),
        '总市值':x.get('f20'),'流通市值':x.get('f21'),'市净率':x.get('f23')}
        for code,x in unique.items()])
    frame.attrs.update(source='东方财富',endpoint=first['endpoint'],trade_date=trade_date,total=total)
    return frame


def sector(kind: str, period: int=1) -> pd.DataFrame:
    from .sectors import fetch_sector_period
    return fetch_sector_period(kind,period)


def fund_flow_sectors(kind: str, period: int=1) -> pd.DataFrame:
    """板块主力净流入前10与净流出后10，复刻东方财富板块资金流页面。"""
    if kind not in ('industry','concept') or period not in (1,5,10):
        raise ValueError('板块类型或资金周期无效')
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_in=pool.submit(DFCF.fund_flow_boards,kind,period,True,10)
        future_out=pool.submit(DFCF.fund_flow_boards,kind,period,False,10)
        incoming=future_in.result()
        outgoing=future_out.result()
    flow_field={1:'f62',5:'f164',10:'f174'}[period]
    pct_field={1:'f3',5:'f109',10:'f160'}[period]
    pairs=[]
    for direction,response in [('in',incoming),('out',outgoing)]:
        rows=response['raw']['data'].get('diff') or []
        if len(rows) < 10:
            raise ValueError(f'东方财富{kind}{period}日资金流{direction}排行不足10条')
        for rank,x in enumerate(rows[:10],1):
            pairs.append({
                'collected_at':None,'sector_type':kind,'code':x.get('f12'),'name':x.get('f14'),
                'close':pd.to_numeric(x.get('f2'),errors='coerce'),
                'pct_change':pd.to_numeric(x.get(pct_field),errors='coerce'),
                'net_flow':pd.to_numeric(x.get(flow_field),errors='coerce'),
                'flow_direction':direction,'flow_rank':rank,
                'amount':pd.to_numeric(x.get('f6'),errors='coerce'),
                'company_count':None,'leader_code':None,'leader_name':None,'leader_pct':None,
                '_timestamp':x.get('f124') or 0
            })
    timestamps=[x['_timestamp'] for x in pairs if x['_timestamp']]
    if not timestamps:
        raise ValueError('东方财富板块资金流时间为空')
    collected_at=datetime.fromtimestamp(max(timestamps)).astimezone().isoformat(timespec='seconds')
    for x in pairs:
        x['collected_at']=collected_at
        x.pop('_timestamp',None)
    frame=pd.DataFrame(pairs).dropna(subset=['code','name','pct_change','net_flow'])
    if len(frame) != 20:
        raise ValueError('东方财富板块资金流有效记录不足20条')
    base='https://data.eastmoney.com/bkzj/hy.html' if kind=='industry' else 'https://data.eastmoney.com/bkzj/gn.html'
    frame.attrs.update(source='东方财富 · 板块资金流',period=period,
                       source_url=f'{base}?stat={period}',endpoint=incoming['endpoint'])
    return frame.reset_index(drop=True)


def constituents(code: str, workers: int=4) -> pd.DataFrame:
    first=DFCF.constituents(code,page=1,size=100)
    data=first['raw']['data']; total=int(data.get('total') or 0)
    if total <= 0:
        raise ValueError('东方财富未返回板块成分股')
    pages=math.ceil(total/100); rows=list(data.get('diff') or [])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(DFCF.constituents,code,page,100):page for page in range(2,pages+1)}
        for future in as_completed(futures):
            part=future.result()['raw']['data'].get('diff') or []
            if not part:
                raise ValueError(f'东方财富板块成分股第{futures[future]}页为空')
            rows.extend(part)
    unique={str(x.get('f12')):x for x in rows if x.get('f12')}
    if len(unique) != total:
        raise ValueError(f'东方财富成分股分页不完整：应有{total}，实得{len(unique)}')
    frame=pd.DataFrame([{'code':code,'name':x.get('f14'),'close':_valid(x.get('f2')),
        'pct_change':_valid(x.get('f3')),'amount':_valid(x.get('f6')),
        'turnover':_valid(x.get('f8')),'market_cap':_valid(x.get('f20')),
        'float_market_cap':_valid(x.get('f21')),'pe':_valid(x.get('f9')),
        'pb':_valid(x.get('f23'))} for code,x in unique.items()])
    frame.attrs.update(source='东方财富',endpoint=first['endpoint'],total=total)
    return frame.sort_values('pct_change',ascending=False,na_position='last').reset_index(drop=True)
