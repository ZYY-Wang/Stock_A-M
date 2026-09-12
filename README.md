# A 股每日监测

每天抓取沪深京 A 股与主要指数行情，统计市场涨跌家数、成交额、涨跌停近似数量、涨跌幅中位数，以及连续上涨/下跌个股。正式刷新使用东方财富公开行情接口；失败时保留上一份东方财富缓存，不混入新浪口径。`xinlang.py` 仅作为独立备用实现保留。

## 安装与运行

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m stock_monitor.cli
```

## 可视化仪表盘

```powershell
python -m stock_monitor.web --root "C:\Users\WZYY\Documents\ChatGPT\stock monitor"
```

浏览器打开 `http://127.0.0.1:8765`。点击“立即刷新”会保存全市场和行业板块快照；点击热力图或排行榜可查看板块成分股，并可把板块或个股加入三个月关注池。首次运行只有今日数据，3日、5日、20日轮动指标会随快照逐步形成。

输出位于 `reports/YYYY-MM-DD/`，历史数据保存在 `data/market.db`。首次运行只建立连续涨跌基线；从第二个交易日开始形成连续天数。重复运行同一天会覆盖当天记录，不会重复计数。

建议在交易日 15:30 后运行。非交易日请不要执行，否则实时接口可能返回最近交易日数据，却被写入当天日期。

## 配置

编辑 `config.toml` 可以调整主要指数、连续天数阈值、榜单数量，以及是否排除 ST 股票。

## Windows 定时任务

先手动运行成功，再在“任务计划程序”中新建任务：周一至周五 15:40 执行：

```text
程序：C:\完整路径\stock monitor\.venv\Scripts\python.exe
参数：-m stock_monitor.cli --root "C:\完整路径\stock monitor"
起始于：C:\完整路径\stock monitor
```

节假日仍可能触发，因此推荐后续接入交易日历校验。数据仅供研究和监测，不构成投资建议。

界面展示：
<img width="1874" height="770" alt="image" src="https://github.com/user-attachments/assets/6f80d8a2-1454-43e2-84b1-8a6617e8202e" />
<img width="1874" height="770" alt="image" src="https://github.com/user-attachments/assets/23b66e5c-a162-4da1-84a0-9edcdc4b9c1d" />



