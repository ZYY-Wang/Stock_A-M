import pandas as pd

from stock_monitor import dfcf_provider as provider


def test_market_summary_uses_dfcf_breadth(monkeypatch):
    rows=[
        {'f13':1,'f12':'000001','f2':3000,'f3':1,'f4':30,'f6':20,'f124':1789142400},
        {'f13':1,'f12':'000002','f104':100,'f105':50,'f106':2},
        {'f13':0,'f12':'399001','f6':40},
        {'f13':0,'f12':'399002','f104':200,'f105':80,'f106':3},
        {'f13':0,'f12':'899050','f6':5,'f104':10,'f105':8,'f106':1},
    ]
    monkeypatch.setattr(provider.DFCF,'quotes',lambda ids:{'endpoint':'eastmoney','raw':{'data':{'diff':rows}}})
    trends=['2026-09-10 09:30,100','2026-09-10 15:00,200','2026-09-11 09:30,150','2026-09-11 15:00,300']
    monkeypatch.setattr(provider.DFCF,'trends',lambda secid,days:{'raw':{'data':{'trends':trends}}})
    result=provider.market_summary()
    assert (result['up'],result['down'],result['flat'])==(310,138,6)
    assert result['amount_yuan']==65
    assert result['amount_change_yuan']==150
    assert result['change_points']==30
    assert result['source']=='东方财富'


def test_constituents_normalizes_fields(monkeypatch):
    raw={'endpoint':'eastmoney','raw':{'data':{'total':1,'diff':[{'f12':'000001','f14':'平安银行','f2':10,
        'f3':1,'f6':2,'f8':3,'f9':4,'f20':5,'f21':6,'f23':0.7}]}}}
    monkeypatch.setattr(provider.DFCF,'constituents',lambda code,page=1,size=100:raw)
    frame=provider.constituents('BK001')
    assert frame.loc[0,'code']=='000001'
    assert frame.loc[0,'pe']==4
    assert frame.attrs['source']=='东方财富'


def test_fund_flow_sectors_combines_top_and_bottom_ten(monkeypatch):
    def fetch(kind,period,descending,size):
        sign=1 if descending else -1
        rows=[{'f12':f'BK{i:04d}','f14':f'板块{i}','f109':i/10,
               'f164':sign*(10-i)*1e8,'f6':1e9,'f124':1789142400}
              for i in range(10)]
        return {'endpoint':'eastmoney','raw':{'data':{'diff':rows}}}
    monkeypatch.setattr(provider.DFCF,'fund_flow_boards',fetch)
    frame=provider.fund_flow_sectors('industry',5)
    assert len(frame)==20
    assert list(frame['flow_direction'][:10].unique())==['in']
    assert list(frame['flow_direction'][10:].unique())==['out']
    assert frame.iloc[0]['net_flow']==1e9
    assert frame.iloc[10]['net_flow']==-1e9
    assert frame.attrs['source_url'].endswith('hy.html?stat=5')
