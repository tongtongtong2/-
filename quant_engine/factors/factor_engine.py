"""
多因子计算引擎
适配三种市场状态的因子库：
- 牛市因子：动量、突破、资金流入
- 熊市因子：超跌反弹、防御性、低波动
- 震荡因子：均值回归、布林带、RSI极值
"""
import numpy as np
import pandas as pd
from typing import Dict, List


class FactorEngine:
    """
    统一因子计算接口
    输入：个股 OHLCV DataFrame
    输出：因子值 DataFrame（每行一只股票，每列一个因子）
    """
    
    def compute_all(self, df: pd.DataFrame, market_state: str = "bull") -> pd.DataFrame:
        """
        计算所有因子
        
        Parameters
        ----------
        df : pd.DataFrame
            columns: [date, code, open, high, low, close, volume, amount]
        market_state : str
            "bull" / "bear" / "osc" - 决定因子权重
        """
        results = {}
        
        # 通用因子（所有状态都用）
        results["momentum_5d"] = self._momentum(df, 5)
        results["momentum_20d"] = self._momentum(df, 20)
        results["volume_ratio"] = self._volume_ratio(df, 5, 20)
        results["rsi_14"] = self._rsi(df, 14)
        results["atr_pct"] = self._atr_percent(df, 14)
        
        # 牛市专用因子（注重趋势稳定性，避免追高）
        if market_state == "bull":
            results["breakout_20d"] = self._breakout_strength(df, 20)
            results["ma_support"] = self._ma_support_distance(df)
            results["volume_breakout"] = self._volume_breakout(df)
            results["trend_stability"] = self._trend_stability(df)  # 新增：趋势稳定性
            results["relative_strength"] = self._relative_strength(df, 20)
            # 过热惩罚：短期涨太多的降权
            results["overheat_penalty"] = self._overheat_penalty(df)
        
        # 熊市专用因子
        elif market_state == "bear":
            results["oversold_depth"] = self._oversold_depth(df)
            results["support_distance"] = self._support_distance(df, 60)
            results["low_volatility"] = self._low_volatility_score(df)
            results["dividend_yield"] = self._dividend_proxy(df)
            results["bear_divergence"] = self._bear_divergence(df)
        
        # 震荡专用因子
        elif market_state == "osc":
            results["bollinger_position"] = self._bollinger_position(df)
            results["rsi_extreme"] = self._rsi_extreme(df)
            results["mean_reversion_5d"] = self._mean_reversion(df, 5)
            results["range_position"] = self._range_position(df, 20)
            results["volume_dry"] = self._volume_dry(df)
        
        return pd.DataFrame(results)
    
    # ==================== 通用因子 ====================
    
    def _momentum(self, df: pd.DataFrame, period: int) -> pd.Series:
        """N日动量 = (close - close_n) / close_n"""
        close = df.groupby("code")["close"].last()
        close_n = df.groupby("code")["close"].apply(lambda x: x.iloc[-period-1] if len(x) > period else np.nan)
        return (close - close_n) / close_n
    
    def _volume_ratio(self, df: pd.DataFrame, short: int, long: int) -> pd.Series:
        """量比 = 近short日均量 / 近long日均量"""
        def calc(g):
            vol = g["volume"].values
            if len(vol) < long:
                return np.nan
            return np.mean(vol[-short:]) / np.mean(vol[-long:]) if np.mean(vol[-long:]) > 0 else 1.0
        return df.groupby("code").apply(calc)
    
    def _rsi(self, df: pd.DataFrame, period: int) -> pd.Series:
        """RSI 相对强弱指标"""
        def calc(g):
            close = g["close"].values
            if len(close) < period + 1:
                return np.nan
            deltas = np.diff(close[-(period+1):])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses)
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        return df.groupby("code").apply(calc)
    
    def _atr_percent(self, df: pd.DataFrame, period: int) -> pd.Series:
        """ATR / Close 百分比，衡量波动率"""
        def calc(g):
            h = g["high"].values
            l = g["low"].values
            c = g["close"].values
            if len(c) < period + 1:
                return np.nan
            tr = []
            for i in range(-period, 0):
                tr.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
            atr = np.mean(tr)
            return atr / c[-1] * 100 if c[-1] > 0 else np.nan
        return df.groupby("code").apply(calc)
    
    # ==================== 牛市因子 ====================
    
    def _breakout_strength(self, df: pd.DataFrame, period: int) -> pd.Series:
        """突破强度 = (close - N日最高) / N日最高，正值=创新高"""
        def calc(g):
            c = g["close"].values
            h = g["high"].values
            if len(h) < period:
                return np.nan
            high_n = np.max(h[-period-1:-1])  # 不含今天
            return (c[-1] - high_n) / high_n if high_n > 0 else 0
        return df.groupby("code").apply(calc)
    
    def _ma_support_distance(self, df: pd.DataFrame) -> pd.Series:
        """价格距离MA20的百分比，正值=在均线上方"""
        def calc(g):
            c = g["close"].values
            if len(c) < 20:
                return np.nan
            ma20 = np.mean(c[-20:])
            return (c[-1] - ma20) / ma20 * 100 if ma20 > 0 else 0
        return df.groupby("code").apply(calc)
    
    def _volume_breakout(self, df: pd.DataFrame) -> pd.Series:
        """放量突破信号：今日量 > 20日均量 * 2 且收阳"""
        def calc(g):
            c = g["close"].values
            o = g["open"].values
            v = g["volume"].values
            if len(v) < 20:
                return 0.0
            vol_avg = np.mean(v[-20:])
            is_up = c[-1] > o[-1]
            vol_expand = v[-1] / vol_avg if vol_avg > 0 else 1
            return vol_expand if is_up else 0.0
        return df.groupby("code").apply(calc)
    
    def _consecutive_direction(self, df: pd.DataFrame, direction: str = "up") -> pd.Series:
        """连续上涨/下跌天数"""
        def calc(g):
            c = g["close"].values
            if len(c) < 2:
                return 0
            count = 0
            for i in range(len(c)-1, 0, -1):
                if direction == "up" and c[i] > c[i-1]:
                    count += 1
                elif direction == "down" and c[i] < c[i-1]:
                    count += 1
                else:
                    break
            return count
        return df.groupby("code").apply(calc)
    
    def _relative_strength(self, df: pd.DataFrame, period: int) -> pd.Series:
        """相对强度：个股涨幅 vs 全市场中位数涨幅"""
        def calc(g):
            c = g["close"].values
            if len(c) < period:
                return np.nan
            return (c[-1] - c[-period]) / c[-period]
        all_returns = df.groupby("code").apply(calc)
        median_ret = all_returns.median()
        return all_returns - median_ret
    
    # ==================== 熊市因子 ====================
    
    def _oversold_depth(self, df: pd.DataFrame) -> pd.Series:
        """超跌深度：距离60日高点的跌幅"""
        def calc(g):
            c = g["close"].values
            h = g["high"].values
            if len(h) < 60:
                return np.nan
            high_60 = np.max(h[-60:])
            return (c[-1] - high_60) / high_60  # 负值，越负越超跌
        return df.groupby("code").apply(calc)
    
    def _support_distance(self, df: pd.DataFrame, period: int) -> pd.Series:
        """距离支撑位（N日最低）的距离百分比"""
        def calc(g):
            c = g["close"].values
            l = g["low"].values
            if len(l) < period:
                return np.nan
            low_n = np.min(l[-period:])
            return (c[-1] - low_n) / low_n if low_n > 0 else 0
        return df.groupby("code").apply(calc)
    
    def _low_volatility_score(self, df: pd.DataFrame) -> pd.Series:
        """低波动评分：波动率越低分越高（熊市防御）"""
        atr_pct = self._atr_percent(df, 14)
        # 反转：波动率低 = 分数高
        return -atr_pct
    
    def _dividend_proxy(self, df: pd.DataFrame) -> pd.Series:
        """股息率代理：用低PE/低波动近似（无基本面数据时）"""
        # 简化：用价格稳定性代替
        def calc(g):
            c = g["close"].values
            if len(c) < 20:
                return np.nan
            return -np.std(c[-20:]) / np.mean(c[-20:])  # 变异系数取反
        return df.groupby("code").apply(calc)
    
    def _bear_divergence(self, df: pd.DataFrame) -> pd.Series:
        """底背离信号：价格创新低但RSI未创新低"""
        def calc(g):
            c = g["close"].values
            if len(c) < 30:
                return 0.0
            # 计算两段RSI
            rsi_recent = self._calc_rsi_array(c[-14:])
            rsi_prev = self._calc_rsi_array(c[-28:-14])
            price_lower = c[-1] < np.min(c[-28:-14])
            rsi_higher = rsi_recent > rsi_prev if not np.isnan(rsi_recent) and not np.isnan(rsi_prev) else False
            return 1.0 if (price_lower and rsi_higher) else 0.0
        return df.groupby("code").apply(calc)
    
    def _calc_rsi_array(self, prices) -> float:
        """辅助：计算一段价格的RSI"""
        if len(prices) < 2:
            return np.nan
        deltas = np.diff(prices)
        gains = np.mean(np.where(deltas > 0, deltas, 0))
        losses = np.mean(np.where(deltas < 0, -deltas, 0))
        if losses == 0:
            return 100.0
        return 100 - 100 / (1 + gains / losses)
    
    # ==================== 震荡因子 ====================
    
    def _bollinger_position(self, df: pd.DataFrame) -> pd.Series:
        """布林带位置：(close - lower) / (upper - lower)，0=下轨，1=上轨"""
        def calc(g):
            c = g["close"].values
            if len(c) < 20:
                return np.nan
            ma = np.mean(c[-20:])
            std = np.std(c[-20:])
            upper = ma + 2 * std
            lower = ma - 2 * std
            width = upper - lower
            if width == 0:
                return 0.5
            return (c[-1] - lower) / width
        return df.groupby("code").apply(calc)
    
    def _rsi_extreme(self, df: pd.DataFrame) -> pd.Series:
        """RSI极值信号：<30超卖(正分)，>70超买(负分)"""
        rsi = self._rsi(df, 14)
        # 转换为交易信号：超卖=正，超买=负
        return rsi.apply(lambda x: (30 - x) / 30 if x < 30 else (70 - x) / 30 if x > 70 else 0)
    
    def _mean_reversion(self, df: pd.DataFrame, period: int) -> pd.Series:
        """均值回归因子：偏离均值越远，回归概率越大"""
        def calc(g):
            c = g["close"].values
            if len(c) < period + 10:
                return np.nan
            ma = np.mean(c[-period-10:-1])  # 不含今天的均值
            deviation = (c[-1] - ma) / ma
            return -deviation  # 取反：跌多了给正分（买入信号）
        return df.groupby("code").apply(calc)
    
    def _range_position(self, df: pd.DataFrame, period: int) -> pd.Series:
        """区间位置：在N日高低区间中的位置，0=底部，1=顶部"""
        def calc(g):
            c = g["close"].values
            h = g["high"].values
            l = g["low"].values
            if len(c) < period:
                return np.nan
            high_n = np.max(h[-period:])
            low_n = np.min(l[-period:])
            rng = high_n - low_n
            if rng == 0:
                return 0.5
            return (c[-1] - low_n) / rng
        return df.groupby("code").apply(calc)
    
    def _volume_dry(self, df: pd.DataFrame) -> pd.Series:
        """缩量程度：量越小越可能反弹（震荡市底部特征）"""
        def calc(g):
            v = g["volume"].values
            if len(v) < 20:
                return np.nan
            vol_avg = np.mean(v[-20:])
            return 1 - (v[-1] / vol_avg) if vol_avg > 0 else 0  # 缩量=正分
        return df.groupby("code").apply(calc)
    
    def _trend_stability(self, df: pd.DataFrame) -> pd.Series:
        """趋势稳定性：MA20斜率的一致性（标准差越小越稳定）"""
        def calc(g):
            c = g["close"].values
            if len(c) < 25:
                return np.nan
            # 计算最近5天的MA20值
            ma_values = []
            for i in range(-5, 0):
                ma_values.append(np.mean(c[i-20:i]) if i != -1 else np.mean(c[-20:]))
            # 斜率一致性
            slopes = np.diff(ma_values)
            if np.std(slopes) == 0:
                return 1.0
            # 斜率全为正且稳定 = 高分
            all_positive = all(s > 0 for s in slopes)
            stability = 1.0 / (1.0 + np.std(slopes) * 100)
            return stability * (1.5 if all_positive else 0.5)
        return df.groupby("code").apply(calc)
    
    def _overheat_penalty(self, df: pd.DataFrame) -> pd.Series:
        """过热惩罚：5日涨幅超过10%的给负分"""
        def calc(g):
            c = g["close"].values
            if len(c) < 6:
                return 0.0
            ret_5d = (c[-1] - c[-6]) / c[-6]
            if ret_5d > 0.10:
                return -(ret_5d - 0.10) * 5  # 超过10%的部分给负分
            return 0.0
        return df.groupby("code").apply(calc)
