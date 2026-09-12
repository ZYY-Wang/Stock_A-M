# 两版数据接口

- `src/stock_monitor/xinlang.py`：新浪独立备用版；正式刷新不自动调用。旧 `sina.py` 仅留兼容入口。
- `src/stock_monitor/DFCF.py`：东方财富原始接口层；`dfcf_provider.py` 负责转换页面字段。正式刷新使用东方财富，失败时保留旧缓存，不调用新浪兜底。

## 东方财富独立测试

在项目目录运行：

```powershell
python -m stock_monitor.DFCF quote --secid 1.000001
python -m stock_monitor.DFCF boards --kind industry --period 3 --size 5
python -m stock_monitor.DFCF boards --kind concept --period 20 --size 5
python -m stock_monitor.DFCF constituents --code BK0420 --size 5
python -m stock_monitor.DFCF history --secid 90.BK0420 --start 20260601 --end 20260911 --adjust 0
python -m stock_monitor.DFCF activity --size 5
```

列表仅返回指定页，不能据此声称获取全市场。保留原始字段、请求参数和抓取时间；抓取时间不是行情日期。报价小数位、成交量单位、复权口径、日期覆盖、分页完整性需逐项验证后再统一。接口失败保留错误，不能当作空榜或零行情。

已有抽测：个股日线、异动接口曾成功；指数、板块列表曾返回502，板块日线曾发生代理连接错误。这是历史测试结果，不是稳定性承诺。

板块周期字段已通过同一板块日线反算核验：今日 `f3`、3日 `f127`、5日 `f109`、20日 `f110`。大盘异动使用东方财富“当日异动板块监控”接口，展示板块、涨跌幅、主力净流入、异动总次数、最频繁个股及异动类型，不把次数解释为投资强弱排名。
