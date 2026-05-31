# 回测模块设计文档

**日期：** 2026-05-22
**目标：** 用过去1年历史数据逐日模拟选股策略，验证其有效性

## 1. 概述

### 1.1 目的

当前选股策略（均线多头 + 五因子打分）从未经过历史验证。本模块通过逐日回放历史数据，模拟每天选股 → 次日买入 → 止盈止损平仓的完整流程，输出策略的真实表现指标。

### 1.2 核心指标

- 胜率、平均收益、盈亏比
- 年化收益率、Sharpe Ratio、最大回撤
- 月度收益分布
- vs 沪深300 超额收益

## 2. 架构

```
backtest/
├── data_downloader.py    # 一次性下载历史数据到本地 SQLite
├── data_store.py         # 本地数据读写接口
├── engine.py             # 回测引擎（逐日模拟主循环）
├── portfolio.py          # 持仓管理 + 交易记录
├── report.py             # 统计计算 + 报告输出
└── run_backtest.py       # 入口脚本
```

独立于主应用，不依赖 Flask/MySQL/网络。纯本地计算。

## 3. 数据层

### 3.1 存储

SQLite 单文件：`backtest/data/market_data.db`

**daily_bars 表：**
| 字段 | 类型 | 说明 |
|------|------|------|
| stock_code | TEXT | 6位股票代码 |
| trade_date | TEXT | YYYY-MM-DD |
| open | REAL | 开盘价 |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| volume | REAL | 成交量（股） |

主键：(stock_code, trade_date)

**stock_info 表：**
| 字段 | 类型 | 说明 |
|------|------|------|
| stock_code | TEXT | 6位股票代码 |
| stock_name | TEXT | 股票名称 |
| board | TEXT | 主板/创业板 |

主键：stock_code

**index_daily 表（沪深300基准）：**
| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | TEXT | YYYY-MM-DD |
| close | REAL | 收盘价 |

主键：trade_date

### 3.2 下载策略

- 数据源：新浪财经日线接口（已验证可用）
- 范围：2025-04-01 至 2026-05-22（多留1个月给均线预热）
- 标的：沪深主板 + 创业板，约4900只
- 并发：12线程，预计15-20分钟
- 增量更新：已有数据的票只补最新日期

### 3.3 数据接口

```python
class DataStore:
    def get_daily(self, code: str, end_date: str, days: int = 120) -> pd.DataFrame
    def get_all_codes_on_date(self, trade_date: str) -> list[str]
    def get_trade_dates(self, start: str, end: str) -> list[str]
    def get_index_daily(self, start: str, end: str) -> pd.DataFrame
```

## 4. 回测引擎

### 4.1 主循环

```python
for T in trade_dates[预热期后:]:
    # 1. 构造当日 spot（用 daily_bars 的 T 日数据模拟）
    spot = build_spot_from_daily(T)

    # 2. 初筛
    candidates = prefilter(spot)  # 去ST、价格>0、成交额>=1亿、不涨停

    # 3. 对候选票拉截止T日的日线，算指标+硬过滤+打分
    scored = score_candidates(candidates, T)

    # 4. 取 top 10（行业分散不做，因为本地没行业数据）
    picks = scored[:10]

    # 5. T+1 开盘价买入（如果持仓未满）
    for pick in picks:
        if portfolio.position_count < MAX_POSITIONS:
            open_price_t1 = get_open(pick.code, T+1)
            portfolio.open(pick.code, open_price_t1, T+1)

    # 6. 检查持仓是否触发平仓
    for pos in portfolio.active_positions:
        close_price_T = get_close(pos.code, T)
        ret = close_price_T / pos.entry_price - 1
        if ret >= 0.15:       # 止盈
            portfolio.close(pos, close_price_T, T, "止盈")
        elif ret <= -0.05:    # 止损
            portfolio.close(pos, close_price_T, T, "止损")
        elif pos.hold_days >= 30:  # 超时
            portfolio.close(pos, close_price_T, T, "超时")
```

### 4.2 关键参数

| 参数 | 值 | 说明 |
|------|---|------|
| 回测区间 | 2025-06-01 ~ 2026-05-22 | 前2个月为预热期 |
| 每日选股数 | 10 | 和实盘一致 |
| 最大持仓数 | 10 | 资金约束 |
| 止盈 | +15% | |
| 止损 | -5% | |
| 最长持有 | 30个交易日 | |
| 资金分配 | 等权 | 每只票相同金额 |
| 手续费 | 不计 | 第一版简化 |
| 滑点 | 不计 | 第一版简化 |

### 4.3 模拟 spot 数据

回测时没有实时行情，用 daily_bars 的 T 日数据构造：
- current_price = close
- change_percent = (close - prev_close) / prev_close * 100
- turnover = close * volume（近似成交额）
- float_market_cap：不可用，跳过市值过滤（或用固定阈值近似）

注意：回测中无法获取流通市值，硬过滤中的"流通市值>=50亿"条件在回测中跳过。这会让回测结果略偏乐观（实盘会多踢掉一些小盘股）。

## 5. 持仓管理

```python
@dataclass
class Position:
    code: str
    entry_price: float
    entry_date: str
    hold_days: int = 0

@dataclass
class Trade:
    code: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    exit_reason: str  # 止盈/止损/超时
```

## 6. 报告输出

### 6.1 终端输出

```
============================================================
  回测报告  2025-06-01 ~ 2026-05-22
============================================================

  总交易次数:     xxx
  胜率:           xx.x%
  平均收益:       x.xx%
  平均盈利:       +x.xx%  (盈利交易的平均)
  平均亏损:       -x.xx%  (亏损交易的平均)
  盈亏比:         x.xx
  最大单笔盈利:   +xx.x%
  最大单笔亏损:   -xx.x%

  年化收益率:     xx.x%
  Sharpe Ratio:   x.xx
  最大回撤:       -xx.x%
  Calmar Ratio:   x.xx

  vs 沪深300:     +/-xx.x% (超额收益)

  月度收益:
  2025-06: +x.x%  |  2025-07: -x.x%  |  ...

  平仓原因分布:
  止盈: xx次 (xx%)  |  止损: xx次 (xx%)  |  超时: xx次 (xx%)
============================================================
```

### 6.2 CSV 导出

所有交易记录导出到 `backtest/results/trades.csv`，方便进一步分析。

## 7. 选股逻辑复用

回测引擎内部独立实现选股算法（从 stock_selector.py 提取核心逻辑），包括：
- `compute_indicators()` — 技术指标计算
- `passes_hard_filter()` — 硬过滤（回测中跳过流通市值条件）
- `score_dataframe()` — 五因子打分
- `prefilter()` — 初筛（去ST、去涨停、成交额过滤）

不 import 主应用代码，保持回测模块完全独立。

## 8. 使用方式

```bash
# 第一步：下载数据（只需跑一次，约15-20分钟）
python backtest/data_downloader.py

# 第二步：跑回测（约2-5分钟）
python backtest/run_backtest.py

# 可选：调参数再跑
python backtest/run_backtest.py --take-profit 0.10 --stop-loss -0.03 --max-hold 20
```

## 9. 后续扩展

- 加手续费（万1.5佣金 + 千1印花税）
- 参数扫描（遍历不同止盈止损组合，找最优参数）
- 加"今日涨幅>7%不买入"等改进规则，对比改进前后
- 可视化：净值曲线、回撤曲线（matplotlib）
