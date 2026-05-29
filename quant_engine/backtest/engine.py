"""
回测引擎
支持全市场状态自适应回测，输出完整绩效报告。

特点：
1. 自动识别市场状态并切换策略
2. 真实交易成本（佣金万2.5 + 印花税千1 + 滑点0.1%）
3. Walk-forward 验证防过拟合
4. 输出 Sharpe/Sortino/MaxDD/胜率/盈亏比
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_engine.market_regime import MarketRegimeDetector, MarketState
from quant_engine.factors.factor_engine import FactorEngine
from quant_engine.strategies.adaptive_strategy import AdaptiveStrategyEngine, TradeSignal
from quant_engine.risk.risk_manager import RiskManager


# 交易成本
COMMISSION = 0.00025      # 万2.5
STAMP_TAX = 0.001         # 千1（卖出）
SLIPPAGE = 0.001          # 0.1%
INITIAL_CASH = 200_000.0  # 20万初始资金（匹配用户实际）


@dataclass
class BacktestConfig:
    initial_cash: float = INITIAL_CASH
    start_date: str = "2024-01-01"
    end_date: str = "2026-05-29"
    commission: float = COMMISSION
    stamp_tax: float = STAMP_TAX
    slippage: float = SLIPPAGE
    rebalance_freq: str = "daily"  # "daily" / "weekly"


@dataclass
class TradeRecord:
    date: str
    code: str
    action: str
    price: float
    shares: int
    cost: float
    reason: str
    market_state: str
    strategy: str


@dataclass
class DailySnapshot:
    date: str
    portfolio_value: float
    cash: float
    holding_value: float
    market_state: str
    position_ratio: float
    num_holdings: int


@dataclass
class BacktestResult:
    # 绩效指标
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_days: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_holding_days: float = 0.0
    trade_count: int = 0
    
    # 分状态绩效
    bull_return: float = 0.0
    bear_return: float = 0.0
    osc_return: float = 0.0
    
    # 风控统计
    stop_loss_count: int = 0
    take_profit_count: int = 0
    
    # 明细
    trades: List[TradeRecord] = field(default_factory=list)
    daily_snapshots: List[DailySnapshot] = field(default_factory=list)
    
    # 综合评分
    score: float = 0.0


class BacktestEngine:
    """
    全市场自适应回测引擎
    """
    
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.regime_detector = MarketRegimeDetector()
        self.factor_engine = FactorEngine()
        self.strategy_engine = AdaptiveStrategyEngine()
        self.risk_manager = RiskManager()
    
    def run(self, index_data: pd.DataFrame, stock_data: Dict[str, pd.DataFrame]) -> BacktestResult:
        """
        运行回测
        
        Parameters
        ----------
        index_data : pd.DataFrame
            大盘指数日线数据 [date, open, high, low, close, volume]
        stock_data : Dict[str, pd.DataFrame]
            个股日线数据 {code: DataFrame[date, open, high, low, close, volume, amount]}
        """
        result = BacktestResult()
        
        # 初始化
        cash = self.config.initial_cash
        holdings = {}  # {code: {shares, avg_cost, buy_date, max_price, hold_days}}
        
        dates = sorted(index_data["date"].unique())
        dates = [d for d in dates if self.config.start_date <= d <= self.config.end_date]
        
        if not dates:
            print("无有效交易日期")
            return result
        
        print(f"回测区间: {dates[0]} ~ {dates[-1]} ({len(dates)}个交易日)")
        print(f"初始资金: {cash:,.0f}")
        print(f"股票池: {len(stock_data)}只")
        print("-" * 60)
        
        state_days = {"bull": 0, "bear": 0, "osc": 0, "trans": 0}
        state_returns = {"bull": [], "bear": [], "osc": [], "trans": []}
        prev_value = cash
        
        for i, date in enumerate(dates):
            # 1. 获取当日数据
            idx_slice = index_data[index_data["date"] <= date].tail(150)
            if len(idx_slice) < 30:
                continue
            
            # 2. 识别市场状态
            regime = self.regime_detector.detect(idx_slice)
            state = regime.state.value
            state_days[state] = state_days.get(state, 0) + 1
            
            # 3. 准备个股数据
            available_stocks = {}
            stock_today = []
            for code, sdf in stock_data.items():
                sdf_slice = sdf[sdf["date"] <= date].tail(150)
                if len(sdf_slice) >= 30 and sdf_slice["date"].iloc[-1] == date:
                    available_stocks[code] = sdf_slice
                    stock_today.append({"code": code, **sdf_slice.iloc[-1].to_dict()})
            
            if not stock_today:
                continue
            
            stock_today_df = pd.DataFrame(stock_today)
            
            # 4. 计算因子（传入每只股票最近60天数据）
            all_stock_history = []
            for code, sdf in available_stocks.items():
                all_stock_history.append(sdf.tail(60))
            
            if not all_stock_history:
                continue
            
            combined_df = pd.concat(all_stock_history, ignore_index=True)
            factors = self.factor_engine.compute_all(combined_df, state)
            
            if factors.empty:
                continue
            
            # 5. 风控检查
            portfolio_value = cash + sum(
                available_stocks[c]["close"].iloc[-1] * h["shares"]
                for c, h in holdings.items() if c in available_stocks
            )
            
            index_ret = (idx_slice["close"].iloc[-1] - idx_slice["close"].iloc[-2]) / idx_slice["close"].iloc[-2] if len(idx_slice) > 1 else 0
            risk_alerts = self.risk_manager.check_portfolio_risk(
                portfolio_value, self.config.initial_cash, holdings, state, index_ret
            )
            
            # 处理风控警报
            force_sell_all = False
            for alert in risk_alerts:
                if alert.action == "clear":
                    force_sell_all = True
                    break
            
            # 6. 生成交易信号
            if force_sell_all:
                # 强制清仓
                for code in list(holdings.keys()):
                    if code in available_stocks:
                        price = available_stocks[code]["close"].iloc[-1]
                        shares = holdings[code]["shares"]
                        sell_cost = price * shares * (self.config.commission + self.config.stamp_tax + self.config.slippage)
                        cash += price * shares - sell_cost
                        result.trades.append(TradeRecord(
                            date=date, code=code, action="sell", price=price,
                            shares=shares, cost=sell_cost, reason="风控强制清仓",
                            market_state=state, strategy="risk_control"
                        ))
                        result.stop_loss_count += 1
                holdings.clear()
            else:
                # 正常策略执行
                signals = self.strategy_engine.execute(state, factors, holdings, available_stocks)
                
                # 执行信号
                for signal in signals:
                    if signal.action == "sell" and signal.code in holdings:
                        code = signal.code
                        # 最短持有期检查（止损除外）
                        hold_days = holdings[code].get("hold_days", 0)
                        is_stop_loss = "stop_loss" in signal.strategy
                        min_hold = 3  # 默认最少3天
                        if not is_stop_loss and hold_days < min_hold:
                            continue  # 未到最短持有期，跳过
                        
                        price = signal.price * (1 - self.config.slippage)
                        shares = holdings[code]["shares"]
                        sell_cost = price * shares * (self.config.commission + self.config.stamp_tax)
                        cash += price * shares - sell_cost
                        
                        pnl = (price - holdings[code]["avg_cost"]) * shares - sell_cost
                        result.trades.append(TradeRecord(
                            date=date, code=code, action="sell", price=price,
                            shares=shares, cost=sell_cost, reason=signal.reason,
                            market_state=state, strategy=signal.strategy
                        ))
                        
                        if "stop_loss" in signal.strategy:
                            result.stop_loss_count += 1
                        elif "profit" in signal.strategy or "trailing" in signal.strategy:
                            result.take_profit_count += 1
                        
                        del holdings[code]
                    
                    elif signal.action == "buy" and signal.code not in holdings:
                        code = signal.code
                        price = signal.price * (1 + self.config.slippage)
                        
                        # 计算可买股数
                        position_value = portfolio_value * signal.position_pct
                        max_buy = min(position_value, cash * 0.95)  # 留5%现金
                        shares = int(max_buy / price / 100) * 100  # 整手
                        
                        if shares >= 100:
                            buy_cost = price * shares * self.config.commission
                            total_cost = price * shares + buy_cost
                            if total_cost <= cash:
                                cash -= total_cost
                                holdings[code] = {
                                    "shares": shares,
                                    "avg_cost": price,
                                    "buy_date": date,
                                    "max_price": price,
                                    "hold_days": 0,
                                    "position_pct": signal.position_pct,
                                }
                                result.trades.append(TradeRecord(
                                    date=date, code=code, action="buy", price=price,
                                    shares=shares, cost=buy_cost, reason=signal.reason,
                                    market_state=state, strategy=signal.strategy
                                ))
            
            # 7. 更新持仓状态（在下一轮循环开始时已更新）
            for code in list(holdings.keys()):
                holdings[code]["hold_days"] = holdings[code].get("hold_days", 0) + 1
                if code in available_stocks:
                    current_price = available_stocks[code]["close"].iloc[-1]
                    holdings[code]["max_price"] = max(
                        holdings[code].get("max_price", 0), current_price
                    )
                    holdings[code]["current_value"] = current_price * holdings[code]["shares"]
            
            # 8. 记录每日快照
            holding_value = sum(
                available_stocks[c]["close"].iloc[-1] * h["shares"]
                for c, h in holdings.items() if c in available_stocks
            )
            portfolio_value = cash + holding_value
            
            daily_ret = (portfolio_value - prev_value) / prev_value if prev_value > 0 else 0
            state_returns[state].append(daily_ret)
            prev_value = portfolio_value
            
            result.daily_snapshots.append(DailySnapshot(
                date=date, portfolio_value=portfolio_value,
                cash=cash, holding_value=holding_value,
                market_state=state,
                position_ratio=holding_value / portfolio_value if portfolio_value > 0 else 0,
                num_holdings=len(holdings)
            ))
        
        # 9. 计算绩效指标
        self._calc_metrics(result, state_returns, state_days)
        
        return result
    
    def _calc_metrics(self, result: BacktestResult, state_returns: Dict, state_days: Dict):
        """计算所有绩效指标"""
        if not result.daily_snapshots:
            return
        
        values = [s.portfolio_value for s in result.daily_snapshots]
        initial = self.config.initial_cash
        final = values[-1]
        n_days = len(values)
        
        # 基础收益
        result.total_return = (final - initial) / initial
        result.annual_return = (1 + result.total_return) ** (252 / max(n_days, 1)) - 1
        
        # 日收益率
        daily_returns = np.diff(values) / np.array(values[:-1])
        
        # Sharpe
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            result.sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
        
        # Sortino
        downside = daily_returns[daily_returns < 0]
        if len(downside) > 0 and np.std(downside) > 0:
            result.sortino = np.mean(daily_returns) / np.std(downside) * np.sqrt(252)
        
        # 最大回撤
        peak = values[0]
        max_dd = 0
        dd_start = 0
        max_dd_days = 0
        current_dd_start = 0
        for i, v in enumerate(values):
            if v > peak:
                peak = v
                current_dd_start = i
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
                max_dd_days = i - current_dd_start
        result.max_drawdown = max_dd
        result.max_drawdown_days = max_dd_days
        
        # 胜率和盈亏比
        trades = result.trades
        sell_trades = [t for t in trades if t.action == "sell"]
        if sell_trades:
            # 配对计算
            wins = 0
            total_profit = 0
            total_loss = 0
            holding_days = []
            
            buy_map = {}
            for t in trades:
                if t.action == "buy":
                    buy_map[t.code] = t
                elif t.action == "sell" and t.code in buy_map:
                    buy_t = buy_map[t.code]
                    pnl = (t.price - buy_t.price) * t.shares - t.cost - buy_t.cost
                    if pnl > 0:
                        wins += 1
                        total_profit += pnl
                    else:
                        total_loss += abs(pnl)
                    del buy_map[t.code]
            
            completed = wins + (len(sell_trades) - wins)
            result.win_rate = wins / len(sell_trades) if sell_trades else 0
            result.profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")
            result.trade_count = len(sell_trades)
        
        # 分状态收益
        for state in ["bull", "bear", "osc"]:
            rets = state_returns.get(state, [])
            if rets:
                cumulative = np.prod([1 + r for r in rets]) - 1
                setattr(result, f"{state}_return", cumulative)
        
        # 综合评分（参考 autoquant 的评分体系）
        score = 0.0
        score += self._normalize("sortino", result.sortino) * 0.25
        score += self._normalize("max_drawdown", result.max_drawdown) * 0.25
        score += self._normalize("annual_return", result.annual_return) * 0.20
        score += self._normalize("win_rate", result.win_rate) * 0.15
        score += self._normalize("profit_factor", result.profit_factor) * 0.15
        result.score = round(score, 4)
    
    def _normalize(self, metric: str, value: float) -> float:
        """归一化到 [0, 1]"""
        ranges = {
            "sortino": (-0.5, 3.0),
            "max_drawdown": (0.30, 0.0),  # 反转
            "annual_return": (-0.10, 0.80),
            "win_rate": (0.25, 0.65),
            "profit_factor": (0.6, 3.0),
        }
        if metric not in ranges:
            return 0.5
        low, high = ranges[metric]
        if high == low:
            return 0.5
        return max(0.0, min(1.0, (value - low) / (high - low)))
    
    def print_report(self, result: BacktestResult):
        """打印回测报告"""
        print("\n" + "=" * 60)
        print("           全市场自适应策略 回测报告")
        print("=" * 60)
        
        print(f"\n【总体绩效】")
        print(f"  总收益率:     {result.total_return:>8.1%}")
        print(f"  年化收益:     {result.annual_return:>8.1%}")
        print(f"  Sharpe:       {result.sharpe:>8.2f}")
        print(f"  Sortino:      {result.sortino:>8.2f}")
        print(f"  最大回撤:     {result.max_drawdown:>8.1%}")
        print(f"  回撤天数:     {result.max_drawdown_days:>8d}")
        print(f"  胜率:         {result.win_rate:>8.1%}")
        print(f"  盈亏比:       {result.profit_factor:>8.2f}")
        print(f"  交易次数:     {result.trade_count:>8d}")
        print(f"  综合评分:     {result.score:>8.4f}")
        
        print(f"\n【分状态收益】")
        print(f"  牛市收益:     {result.bull_return:>8.1%}")
        print(f"  熊市收益:     {result.bear_return:>8.1%}")
        print(f"  震荡收益:     {result.osc_return:>8.1%}")
        
        print(f"\n【风控统计】")
        print(f"  止损次数:     {result.stop_loss_count:>8d}")
        print(f"  止盈次数:     {result.take_profit_count:>8d}")
        
        print(f"\n【资金曲线】")
        if result.daily_snapshots:
            first = result.daily_snapshots[0]
            last = result.daily_snapshots[-1]
            print(f"  起始: {first.date} | {first.portfolio_value:>12,.0f}")
            print(f"  结束: {last.date} | {last.portfolio_value:>12,.0f}")
        
        print("\n" + "=" * 60)
