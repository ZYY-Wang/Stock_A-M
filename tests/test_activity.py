from fastapi.testclient import TestClient
from stock_monitor.web import create_app


def test_activity_cache_preserved_on_failure(tmp_path,monkeypatch):
    client=TestClient(create_app(tmp_path))
    assert client.get('/api/board-activity').json()['items']==[]
    data={'source_time':'2026-09-09 15:00:00','fetched_at':'2026-09-10T00:00:00','total':1,'items':[{'code':'BK001','count':10}]}
    monkeypatch.setattr('stock_monitor.activity.fetch_activity',lambda:data)
    assert client.post('/api/board-activity/refresh').json()==data
    def fail():
        raise ValueError('offline')
    monkeypatch.setattr('stock_monitor.activity.fetch_activity',fail)
    assert client.post('/api/board-activity/refresh').status_code==502
    assert client.get('/api/board-activity').json()==data
