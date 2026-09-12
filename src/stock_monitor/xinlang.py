"""新浪独立备用接口：正式刷新流程不自动调用。"""
import json
import math
import re
import time
from datetime import datetime
import pandas as pd
import requests


def get(url, **kwargs):
    for attempt in range(2):
        try:
            r=requests.get(url,timeout=(5,12),**kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt: raise
            time.sleep(1)


def indices():
    symbols=['sh000001','sz399001','sz399006','sh000300','sh000905','sh000852']
    r=get('https://hq.sinajs.cn/list='+','.join(symbols),headers={'Referer':'https://finance.sina.com.cn/'})
    r.encoding='gbk'
    rows=[]
    for ticker,payload in re.findall(r'hq_str_(\w+)="([^"]*)"',r.text):
        v=payload.split(',')
        if len(v)<32: continue
        close,previous=float(v[3]),float(v[2])
        if close<=0 or previous<=0: continue
        date=datetime.strptime(v[30],'%Y-%m-%d').date().isoformat()
        rows.append(dict(code=ticker[2:],name=v[0],trade_date=date,close=close,pct_change=(close/previous-1)*100,amount=float(v[9])))
    if len(rows)!=len(symbols): raise ValueError('新浪指数返回不完整，保留旧缓存')
    return pd.DataFrame(rows)


def market_summary():
    r=get('https://hq.sinajs.cn/list=sh000001,sh000002_zdp,sz399107_zdp',headers={'Referer':'https://finance.sina.com.cn/'})
    r.encoding='gbk'
    parts=dict(re.findall(r'hq_str_(\w+)="([^"]*)"',r.text))
    counts=[]
    for key in ('sh000002_zdp','sz399107_zdp'):
        values=parts[key].split(',')
        if len(values)!=3 or not all(re.fullmatch(r'\d+',v) for v in values):
            raise ValueError('新浪涨跌平汇总不完整')
        counts.append(list(map(int,values)))
    v=parts['sh000001'].split(',')
    close,prev=float(v[3]),float(v[2])
    if not all(math.isfinite(x) and x>0 for x in (close,prev)):raise ValueError('无有效上证指数')
    stamp=datetime.strptime(v[30]+' '+v[31],'%Y-%m-%d %H:%M:%S').isoformat(sep=' ')
    volume,amount=float(v[8]),float(v[9])
    if not all(math.isfinite(x) and x>=0 for x in (volume,amount)):
        raise ValueError('上证成交量或成交额无效')
    return {'close':close,'pct_change':(close/prev-1)*100,
            'volume_hands':volume,'amount_yuan':amount,
            'up':counts[0][0]+counts[1][0],'down':counts[0][1]+counts[1][1],
            'flat':counts[0][2]+counts[1][2], 'reference_time':stamp,
            'fetched_at':datetime.now().astimezone().isoformat(timespec='seconds')}


def stocks():
    base='http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.'
    count=int(get(base+'getHQNodeStockCount',params={'node':'hs_a'}).text.strip('"'))
    if count<1: raise ValueError('新浪股票数量为空')
    rows=[]
    for page in range(1,math.ceil(count/80)+1):
        part=get(base+'getHQNodeData',params={'page':page,'num':80,'sort':'symbol','asc':1,'node':'hs_a','symbol':'','_s_r_a':'page'}).json()
        if not isinstance(part,list) or not part: raise ValueError(f'新浪第{page}页不完整')
        rows.extend(part)
    frame=pd.DataFrame(rows)
    if len(frame)!=count or frame['code'].nunique()!=count: raise ValueError('新浪股票分页数量不一致，保留旧缓存')
    # The list only gives a time of day. Verify the current trading date independently.
    dates=indices()['trade_date'].unique()
    if len(dates)!=1: raise ValueError('新浪交易日期不一致')
    frame=frame.rename(columns={'code':'代码','name':'名称','trade':'最新价','changepercent':'涨跌幅','pricechange':'涨跌额','settlement':'昨收','open':'今开','high':'最高','low':'最低','volume':'成交量','amount':'成交额','turnoverratio':'换手率'})
    frame.attrs['trade_date']=dates[0]
    return frame


def sector(kind):
    url='http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php' if kind=='industry' else 'http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class'
    text=get(url).text
    data=json.loads(text[text.index('{'):])
    frame=pd.DataFrame([v.split(',') for v in data.values()],columns=['code','name','company_count','average','change','pct_change','volume','amount','leader_code','leader_pct','leader_price','leader_change','leader_name'])
    if frame.empty: raise ValueError('新浪板块返回为空')
    for col in ['company_count','pct_change','amount','leader_pct']: frame[col]=pd.to_numeric(frame[col],errors='coerce')
    frame['collected_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    frame['sector_type']=kind
    return frame
