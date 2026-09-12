from fastapi.testclient import TestClient

from stock_monitor.web import create_app


def test_dfcf_diagnostics_and_history(tmp_path, monkeypatch):
    def quotes(secids):
        return {'endpoint':'https://push2.eastmoney.com/api/qt/ulist.np/get','raw':{'data':{'diff':[
            {'f13':int(secid.split('.')[0]), 'f12':secid.split('.')[-1], 'f14':'测试指数',
             'f2':3000.1, 'f4':10.2, 'f3':0.34, 'f17':2990, 'f15':3010, 'f16':2980,
             'f18':2989.9, 'f5':123, 'f6':456, 'f124':1789142400} for secid in secids]}}}
    def stocks(page=1,size=100):
        return {'endpoint':'https://push2.eastmoney.com/api/qt/clist/get','raw':{'data':{
            'total':2,'diff':[{'f12':'000001','f14':'平安银行','f2':10,'f3':1,'f5':2,'f6':3}]}}}
    monkeypatch.setattr('stock_monitor.dfcf_diagnostics.DFCF.quotes',quotes)
    monkeypatch.setattr('stock_monitor.dfcf_diagnostics.DFCF.stocks',stocks)
    client=TestClient(create_app(tmp_path))
    assert client.get('/dfcf-test').status_code==200
    result=client.post('/api/dfcf-diagnostics/run',json={'network_label':'VPN关闭'}).json()
    assert result['status']=='success'
    assert len(result['indices'])==4
    assert result['stocks']['total']==2
    history=client.get('/api/dfcf-diagnostics/history').json()['items']
    assert history[0]['network_label']=='VPN关闭'
    assert history[0]['stocks']['sample'][0]['code']=='000001'
