"""东方财富实验接口：只读、返回原始字段，不接入生产刷新或数据库。

Example: python -m stock_monitor.DFCF boards --kind industry --size 5
No request is made on import. No automatic fallback to another provider.
"""
import argparse
import json
import re
from datetime import datetime

import requests

SOURCE = '东方财富（实验）'
HOST = 'https://push2.eastmoney.com'
FALLBACK_HOST = 'https://push2delay.eastmoney.com'
HISTORY_HOST = 'https://push2his.eastmoney.com'
ACTIVITY_HOST = 'https://push2ex.eastmoney.com'

# 东方财富实验接口固定直连。VPN退出后，Windows/Python进程中可能仍残留
# HTTP(S)_PROXY 指向已经关闭的本地代理端口，requests默认会继续使用它。
SESSION = requests.Session()
SESSION.trust_env = False
# 历史分时域名在部分网络下只经系统代理可达。始终先直连，失败后才
# 尝试此会话；VPN退出且代理端口失效时不会影响直连成功的路径。
PROXY_SESSION = requests.Session()


def _request_once(host, path, params, session=SESSION):
    response = session.get(host + path, params=params,
                           headers={'Referer': 'https://quote.eastmoney.com/',
                                    'User-Agent': 'Mozilla/5.0'}, timeout=(5, 15))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get('rc') != 0 or payload.get('data') is None:
        raise ValueError('东方财富返回业务错误或空数据；不转换为零或成功')
    return {'source': SOURCE, 'fetched_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'endpoint': host + path, 'params': params, 'raw': payload}


def _request(host, path, params):
    """主实时节点失败时使用东方财富备用节点；历史和异动接口不跨节点。"""
    try:
        return _request_once(host, path, params)
    except requests.RequestException as primary_error:
        if host != HOST:
            raise
        result = _request_once(FALLBACK_HOST, path, params)
        result['fallback_from'] = host
        result['primary_error'] = f'{type(primary_error).__name__}: {primary_error}'[:500]
        return result


def _history_request(path, params):
    try:
        return _request_once(HISTORY_HOST, path, params)
    except requests.RequestException as direct_error:
        result = _request_once(HISTORY_HOST, path, params, PROXY_SESSION)
        result['fallback_from'] = 'direct'
        result['direct_error'] = f'{type(direct_error).__name__}: {direct_error}'[:500]
        return result


def _secid(value):
    if not re.fullmatch(r'(?:0|1)\.[0-9]{6}|90\.BK[0-9]{4}', value):
        raise ValueError('secid格式示例：1.000001、0.000988、90.BK0420')
    return value


def _page(page, size):
    if not isinstance(page, int) or page < 1 or not isinstance(size, int) or not 1 <= size <= 100:
        raise ValueError('page须为正整数，size须在1至100之间')


def quote(secid='1.000001'):
    """单个指数/股票/板块报价；保留f字段，单位尚未统一。"""
    return _request(HOST, '/api/qt/stock/get', {
        'secid': _secid(secid), 'fltt': 2, 'invt': 2,
        'fields': 'f10,f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f86,f116,f117,f162,f167,f168,f169,f170,f171'})


def quotes(secids):
    """批量指数/股票报价；用于减少连接次数，避免高频并发触发断连。"""
    values = list(secids)
    if not values or len(values) > 50:
        raise ValueError('secids数量须在1至50之间')
    return _request(HOST, '/api/qt/ulist.np/get', {
        'secids': ','.join(_secid(value) for value in values), 'fltt': 2, 'invt': 2,
        'fields': 'f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f104,f105,f106,f124'})


def _list(fs, page, size):
    _page(page, size)
    return _request(HOST, '/api/qt/clist/get', {
        'pn': page, 'pz': size, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f3',
        'fs': fs, 'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f104,f105,f106,f124,f128,f136,f140,f141'})


def stocks(page=1, size=100):
    """沪深京A股单页；不是完整全市场结果。"""
    return _list('m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048', page, size)


def boards(kind='industry', page=1, size=100, period=1):
    """板块排行；涨幅字段：今日f3、3日f127、5日f109、20日f110。"""
    if kind not in ('industry', 'concept'):
        raise ValueError('kind须为industry或concept')
    period_fields = {1: 'f3', 3: 'f127', 5: 'f109', 20: 'f110'}
    if period not in period_fields:
        raise ValueError('period须为1、3、5或20')
    _page(page, size)
    return _request(HOST, '/api/qt/clist/get', {
        'pn': page, 'pz': size, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
        'fid': period_fields[period],
        'fs': 'm:90 t:' + ('2' if kind == 'industry' else '3'),
        'fields': 'f2,f3,f5,f6,f12,f13,f14,f20,f104,f105,f106,f109,f110,f124,f127,f128,f136,f140,f141'})


def fund_flow_boards(kind='industry', period=1, descending=True, size=10):
    """东方财富板块资金流排行，字段与板块资金流页面一致。"""
    if kind not in ('industry', 'concept'):
        raise ValueError('kind须为industry或concept')
    flow_fields = {1: 'f62', 5: 'f164', 10: 'f174'}
    if period not in flow_fields:
        raise ValueError('period须为1、5或10')
    _page(1, size)
    fields = {
        1: 'f12,f14,f2,f3,f6,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124,f1,f13',
        5: 'f12,f14,f2,f6,f109,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f257,f258,f124,f1,f13',
        10: 'f12,f14,f2,f6,f160,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f260,f261,f124,f1,f13',
    }
    return _request(HOST, '/api/qt/clist/get', {
        'pn': 1, 'pz': size, 'po': 1 if descending else 0, 'np': 1,
        'fltt': 2, 'invt': 2, 'fid': flow_fields[period],
        'fs': 'm:90 s:4' if kind == 'industry' else 'm:90 t:3',
        'fields': fields[period], 'ut': '8dec03ba335b81bf4ebdf7b29ec27d15'})


def constituents(code, page=1, size=100):
    _secid('90.' + code)
    return _list('b:' + code, page, size)


def history(secid, start, end, adjust=1):
    """日线原始返回；股票adjust=1前复权，板块通常用0。"""
    for value in (start, end):
        if not re.fullmatch(r'\d{8}', value):
            raise ValueError('日期必须为YYYYMMDD')
        datetime.strptime(value, '%Y%m%d')
    if start > end or adjust not in (0, 1, 2):
        raise ValueError('日期范围或复权参数无效')
    return _history_request('/api/qt/stock/kline/get', {
        'secid': _secid(secid), 'klt': 101, 'fqt': adjust, 'beg': start, 'end': end,
        'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'})


def trends(secid, days=2):
    """分时成交额；用于复刻大盘星图“比昨日放量/缩量”的同时间口径。"""
    if not isinstance(days, int) or not 1 <= days <= 5:
        raise ValueError('days须为1至5之间的整数')
    return _history_request('/api/qt/stock/trends2/get', {
        'secid': _secid(secid), 'ndays': days, 'iscr': 0, 'iscca': 0,
        'fields1': 'f1', 'fields2': 'f51,f57',
        'ut': '7eea3edcaed734bea9cbfc24409ed989'})


def activity(page=1, size=100):
    """板块异动累计统计，不是板块事件时间线；dt为源端整批时间。"""
    _page(page, size)
    return _request(ACTIVITY_HOST, '/getAllBKChanges', {
        'ut': '7eea3edcaed734bea9cbfc24409ed989', 'dpt': 'wzchanges',
        'pageindex': page-1, 'pagesize': size})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['quote','stocks','boards','constituents','history','activity'])
    parser.add_argument('--secid', default='1.000001')
    parser.add_argument('--kind', choices=['industry','concept'], default='industry')
    parser.add_argument('--period', type=int, choices=[1,3,5,20], default=1)
    parser.add_argument('--code', default='BK0420')
    parser.add_argument('--page', type=int, default=1)
    parser.add_argument('--size', type=int, default=5)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--adjust', type=int, choices=[0,1,2], default=1)
    args = parser.parse_args()
    if args.action == 'history' and (not args.start or not args.end):
        parser.error('history需要--start和--end')
    calls = {'quote': lambda: quote(args.secid), 'stocks': lambda: stocks(args.page,args.size),
             'boards': lambda: boards(args.kind,args.page,args.size,args.period),
             'constituents': lambda: constituents(args.code,args.page,args.size),
             'history': lambda: history(args.secid,args.start,args.end,args.adjust),
             'activity': lambda: activity(args.page,args.size)}
    try:
        print(json.dumps(calls[args.action](), ensure_ascii=True, indent=2))
    except (requests.RequestException, ValueError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
