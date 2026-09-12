from fastapi.testclient import TestClient

from stock_monitor.web import create_app
from stock_monitor.core import Store
import pandas as pd
import pytest


def test_stock_search(tmp_path):
    store = Store(tmp_path / 'data' / 'market.db')
    store.initialize()
    store.save_stocks(pd.DataFrame([
        dict(trade_date=d,code=c,name=n,close=10,pct_change=1,amount=100,streak=1,direction=1)
        for d,c,n in [('2026-09-08','000988','旧名称'),('2026-09-09','000988','华工科技'),('2026-09-09','600001','测试股票')]
    ]))
    store.close()
    client=TestClient(create_app(tmp_path))
    for q in ['华工','000988','0988',' 华工科技 ']:
        data=client.get('/api/stocks/search',params={'q':q}).json()
        assert data['total']==1
        assert data['items'][0]['code']=='000988'
        assert data['trade_date']=='2026-09-09'
    for q in ['', '%', '_', "' OR 1=1--", '旧名称']:
        assert client.get('/api/stocks/search',params={'q':q}).json()['items']==[]


def test_watch_links_many_to_many_and_failure(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path))
    for kind, code in [('industry','A'),('concept','B'),('stock','000001'),('stock','000002')]:
        client.post('/api/watchlist', json={'item_type':kind,'item_code':code,'item_name':code})
    def members(code):
        return pd.DataFrame({'code':['000001','000002'] if code=='A' else ['000001']})
    monkeypatch.setattr('stock_monitor.web.fetch_sector_constituents', members)
    assert client.post('/api/watchlist/refresh-links').json()['warnings']==[]
    links=client.get('/api/watchlist').json()['links']
    assert {(x['sector_code'],x['stock_code']) for x in links}=={('A','000001'),('A','000002'),('B','000001')}
    # Reopening the application retains cached evidence without network requests.
    assert len(TestClient(create_app(tmp_path)).get('/api/watchlist').json()['links'])==3
    def fail(code):
        raise RuntimeError('offline')
    monkeypatch.setattr('stock_monitor.web.fetch_sector_constituents', fail)
    assert len(client.post('/api/watchlist/refresh-links').json()['warnings'])==2
    assert len(client.get('/api/watchlist').json()['links'])==3
    client.delete('/api/watchlist/stock/000002')
    assert len(client.get('/api/watchlist').json()['links'])==2


def test_watchlist_round_trip(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/watchlist", json={
        "item_type": "industry", "item_code": "new_test", "item_name": "测试行业"
    })
    assert response.status_code == 200
    items = client.get("/api/watchlist").json()["items"]
    assert items[0]["item_name"] == "测试行业"
    assert client.delete("/api/watchlist/industry/new_test").status_code == 200
    assert client.get("/api/watchlist").json()["items"] == []


def test_watchlist_extend_menu_actions(tmp_path):
    client = TestClient(create_app(tmp_path))
    client.post('/api/watchlist', json={
        'item_type': 'stock', 'item_code': '000988', 'item_name': '华工科技'
    })
    store = Store(tmp_path / 'data' / 'market.db')
    store.initialize()
    store.conn.execute(
        "UPDATE watchlist SET expires_at=? WHERE item_type='stock' AND item_code='000988'",
        ('2099-01-31T12:00:00+08:00',),
    )
    store.conn.commit()
    store.close()
    response = client.post('/api/watchlist/stock/000988/extend', params={'period': '1m'})
    assert response.status_code == 200
    assert response.json()['expires_at'] == '2099-02-28T12:00:00+08:00'
    response = client.post('/api/watchlist/stock/000988/extend', params={'period': '15d'})
    assert response.json()['expires_at'] == '2099-03-15T12:00:00+08:00'
    assert client.post('/api/watchlist/stock/000988/extend', params={'period': 'bad'}).status_code == 422
    assert client.post('/api/watchlist/stock/missing/extend', params={'period': '15d'}).status_code == 404


def test_watchlist_pin_and_preserve_pin_on_renew(tmp_path):
    client = TestClient(create_app(tmp_path))
    for code in ('000001', '000002'):
        client.post('/api/watchlist', json={'item_type': 'stock', 'item_code': code, 'item_name': code})
    assert client.post('/api/watchlist/stock/000001/pin', params={'pinned': True}).json()['pinned'] is True
    items = client.get('/api/watchlist').json()['items']
    assert items[0]['item_code'] == '000001'
    assert items[0]['pinned'] == 1
    client.post('/api/watchlist', json={'item_type': 'stock', 'item_code': '000001', 'item_name': '更新名称'})
    assert client.get('/api/watchlist').json()['items'][0]['pinned'] == 1
    assert client.post('/api/watchlist/stock/000001/pin', params={'pinned': False}).json()['pinned'] is False
    assert client.post('/api/watchlist/stock/missing/pin').status_code == 404


def test_watchlist_includes_latest_stock_price_and_change(tmp_path):
    store=Store(tmp_path/'data'/'market.db');store.initialize()
    store.save_stocks(pd.DataFrame([dict(trade_date='2026-09-11',code='000988',name='华工科技',
        close=88.12,pct_change=-1.23,amount=100,streak=-1,direction=-1)]))
    store.close()
    client=TestClient(create_app(tmp_path))
    client.post('/api/watchlist',json={'item_type':'stock','item_code':'000988','item_name':'华工科技'})
    item=client.get('/api/watchlist').json()['items'][0]
    assert item['current_price']==88.12
    assert item['current_pct']==-1.23
    assert item['quote_time']=='2026-09-11'


def test_empty_overview(tmp_path):
    client = TestClient(create_app(tmp_path))
    data = client.get("/api/overview").json()
    assert data == {"trade_date": None, "sector_time": None, "market": None,
                    "sources": {"stocks": None, "indices": None, "sectors": None}}


def test_same_day_stock_snapshot_is_replaced_not_merged(tmp_path):
    store=Store(tmp_path/'data'/'market.db');store.initialize()
    def frame(codes):
        return pd.DataFrame([dict(trade_date='2026-09-11',code=c,name=c,close=10,
            pct_change=1,amount=1,streak=1,direction=1) for c in codes])
    store.save_stocks(frame(['000001','000002']))
    store.save_stocks(frame(['000001']))
    count=store.conn.execute("SELECT COUNT(*) FROM stock_daily WHERE trade_date='2026-09-11'").fetchone()[0]
    store.close()
    assert count==1


@pytest.mark.parametrize('period', [1, 5, 10])
def test_concept_period_uses_dfcf_fund_flow(tmp_path, period, monkeypatch):
    def fetch(kind, selected_period):
        assert (kind,selected_period)==('concept',period)
        frame=pd.DataFrame([dict(collected_at='2026-09-11T15:00:00+08:00',sector_type='concept',
            code='BK001',name='测试概念',pct_change=period,net_flow=100,
            flow_direction='in',flow_rank=1)])
        frame.attrs.update(source='东方财富 · 板块资金流',source_url='https://data.eastmoney.com/bkzj/gn.html',endpoint='https://push2.eastmoney.com')
        return frame
    monkeypatch.setattr('stock_monitor.web.fund_flow_sectors',fetch)
    client = TestClient(create_app(tmp_path))
    response = client.get('/api/sectors', params={'period': period, 'sector_type': 'concept'})
    assert response.status_code == 200
    data=response.json();items = data['items']
    assert len(items) == 1
    assert items[0]['code'] == 'BK001'
    assert items[0]['pct_change'] == period
    assert data['source']=='东方财富 · 板块资金流'
    assert items[0]['net_flow']==100
