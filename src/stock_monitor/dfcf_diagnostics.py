"""东方财富联网诊断页；与正式行情数据库写入完全隔离。"""
from __future__ import annotations

import json
import time
from datetime import datetime

import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import DFCF


INDEXES = {
    "1.000001": "上证指数",
    "0.399001": "深证成指",
    "0.399006": "创业板指",
    "1.000300": "沪深300",
}


class DiagnosticRequest(BaseModel):
    network_label: str = "未标注"


def _number(value):
    return value if isinstance(value, (int, float)) else None


def _source_time(value):
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
    except (ValueError, OSError, OverflowError):
        return None


def _error_result(exc: Exception, elapsed_ms: int) -> dict:
    if isinstance(exc, requests.exceptions.ProxyError):
        category = "代理或VPN连接失败"
    elif isinstance(exc, requests.exceptions.Timeout):
        category = "连接超时"
    elif isinstance(exc, requests.exceptions.ConnectionError):
        category = "网络连接失败"
    elif isinstance(exc, requests.exceptions.HTTPError):
        category = "HTTP响应错误"
    elif isinstance(exc, (ValueError, json.JSONDecodeError)):
        category = "接口数据异常"
    else:
        category = "未知错误"
    return {"ok": False, "elapsed_ms": elapsed_ms, "category": category,
            "error_type": type(exc).__name__, "error": str(exc)[:500]}


def _probe_indices() -> list[dict]:
    started = time.perf_counter()
    try:
        result = DFCF.quotes(INDEXES)
        rows = result["raw"]["data"].get("diff") or []
        by_secid = {f'{row.get("f13")}.{row.get("f12")}': row for row in rows}
        elapsed = round((time.perf_counter() - started) * 1000)
        output = []
        for secid, name in INDEXES.items():
            data = by_secid.get(secid)
            if not data:
                output.append({"secid": secid, "name": name, "ok": False,
                               "elapsed_ms": elapsed, "category": "接口数据异常",
                               "error_type": "MissingIndex", "error": "批量返回中缺少该指数"})
                continue
            output.append({
                "ok": True, "elapsed_ms": elapsed, "secid": secid,
                "code": str(data.get("f12") or secid.split(".")[-1]), "name": name,
                "price": _number(data.get("f2")), "change": _number(data.get("f4")),
                "pct_change": _number(data.get("f3")), "open": _number(data.get("f17")),
                "high": _number(data.get("f15")), "low": _number(data.get("f16")),
                "previous_close": _number(data.get("f18")), "volume": _number(data.get("f5")),
                "amount": _number(data.get("f6")), "source_time": _source_time(data.get("f124")),
                "endpoint": result["endpoint"],
            })
        return output
    except Exception as exc:
        error = _error_result(exc, round((time.perf_counter() - started) * 1000))
        return [{"secid": secid, "name": name, **error} for secid, name in INDEXES.items()]


def _probe_stocks() -> dict:
    started = time.perf_counter()
    try:
        result = DFCF.stocks(page=1, size=100)
        data = result["raw"]["data"]
        rows = data.get("diff") or []
        sample = [{"code": str(x.get("f12") or ""), "name": x.get("f14"),
                   "price": _number(x.get("f2")), "pct_change": _number(x.get("f3")),
                   "volume": _number(x.get("f5")), "amount": _number(x.get("f6"))}
                  for x in rows[:10]]
        return {"ok": True, "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "total": data.get("total"), "received": len(rows), "sample": sample,
                "endpoint": result["endpoint"],
                "note": "只读取按涨幅排序的首100只，用于验证行情接口，不写入正式行情库。"}
    except Exception as exc:
        return _error_result(exc, round((time.perf_counter() - started) * 1000))


def run_diagnostics(network_label: str) -> dict:
    label = network_label.strip()[:30] or "未标注"
    started_at = datetime.now().astimezone()
    # 两次串行请求：一次批量指数、一次A股列表，避免并发连接触发源端断连。
    index_results = _probe_indices()
    stock_result = _probe_stocks()

    index_ok = sum(bool(x.get("ok")) for x in index_results)
    stocks_ok = bool(stock_result and stock_result.get("ok"))
    used_backup = any("push2delay.eastmoney.com" in str(x.get("endpoint")) for x in index_results)
    used_backup = used_backup or "push2delay.eastmoney.com" in str((stock_result or {}).get("endpoint"))
    if index_ok == len(INDEXES) and stocks_ok:
        conclusion = "东方财富指数与A股行情接口均可用。若VPN关闭时成功而开启时失败，基本可判断是VPN或代理链路影响。"
        status = "success"
    elif index_ok or stocks_ok:
        conclusion = "接口部分可用，不能简单归因为整台电脑断网；请查看失败项的错误类别。"
        status = "partial"
    else:
        conclusion = "东方财富接口均未连通。请根据错误类别判断是超时、代理/VPN、HTTP错误还是接口数据异常。"
        status = "failed"
    if used_backup:
        conclusion += " 本次由东方财富备用行情节点返回；收盘值可用，盘中延迟程度需在交易时段核验。"
    return {
        "network_label": label, "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status, "conclusion": conclusion, "source": DFCF.SOURCE,
        "used_backup": used_backup,
        "indices": index_results, "stocks": stock_result,
    }


def register_dfcf_diagnostics(app: FastAPI, connect, static_dir) -> None:
    def initialize(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS dfcf_diagnostics (
          id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
          network_label TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
        )""")
        conn.commit()

    @app.get("/dfcf-test")
    def diagnostics_page():
        return FileResponse(static_dir / "dfcf-test.html")

    @app.get("/dfcf-test.css")
    def diagnostics_css():
        return FileResponse(static_dir / "dfcf-test.css", media_type="text/css")

    @app.get("/dfcf-test.js")
    def diagnostics_js():
        return FileResponse(static_dir / "dfcf-test.js", media_type="text/javascript")

    @app.post("/api/dfcf-diagnostics/run")
    def run_test(request: DiagnosticRequest):
        result = run_diagnostics(request.network_label)
        with connect() as conn:
            initialize(conn)
            conn.execute("INSERT INTO dfcf_diagnostics(created_at,network_label,status,payload) VALUES(?,?,?,?)",
                         (result["finished_at"], result["network_label"], result["status"],
                          json.dumps(result, ensure_ascii=False)))
            conn.execute("DELETE FROM dfcf_diagnostics WHERE id NOT IN (SELECT id FROM dfcf_diagnostics ORDER BY id DESC LIMIT 50)")
            conn.commit()
        return result

    @app.get("/api/dfcf-diagnostics/history")
    def test_history():
        with connect() as conn:
            initialize(conn)
            rows = conn.execute("SELECT id,payload FROM dfcf_diagnostics ORDER BY id DESC LIMIT 20").fetchall()
        return {"items": [{**json.loads(row["payload"]), "id": row["id"]} for row in rows]}
