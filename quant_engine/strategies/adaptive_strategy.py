"""
自适应多策略引擎
根据市场状态自动切换策略：
- 牛市：趋势追踪 + 突破买入 + 移动止盈
- 熊市：超跌反弹 + 严格止损 + 轻仓防守
- 震荡：高抛低吸 + 网格交易 + 区间突破
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


@dataclass
class TradeSignal:
    code: str
    action: str          # "buy" / "sell" / "hold"
    price: float
    target_price: float  # 目标价
    stop_loss: float     # 止损价
    position_pct: float  # 建议仓位比例
    reason: str
    confidence: float    # 信号置信度 0-1
    strategy: str        # 来源策略名


class BullStrategy:
    """
    牛市策略：趋势追踪 + 动量突破
    
    核心逻辑：
    1. 选股：动量强 + 放量突破 + 均线多头
    2. 买入：突破20日新高 + 量能确认
    3. 止盈：移动止盈（回撤ATR*2则卖出）
    4. 止损：跌破MA20 或 固定-8%
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {
            "max_positions": 5,         # 减少持仓数，集中火力
            "position_pct": 0.15,       # 单只仓位提高
            "stop_loss_pct": -0.12,     # 放宽止损到12%（A股波动大）
            "trailing_atr_mult": 2.5,   # 移动止盈ATR倍数放宽
            "trailing_activate_pct": 0.05,  # 盈利5%后才启动追踪止盈
            "breakout_period": 20,
            "min_volume_ratio": 1.3,    # 降低量比门槛
            "min_momentum_5d": 0.02,    # 降低动量门槛
            "ma_period": 20,
            "min_holding_days": 5,      # 最少持有5天（除非止损）
        }
    
    def generate_signals(self, factors: pd.DataFrame, holdings: Dict, 
                        prices: Dict[str, pd.DataFrame]) -> List[TradeSignal]:
        signals = []
        
        # 卖出信号：检查持仓
        for code, pos in holdings.items():
            if code not in prices:
                continue
            df = prices[code]
            close = df["close"].values[-1]
            
            # 止损检查
            pnl_pct = (close - pos["avg_cost"]) / pos["avg_cost"]
            if pnl_pct <= self.config["stop_loss_pct"]:
                signals.append(TradeSignal(
                    code=code, action="sell", price=close,
                    target_price=0, stop_loss=0, position_pct=1.0,
                    reason=f"止损触发: {pnl_pct:.1%}",
                    confidence=0.95, strategy="bull_stop_loss"
                ))
                continue
            
            # 移动止盈：盈利超过阈值后才启动追踪
            if "max_price" in pos:
                pnl_from_cost = (close - pos["avg_cost"]) / pos["avg_cost"]
                activate_pct = self.config.get("trailing_activate_pct", 0.05)
                if pnl_from_cost > activate_pct:  # 盈利超过5%才启动追踪
                    atr = self._calc_atr(df, 14)
                    trail_stop = pos["max_price"] - atr * self.config["trailing_atr_mult"]
                    if close < trail_stop:
                        signals.append(TradeSignal(
                            code=code, action="sell", price=close,
                            target_price=0, stop_loss=0, position_pct=1.0,
                            reason=f"移动止盈: 从高点{pos['max_price']:.2f}回撤至{close:.2f}",
                            confidence=0.85, strategy="bull_trailing_stop"
                        ))
                        continue
            
            # 跌破MA20
            if len(df) >= 20:
                ma20 = np.mean(df["close"].values[-20:])
                if close < ma20 * 0.98:  # 跌破MA20的2%
                    signals.append(TradeSignal(
                        code=code, action="sell", price=close,
                        target_price=0, stop_loss=0, position_pct=1.0,
                        reason=f"跌破MA20({ma20:.2f})",
                        confidence=0.75, strategy="bull_ma_break"
                    ))
        
        # 买入信号：从因子中选股
        if len(holdings) < self.config["max_positions"]:
            buy_candidates = self._select_buy_candidates(factors, holdings, prices)
            signals.extend(buy_candidates)
        
        return signals
    
    def _select_buy_candidates(self, factors, holdings, prices) -> List[TradeSignal]:
        """选择买入候选"""
        candidates = []
        
        for code in factors.index:
            if code in holdings:
                continue
            
            row = factors.loc[code]
            
            # 牛市买入条件（综合趋势稳定性 + 避免追高）
            momentum_ok = row.get("momentum_5d", 0) > self.config["min_momentum_5d"]
            momentum_20d = row.get("momentum_20d", 0)
            volume_ok = row.get("volume_ratio", 0) > self.config["min_volume_ratio"]
            breakout_ok = row.get("breakout_20d", 0) > 0
            stability = row.get("trend_stability", 0)
            overheat = row.get("overheat_penalty", 0)
            
            # 过热的不买（5日涨超10%）
            if overheat < -0.05:
                continue
            
            # 需要中期动量为正 + 短期动量或突破
            if momentum_20d > 0.02 and (momentum_ok or breakout_ok):
                price = prices[code]["close"].values[-1] if code in prices else 0
                atr = self._calc_atr(prices[code], 14) if code in prices else price * 0.03
                
                # 置信度综合计算
                conf = 0.3
                conf += min(0.3, momentum_20d * 2)  # 中期动量贡献
                conf += min(0.2, stability * 0.3)    # 稳定性贡献
                conf += 0.1 if volume_ok else 0      # 量能确认
                conf += 0.1 if breakout_ok else 0    # 突破确认
                
                candidates.append(TradeSignal(
                    code=code, action="buy", price=price,
                    target_price=price * 1.20,  # 目标+20%
                    stop_loss=price * (1 + self.config["stop_loss_pct"]),
                    position_pct=self.config["position_pct"],
                    reason=f"动量{row.get('momentum_5d',0):.1%} 量比{row.get('volume_ratio',0):.1f}",
                    confidence=min(0.95, conf),
                    strategy="bull_breakout"
                ))
        
        # 按置信度排序，取前N个
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        slots = self.config["max_positions"] - len(holdings)
        return candidates[:slots]
    
    def _calc_atr(self, df: pd.DataFrame, period: int) -> float:
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        if len(c) < period + 1:
            return c[-1] * 0.03
        tr = []
        for i in range(-period, 0):
            tr.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
        return np.mean(tr)


class BearStrategy:
    """
    熊市策略：防守 + 超跌反弹
    
    核心逻辑：
    1. 默认空仓或极轻仓（最多30%仓位）
    2. 只做超跌反弹：RSI<25 + 底背离 + 缩量企稳
    3. 快进快出：目标5-8%就走
    4. 严格止损：-5%无条件出局
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {
            "max_positions": 2,         # 最多2只（更保守）
            "position_pct": 0.06,       # 单只仓位更小
            "max_total_position": 0.20, # 总仓位不超20%
            "stop_loss_pct": -0.05,     # 严格止损5%
            "take_profit_pct": 0.05,    # 快速止盈5%（降低目标提高兑现率）
            "rsi_oversold": 20,         # RSI更极端才入场
            "min_drop_from_high": -0.25, # 至少从高点跌25%
            "min_holding_days": 2,      # 最少持有2天
        }
    
    def generate_signals(self, factors: pd.DataFrame, holdings: Dict,
                        prices: Dict[str, pd.DataFrame]) -> List[TradeSignal]:
        signals = []
        
        # 卖出：严格止损 + 快速止盈
        for code, pos in holdings.items():
            if code not in prices:
                continue
            close = prices[code]["close"].values[-1]
            pnl_pct = (close - pos["avg_cost"]) / pos["avg_cost"]
            
            # 止损
            if pnl_pct <= self.config["stop_loss_pct"]:
                signals.append(TradeSignal(
                    code=code, action="sell", price=close,
                    target_price=0, stop_loss=0, position_pct=1.0,
                    reason=f"熊市止损: {pnl_pct:.1%}",
                    confidence=0.98, strategy="bear_stop_loss"
                ))
            # 止盈
            elif pnl_pct >= self.config["take_profit_pct"]:
                signals.append(TradeSignal(
                    code=code, action="sell", price=close,
                    target_price=0, stop_loss=0, position_pct=1.0,
                    reason=f"熊市止盈: {pnl_pct:.1%}",
                    confidence=0.9, strategy="bear_take_profit"
                ))
            # 持有超过5天也考虑出
            elif pos.get("hold_days", 0) > 5 and pnl_pct > 0:
                signals.append(TradeSignal(
                    code=code, action="sell", price=close,
                    target_price=0, stop_loss=0, position_pct=1.0,
                    reason=f"熊市持有超5天，落袋: {pnl_pct:.1%}",
                    confidence=0.7, strategy="bear_time_exit"
                ))
        
        # 买入：极度谨慎，只做超跌反弹
        total_pos = sum(p.get("position_pct", 0.1) for p in holdings.values())
        if total_pos < self.config["max_total_position"] and len(holdings) < self.config["max_positions"]:
            for code in factors.index:
                if code in holdings:
                    continue
                row = factors.loc[code]
                
                rsi = row.get("rsi_14", 50)
                oversold = row.get("oversold_depth", 0)
                divergence = row.get("bear_divergence", 0)
                vol_dry = row.get("volume_dry", 0)
                
                # 超跌 + RSI极低 + 缩量（地量见地价）
                if (rsi < self.config["rsi_oversold"] and 
                    oversold < self.config["min_drop_from_high"] and
                    vol_dry > 0.2):  # 必须缩量
                    price = prices[code]["close"].values[-1] if code in prices else 0
                    
                    # 企稳确认：最近3天不再创新低
                    if code in prices:
                        closes = prices[code]["close"].values
                        if len(closes) >= 5:
                            if closes[-1] <= min(closes[-5:]) * 0.99:
                                continue  # 还在创新低，跳过
                    
                    signals.append(TradeSignal(
                        code=code, action="buy", price=price,
                        target_price=price * (1 + self.config["take_profit_pct"]),
                        stop_loss=price * (1 + self.config["stop_loss_pct"]),
                        position_pct=self.config["position_pct"],
                        reason=f"超跌反弹: RSI={rsi:.0f} 跌幅{oversold:.1%}",
                        confidence=0.5 + divergence * 0.3,
                        strategy="bear_oversold_bounce"
                    ))
        
        return signals


class OscillationStrategy:
    """
    震荡策略：高抛低吸 + 区间交易
    
    核心逻辑：
    1. 识别震荡区间（20日高低点）
    2. 接近下轨买入，接近上轨卖出
    3. 布林带 + RSI 双确认
    4. 仓位中等（50%左右）
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {
            "max_positions": 4,
            "position_pct": 0.10,
            "max_total_position": 0.45,
            "stop_loss_pct": -0.07,     # 稍微放宽
            "take_profit_pct": 0.05,    # 降低目标提高兑现率
            "buy_range_threshold": 0.20, # 更低才买（更极端）
            "sell_range_threshold": 0.75, # 更早卖
            "rsi_buy": 30,              # RSI更低才买
            "rsi_sell": 65,
            "min_holding_days": 3,      # 最少持有3天
        }
    
    def generate_signals(self, factors: pd.DataFrame, holdings: Dict,
                        prices: Dict[str, pd.DataFrame]) -> List[TradeSignal]:
        signals = []
        
        # 卖出逻辑
        for code, pos in holdings.items():
            if code not in prices:
                continue
            close = prices[code]["close"].values[-1]
            pnl_pct = (close - pos["avg_cost"]) / pos["avg_cost"]
            
            # 止损
            if pnl_pct <= self.config["stop_loss_pct"]:
                signals.append(TradeSignal(
                    code=code, action="sell", price=close,
                    target_price=0, stop_loss=0, position_pct=1.0,
                    reason=f"震荡止损: {pnl_pct:.1%}",
                    confidence=0.95, strategy="osc_stop_loss"
                ))
                continue
            
            # 到达区间上轨 或 止盈
            if code in factors.index:
                range_pos = factors.loc[code].get("range_position", 0.5)
                rsi = factors.loc[code].get("rsi_14", 50)
                
                if range_pos > self.config["sell_range_threshold"] or rsi > self.config["rsi_sell"]:
                    signals.append(TradeSignal(
                        code=code, action="sell", price=close,
                        target_price=0, stop_loss=0, position_pct=1.0,
                        reason=f"震荡高抛: 区间位置{range_pos:.0%} RSI={rsi:.0f}",
                        confidence=0.8, strategy="osc_sell_high"
                    ))
                elif pnl_pct >= self.config["take_profit_pct"]:
                    signals.append(TradeSignal(
                        code=code, action="sell", price=close,
                        target_price=0, stop_loss=0, position_pct=1.0,
                        reason=f"震荡止盈: {pnl_pct:.1%}",
                        confidence=0.85, strategy="osc_take_profit"
                    ))
        
        # 买入：区间下轨 + RSI低
        total_pos = sum(p.get("position_pct", 0.1) for p in holdings.values())
        if total_pos < self.config["max_total_position"] and len(holdings) < self.config["max_positions"]:
            for code in factors.index:
                if code in holdings:
                    continue
                row = factors.loc[code]
                
                range_pos = row.get("range_position", 0.5)
                rsi = row.get("rsi_14", 50)
                boll_pos = row.get("bollinger_position", 0.5)
                vol_dry = row.get("volume_dry", 0)
                momentum_20d = row.get("momentum_20d", 0)
                
                # 过滤趋势性下跌（20日跌超15%不是震荡）
                if momentum_20d < -0.15:
                    continue
                
                # 区间底部 + RSI低 + 缩量 + 支撑确认
                if (range_pos < self.config["buy_range_threshold"] and 
                    rsi < self.config["rsi_buy"] and vol_dry > 0.3):
                    price = prices[code]["close"].values[-1] if code in prices else 0
                    
                    # 确认不是持续创新低
                    if code in prices:
                        closes = prices[code]["close"].values
                        if len(closes) >= 5:
                            recent_low = min(closes[-5:])
                            if closes[-1] <= recent_low * 0.99:
                                continue  # 还在创新低，等企稳
                    
                    signals.append(TradeSignal(
                        code=code, action="buy", price=price,
                        target_price=price * (1 + self.config["take_profit_pct"]),
                        stop_loss=price * (1 + self.config["stop_loss_pct"]),
                        position_pct=self.config["position_pct"],
                        reason=f"震荡低吸: 区间{range_pos:.0%} RSI={rsi:.0f} 缩量{vol_dry:.1f}",
                        confidence=0.6 + (1 - range_pos) * 0.3,
                        strategy="osc_buy_low"
                    ))
        
        return signals


class AdaptiveStrategyEngine:
    """
    自适应策略引擎：根据市场状态自动切换策略
    """
    
    def __init__(self):
        self.bull_strategy = BullStrategy()
        self.bear_strategy = BearStrategy()
        self.osc_strategy = OscillationStrategy()
    
    def execute(self, market_state: str, factors: pd.DataFrame, 
                holdings: Dict, prices: Dict[str, pd.DataFrame]) -> List[TradeSignal]:
        """
        根据市场状态执行对应策略
        """
        if market_state == "bull":
            return self.bull_strategy.generate_signals(factors, holdings, prices)
        elif market_state == "bear":
            return self.bear_strategy.generate_signals(factors, holdings, prices)
        elif market_state == "osc":
            return self.osc_strategy.generate_signals(factors, holdings, prices)
        else:
            # 转换期：用震荡策略但降低仓位
            signals = self.osc_strategy.generate_signals(factors, holdings, prices)
            for s in signals:
                if s.action == "buy":
                    s.position_pct *= 0.5  # 仓位减半
            return signals
