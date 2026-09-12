import json
from datetime import datetime
from fastapi import HTTPException

from . import DFCF


CHANGE_TYPES = {
    8201:'火箭发射',8202:'快速反弹',8193:'大笔买入',4:'封涨停板',32:'打开跌停板',
    64:'有大买盘',8207:'竞价上涨',8209:'高开5日线',8211:'向上缺口',8213:'60日新高',
    8215:'60日大幅上涨',8204:'加速下跌',8203:'高台跳水',8208:'竞价下跌',
    8210:'低开5日线',8212:'向下缺口',8216:'60日大幅下跌',8194:'大笔卖出',
    128:'有大卖盘',8:'封跌停板',16:'打开涨停板',8214:'60日新低'
}


def fetch_activity():
    response = DFCF.activity(page=1, size=100)
    data = response['raw']['data']
    stamp = datetime.strptime(str(data['dt']), '%Y%m%d%H%M%S').isoformat(sep=' ')
    items=[]
    for row in data['allbk']:
        stock=row.get('ms') or {}
        types = [{'code':x.get('t'), 'name':CHANGE_TYPES.get(x.get('t'),f"类型{x.get('t')}"),
                  'count':int(x.get('ct') or 0)} for x in (row.get('ydl') or [])]
        items.append({'code':row['c'],'name':row['n'],'pct_change':float(row['u']),
                      'main_net_inflow':float(row.get('zjl') or 0)*10000,
                      'count':int(row['ct']),'stock_code':stock.get('c'),'stock_name':stock.get('n'),
                      'stock_change_type':CHANGE_TYPES.get(stock.get('t'),f"类型{stock.get('t')}") if stock.get('t') is not None else None,
                      'types':types})
    if not items:
        raise ValueError('未返回板块异动记录')
    return {'source_time':stamp,'fetched_at':datetime.now().isoformat(timespec='seconds'),
            'items':items,'total':int(data.get('tc',len(items))),
            'source':'东方财富 · 当日异动板块监控','endpoint':response['endpoint']}


def register_activity(app, connect):
    @app.get('/api/board-activity')
    def activity():
        with connect() as conn:
            row=conn.execute("SELECT value FROM app_metadata WHERE key='board_activity'").fetchone()
        return json.loads(row[0]) if row else {'items':[], 'total':0,'source_time':None,'fetched_at':None}

    @app.post('/api/board-activity/refresh')
    def refresh():
        try:
            data=fetch_activity()
        except Exception as exc:
            raise HTTPException(502,'板块异动读取失败，已保留旧缓存，请稍后重试') from exc
        with connect() as conn:
            conn.execute("INSERT OR REPLACE INTO app_metadata VALUES ('board_activity',?)",(json.dumps(data,ensure_ascii=False,allow_nan=False),))
            conn.commit()
        return data
