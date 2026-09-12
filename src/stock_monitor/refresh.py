from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import pandas as pd
from . import dfcf_provider as provider
from .core import Store, normalize_stocks,calculate_streaks


def refresh_spot(root):
    def job(kind):
        if kind=='summary':
            data=provider.market_summary()
            store=Store(root/'data'/'market.db')
            try:
                store.initialize()
                old_row=store.conn.execute("SELECT value FROM app_metadata WHERE key='market_summary'").fetchone()
                if data.get('amount_change_yuan') is None and old_row:
                    old=json.loads(old_row[0])
                    same_day=str(old.get('reference_time',''))[:10] == str(data.get('reference_time',''))[:10]
                    if same_day and old.get('amount_change_yuan') is not None:
                        data['amount_change_yuan']=old['amount_change_yuan']
                        data['amount_change_cached']=True
                store.set_metadata('market_summary',json.dumps(data,ensure_ascii=False))
            finally:store.close()
            return {'module':kind,'ok':True,'date':data['reference_time']+'（上证参考时间）','rows':1}
        flow_frames=None
        if kind in ('industry','concept'):
            flow_frames={period:provider.fund_flow_sectors(kind,period) for period in (1,5,10)}
            frame=flow_frames[1]
        else:
            frame=provider.stocks() if kind=='stocks' else provider.indices()
        store=Store(root/'data'/'market.db')
        try:
            store.initialize()
            if kind=='stocks':
                date=frame.attrs['trade_date']
                frame=normalize_stocks(frame,date)
                frame=calculate_streaks(frame,store.latest_stocks_before(date))
                store.save_stocks(frame)
            elif kind=='indices':
                date=frame['trade_date'].max()
                store.save_indices(frame)
            else:
                date=frame['collected_at'].max()+'（东方财富源端时间）'
                store.save_sectors(frame)
                for period,period_frame in flow_frames.items():
                    view=period_frame.astype(object).where(pd.notna(period_frame),None)
                    payload={'collected_at':period_frame['collected_at'].max(),
                             'items':view.to_dict('records'),'period':period,
                             'source':period_frame.attrs['source'],
                             'source_url':period_frame.attrs['source_url'],
                             'endpoint':period_frame.attrs['endpoint']}
                    store.set_metadata(f'fund_flow_{kind}_{period}',json.dumps(payload,ensure_ascii=False))
            store.set_metadata(kind+'_source','东方财富')
            if kind in ('industry','concept'):store.set_metadata('sectors_source','东方财富')
            return {'module':kind,'ok':True,'date':date,
                    'rows':sum(len(x) for x in flow_frames.values()) if flow_frames else len(frame)}
        finally:store.close()
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(job,k):k for k in ('summary','stocks','indices','industry','concept')}
        for future in as_completed(futures):
            try:results.append(future.result())
            except Exception as exc:results.append({'module':futures[future],'ok':False,'error':str(exc)[:250]})
    labels={'summary':'上证及沪深京市场概况','stocks':'个股','indices':'指数','industry':'行业','concept':'概念'}
    warnings=[labels[r['module']]+'更新失败，保留旧缓存：'+r['error'] for r in results if not r['ok']]
    return {'ok':not warnings,'warnings':warnings,'results':results}
