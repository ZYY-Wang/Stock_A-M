import pandas as pd
from fastapi.testclient import TestClient
from stock_monitor.core import Store
from stock_monitor.web import create_app


def test_signals_empty_and_divergence(tmp_path):
    client=TestClient(create_app(tmp_path))
    assert client.get('/api/market-signals').json()['available'] is False
    store=Store(tmp_path/'data'/'market.db')
    store.initialize()
    store.save_indices(pd.DataFrame([dict(trade_date='2026-09-09',code='000001',name='上证指数',close=3951,pct_change=1.2,amount=100)]))
    store.save_stocks(pd.DataFrame([dict(trade_date='2026-09-09',code=f'{i:06}',name='测试',close=10,pct_change=-6 if i<7 else 0,amount=10,streak=-1,direction=-1) for i in range(10)]))
    store.close()
    d=client.get('/api/market-signals').json()
    assert d['index']['close']==3951
    assert len(d['alerts'])==4
    assert any('分化' in x for x in d['alerts'])
