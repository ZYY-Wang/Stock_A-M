import pandas as pd

from stock_monitor.core import calculate_streaks, market_summary, normalize_stocks


def test_streak_continues_and_reverses():
    current = pd.DataFrame({
        "code": ["000001", "000002", "000003"], "name": ["甲", "乙", "丙"],
        "close": [11.0, 9.0, 10.0], "prev_close": [10.0, 10.0, 10.0],
        "pct_change": [10.0, -10.0, 0.0], "trade_date": ["2026-09-08"] * 3,
    })
    previous = pd.DataFrame({
        "code": ["000001", "000002", "000003"], "close": [10.0] * 3,
        "streak": [2, 3, -2],
    })
    result = calculate_streaks(current, previous).set_index("code")
    assert result.loc["000001", "streak"] == 3
    assert result.loc["000002", "streak"] == -1
    assert result.loc["000003", "streak"] == 0


def test_normalize_and_summary():
    raw = pd.DataFrame({
        "代码": [1, 2], "名称": ["甲", "乙"], "最新价": [10, 9],
        "涨跌幅": [1.2, -2.0], "成交额": [100, 200],
    })
    frame = normalize_stocks(raw, "2026-09-08")
    assert frame["code"].tolist() == ["000001", "000002"]
    assert market_summary(frame)["amount"] == 300

