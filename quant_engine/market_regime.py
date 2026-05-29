"""
市场状态识别器 (Market Regime Detector)
识别当前市场处于牛市/熊市/震荡，驱动策略切换。

方法：
1. 趋势判断：MA20/MA60/MA120 多头排列 vs 空头排列
2. 波动率状态：ATR 百分位判断震荡 vs 趋势
3. 市场宽度：涨跌比、新高新低比
4. 资金流向：北向资金、融资余额变化率
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MarketState(Enum):
    BULL = "bull"           # 牛市：趋势向上，进攻
    BEAR = "bear"           # 熊市：趋势向下，防守
    OSCILLATION = "osc"    # 震荡：无明确方向，高抛低吸
    TRANSITION = "trans"    # 转换期：状态切换中，轻仓观望


@dataclass
class RegimeSignal:
    state: MarketState
    confidence: float       # 0-1 置信度
    sub_phase: str          # 细分阶段：如牛市初期/中期/末期
    position_ratio: float   # 建议仓位比例 0-1
    reason: str             # 判断依据


class MarketRegimeDetector:
    """
    多维度市场状态识别器
    
    核心逻辑：
    - 牛市：MA20 > MA60 > MA120 + 量能放大 + 宽度扩张
    - 熊市：MA20 < MA60 < MA120 + 量能萎缩 + 宽度收缩
    - 震荡：均线缠绕 + ATR 低位 + 涨跌交替
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {
            "ma_short": 20,
            "ma_mid": 60,
            "ma_long": 120,
            "atr_period": 14,
            "atr_pct_threshold": 50,
            "breadth_bull_threshold": 0.6,
            "breadth_bear_threshold": 0.35,
            "vol_expansion_ratio": 1.3,
            "transition_days": 5,
            "switch_cooldown": 10,       # 状态切换冷却期（天）
            "confirmation_days": 3,      # 新状态需连续确认3天
        }
        self._history = []
        self._current_state = None
        self._pending_state = None
        self._pending_count = 0
        self._cooldown_counter = 0
    
    def detect(self, index_df: pd.DataFrame, breadth_df: pd.DataFrame = None) -> RegimeSignal:
        """
        识别市场状态（带冷却期和确认机制）
        """
        if len(index_df) < self.config["ma_long"] + 10:
            return RegimeSignal(MarketState.OSCILLATION, 0.3, "数据不足", 0.3, "历史数据不足以判断")
        
        close = index_df["close"].values
        volume = index_df["volume"].values
        high = index_df["high"].values
        low = index_df["low"].values
        
        # 1. 均线系统
        ma_short = self._sma(close, self.config["ma_short"])
        ma_mid = self._sma(close, self.config["ma_mid"])
        ma_long = self._sma(close, self.config["ma_long"])
        
        trend_score = self._calc_trend_score(close, ma_short, ma_mid, ma_long)
        
        # 2. 波动率状态
        atr = self._calc_atr(high, low, close, self.config["atr_period"])
        atr_pct = self._calc_atr_percentile(atr)
        
        # 3. 量能状态
        vol_ratio = self._calc_volume_ratio(volume)
        
        # 4. 市场宽度（如果有数据）
        breadth_score = self._calc_breadth_score(breadth_df) if breadth_df is not None else 0.5
        
        # 5. 综合判断
        raw_signal = self._synthesize(trend_score, atr_pct, vol_ratio, breadth_score, close)
        
        # 6. 状态切换冷却期 + 确认机制
        if self._current_state is None:
            self._current_state = raw_signal.state
            return raw_signal
        
        # 冷却期内保持当前状态
        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            raw_signal.state = self._current_state
            return raw_signal
        
        # 状态变化需要连续确认
        if raw_signal.state != self._current_state:
            if raw_signal.state == self._pending_state:
                self._pending_count += 1
            else:
                self._pending_state = raw_signal.state
                self._pending_count = 1
            
            if self._pending_count >= self.config["confirmation_days"]:
                # 确认切换
                self._current_state = raw_signal.state
                self._cooldown_counter = self.config["switch_cooldown"]
                self._pending_state = None
                self._pending_count = 0
            else:
                # 未确认，保持当前状态
                raw_signal.state = self._current_state
        else:
            self._pending_state = None
            self._pending_count = 0
        
        return raw_signal
    
    def _sma(self, data: np.ndarray, period: int) -> np.ndarray:
        """简单移动平均"""
        result = np.full_like(data, np.nan, dtype=float)
        for i in range(period - 1, len(data)):
            result[i] = np.mean(data[i - period + 1:i + 1])
        return result
    
    def _calc_trend_score(self, close, ma_short, ma_mid, ma_long) -> float:
        """
        趋势评分 [-1, 1]
        +1: 完美多头排列
        -1: 完美空头排列
        0: 均线缠绕
        """
        # 取最近值
        c = close[-1]
        ms = ma_short[-1]
        mm = ma_mid[-1]
        ml = ma_long[-1]
        
        if np.isnan(ms) or np.isnan(mm) or np.isnan(ml):
            return 0.0
        
        score = 0.0
        # 价格与均线关系
        if c > ms: score += 0.2
        else: score -= 0.2
        if ms > mm: score += 0.3
        else: score -= 0.3
        if mm > ml: score += 0.3
        else: score -= 0.3
        
        # 均线斜率
        if len(ma_mid) > 5:
            slope = (ma_mid[-1] - ma_mid[-6]) / ma_mid[-6] if ma_mid[-6] != 0 else 0
            score += np.clip(slope * 10, -0.2, 0.2)
        
        return np.clip(score, -1.0, 1.0)
    
    def _calc_atr(self, high, low, close, period) -> np.ndarray:
        """计算 ATR"""
        tr = np.zeros(len(high))
        for i in range(1, len(high)):
            tr[i] = max(high[i] - low[i], 
                       abs(high[i] - close[i-1]), 
                       abs(low[i] - close[i-1]))
        
        atr = np.full_like(tr, np.nan)
        atr[period] = np.mean(tr[1:period+1])
        for i in range(period + 1, len(tr)):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
        return atr
    
    def _calc_atr_percentile(self, atr: np.ndarray) -> float:
        """ATR 在历史中的百分位"""
        valid = atr[~np.isnan(atr)]
        if len(valid) < 20:
            return 50.0
        current = valid[-1]
        return float(np.sum(valid < current) / len(valid) * 100)
    
    def _calc_volume_ratio(self, volume: np.ndarray) -> float:
        """近5日均量 / 近20日均量"""
        if len(volume) < 20:
            return 1.0
        vol_5 = np.mean(volume[-5:])
        vol_20 = np.mean(volume[-20:])
        return vol_5 / vol_20 if vol_20 > 0 else 1.0
    
    def _calc_breadth_score(self, breadth_df: pd.DataFrame) -> float:
        """市场宽度评分 [0, 1]"""
        if breadth_df is None or len(breadth_df) == 0:
            return 0.5
        recent = breadth_df.tail(5)
        adv = recent["advance_count"].sum()
        dec = recent["decline_count"].sum()
        total = adv + dec
        if total == 0:
            return 0.5
        return adv / total
    
    def _synthesize(self, trend_score, atr_pct, vol_ratio, breadth_score, close) -> RegimeSignal:
        """综合所有维度，输出最终状态判断"""
        
        # 牛市条件：趋势强（无breadth数据时放宽breadth要求）
        if trend_score > 0.5 and breadth_score >= 0.45:
            confidence = min(1.0, (trend_score + breadth_score) / 2)
            if trend_score > 0.8 and vol_ratio > 1.2:
                sub = "加速期"
                pos = 0.9
            elif trend_score > 0.5:
                sub = "上升期"
                pos = 0.7
            else:
                sub = "初期"
                pos = 0.5
            return RegimeSignal(MarketState.BULL, confidence, sub, pos,
                              f"趋势分{trend_score:.2f} 宽度{breadth_score:.2f} 量比{vol_ratio:.2f}")
        
        # 熊市条件：趋势弱（无breadth数据时放宽）
        elif trend_score < -0.4 and breadth_score <= 0.55:
            confidence = min(1.0, abs(trend_score))
            if trend_score < -0.7:
                sub = "加速下跌"
                pos = 0.0
            elif trend_score < -0.4:
                sub = "下降趋势"
                pos = 0.1
            else:
                sub = "弱势"
                pos = 0.2
            return RegimeSignal(MarketState.BEAR, confidence, sub, pos,
                              f"趋势分{trend_score:.2f} 宽度{breadth_score:.2f} 量比{vol_ratio:.2f}")
        
        # 震荡条件：趋势不明 + 波动率低
        elif abs(trend_score) < 0.4 and atr_pct < self.config["atr_pct_threshold"]:
            confidence = 1.0 - abs(trend_score)
            pos = 0.4
            return RegimeSignal(MarketState.OSCILLATION, confidence, "区间震荡", pos,
                              f"趋势分{trend_score:.2f} ATR百分位{atr_pct:.0f} 量比{vol_ratio:.2f}")
        
        # 转换期
        else:
            pos = 0.3
            return RegimeSignal(MarketState.TRANSITION, 0.4, "状态切换中", pos,
                              f"趋势分{trend_score:.2f} ATR百分位{atr_pct:.0f} 宽度{breadth_score:.2f}")
