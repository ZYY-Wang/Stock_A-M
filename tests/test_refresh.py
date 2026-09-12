import pandas as pd
from fastapi.testclient import TestClient
from stock_monitor.web import create_app


def test_refresh_isolation(tmp_path,monkeypatch):
    monkeypatch.setattr('stock_monitor.refresh.provider.market_summary',lambda:dict(reference_time='2026-09-11 15:43:32',up=2,flat=1,down=3,source='东方财富'))
    def fail(): raise ValueError('stock offline')
    monkeypatch.setattr('stock_monitor.refresh.provider.stocks',fail)
    monkeypatch.setattr('stock_monitor.refresh.provider.indices',lambda:pd.DataFrame([dict(code='000001',name='上证指数',close=100,pct_change=1,amount=1,trade_date='2026-09-11')]))
    def flow(kind,period):
        frame=pd.DataFrame([dict(code='BK001' if kind=='industry' else 'BK002',name=kind,
            sector_type=kind,collected_at='2026-09-11T15:00:01',pct_change=1,net_flow=2,
            flow_direction='in',flow_rank=1)])
        frame.attrs.update(source='东方财富 · 板块资金流',source_url='https://data.eastmoney.com',endpoint='eastmoney')
        return frame
    monkeypatch.setattr('stock_monitor.refresh.provider.fund_flow_sectors',flow)
    client=TestClient(create_app(tmp_path))
    data=client.post('/api/refresh').json()
    assert len(data['warnings'])==1
    assert sum(r['ok'] for r in data['results'])==4
    assert client.get('/api/market-signals').json()['index']['trade_date']=='2026-09-11'
    for kind in ('industry','concept'):
        assert len(client.get('/api/sectors',params={'sector_type':kind}).json()['items'])==1
