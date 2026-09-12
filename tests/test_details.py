from fastapi.testclient import TestClient
from stock_monitor.web import create_app
from datetime import date
from stock_monitor import details


def test_detail_cache_offline_and_validation(tmp_path, monkeypatch):
    client=TestClient(create_app(tmp_path))
    assert client.get('/api/stocks/invalid/detail').status_code==422
    assert client.get('/api/stocks/000988/detail').json()['cached'] is False
    calls=[]
    def fetch(ticker):
        calls.append(ticker)
        return [dict(date=date.today().isoformat(),open=10,close=11,high=12,low=9,volume=100)]
    monkeypatch.setattr('stock_monitor.details.fetch_daily',fetch)
    data=client.post('/api/stocks/000988/detail/refresh').json()
    assert data['rows'][0]['close']==11
    assert len(calls)==2
    assert client.get('/api/stocks/000988/detail').json()['cached']
    assert len(calls)==2
    def fail(ticker):
        raise ValueError('offline')
    monkeypatch.setattr('stock_monitor.details.fetch_daily',fail)
    monkeypatch.setattr('stock_monitor.details.fetch_daily_fallback',fail)
    data=client.post('/api/stocks/000988/detail/refresh').json()
    assert len(data['warnings'])==2
    assert data['rows'][0]['close']==11


def test_eastmoney_daily_history_parser(monkeypatch):
    seen = {}
    def history(secid, start, end, adjust):
        seen.update(secid=secid, start=start, end=end, adjust=adjust)
        return {'raw': {'data': {'klines': [
            '2026-09-11,10.00,10.50,10.80,9.90,12345,99887766,8.20,5.00,0.50,3.21'
        ]}}}
    monkeypatch.setattr(details.DFCF, 'history', history)
    rows = details.fetch_daily('sz000988')
    assert seen['secid'] == '0.000988'
    assert seen['adjust'] == 1
    assert rows == [{'date': '2026-09-11', 'open': 10.0, 'close': 10.5, 'high': 10.8,
                     'low': 9.9, 'volume': 12345.0, 'amount': 99887766.0,
                     'amplitude': 8.2, 'pct_change': 5.0, 'change': 0.5,
                     'turnover': 3.21}]


def test_manual_eastmoney_quote_refresh_is_independent(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path))
    quote = {'close': 30.86, 'pct_change': 10.02, 'amount': 1.04e9, 'turnover': 8.8,
             'market_cap': 12e9, 'float_market_cap': 9e9, 'pe': 24.5, 'pb': 3.2,
             'quote_time': '2026-09-11T15:00:00+08:00'}
    calls = []
    monkeypatch.setattr(details, 'fetch_quote', lambda code: calls.append(code) or quote)
    data = client.post('/api/stocks/002902/detail/quote/refresh').json()
    assert calls == ['002902']
    assert data['snapshot']['turnover'] == 8.8
    assert data['snapshot']['market_cap'] == 12e9
    assert data['quote_fetched_at']
    assert client.get('/api/stocks/002902/detail').json()['snapshot']['pe'] == 24.5
    monkeypatch.setattr(details, 'fetch_quote', lambda code: (_ for _ in ()).throw(ValueError('offline')))
    data = client.post('/api/stocks/002902/detail/quote/refresh').json()
    assert data['warnings'] == ['东方财富当前行情更新失败，若有缓存则继续显示缓存']
    assert data['snapshot']['close'] == 30.86
