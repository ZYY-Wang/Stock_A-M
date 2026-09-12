import pytest
from stock_monitor import DFCF, xinlang, sina


def test_sina_entry_unchanged():
    assert xinlang.stocks is sina.stocks
    assert xinlang.market_summary is sina.market_summary


def test_dfcf_read_only_parameters(monkeypatch):
    seen=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'rc':0,'data':{'total':2,'diff':[]}}
    def get(url,**kwargs):
        seen.append((url,kwargs))
        return Response()
    monkeypatch.setattr(DFCF.SESSION,'get',get)
    result=DFCF.boards('concept',size=5)
    assert result['raw']['data']['total']==2
    assert seen[0][1]['params']['fs']=='m:90 t:3'
    DFCF.boards('industry',size=5,period=20)
    assert seen[-1][1]['params']['fid']=='f110'
    DFCF.fund_flow_boards('industry',period=5,descending=False,size=10)
    assert seen[-1][1]['params']['fs']=='m:90 s:4'
    assert seen[-1][1]['params']['fid']=='f164'
    assert seen[-1][1]['params']['po']==0
    DFCF.fund_flow_boards('concept',period=10,size=10)
    assert seen[-1][1]['params']['fs']=='m:90 t:3'
    assert seen[-1][1]['params']['fid']=='f174'
    assert seen[0][1]['timeout']==(5,15)
    DFCF.quotes(['1.000001','0.399001'])
    assert seen[-1][1]['params']['secids']=='1.000001,0.399001'
    DFCF.history('90.BK0420','20260601','20260911',0)
    assert seen[-1][1]['params']['fqt']==0
    DFCF.trends('1.000001',2)
    assert seen[-1][1]['params']['fields2']=='f51,f57'
    DFCF.activity(page=2,size=5)
    assert seen[-1][1]['params']['pageindex']==1


def test_invalid_arguments():
    with pytest.raises(ValueError): DFCF.boards('unknown')
    with pytest.raises(ValueError): DFCF.boards(period=10)
    with pytest.raises(ValueError): DFCF.fund_flow_boards(period=3)
    with pytest.raises(ValueError): DFCF.stocks(size=5000)
    with pytest.raises(ValueError): DFCF.quote('bad')
    with pytest.raises(ValueError): DFCF.quotes([])
    with pytest.raises(ValueError): DFCF.history('1.000001','20260912','20260101')


def test_empty_response_fails(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'rc':0,'data':None}
    monkeypatch.setattr(DFCF.SESSION,'get',lambda *a,**kw:Response())
    with pytest.raises(ValueError): DFCF.quote()


def test_primary_network_error_uses_backup(monkeypatch):
    seen=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'rc':0,'data':{'f57':'000001'}}
    def get(url, **kwargs):
        seen.append(url)
        if url.startswith(DFCF.HOST):
            raise DFCF.requests.ConnectionError('primary closed')
        return Response()
    monkeypatch.setattr(DFCF.SESSION,'get',get)
    result=DFCF.quote()
    assert result['endpoint'].startswith(DFCF.FALLBACK_HOST)
    assert result['fallback_from']==DFCF.HOST
    assert len(seen)==2
