"""买卖信号生成器：根据收益率、均线、量能、持有时长生成 buy/hold/sell。

支持 ATR 动态止损和移动止盈（从 backtest/engine.py 移植）。
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from config import Config


class SignalGenerator:
    def __init__(
        self,
        take_profit: float = Config.TAKE_PROFIT,
        stop_loss: float = Config.STOP_LOSS,
        max_hold_days: int = Config.MAX_HOLD_DAYS,
        use_atr_stop: bool = Config.USE_ATR_STOP,
        atr_mult: float = Config.ATR_MULT,
        trailing_atr_mult: float = Config.TRAILING_ATR_MULT,
    ):
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.max_hold_days = max_hold_days
        self.use_atr_stop = use_atr_stop
        self.atr_mult = atr_mult
        self.trailing_atr_mult = trailing_atr_mult

    @staticmethod
    def _ma(series: pd.Series, n: int) -> Optional[float]:
        s = series.dropna()
        if len(s) < n:
            return None
        return float(s.tail(n).mean())

    @staticmethod
    def _calc_atr(history: pd.DataFrame) -> float:
        """Calculate ATR(14) from daily OHLC data."""
        if history is None or history.empty or len(history) < 15:
            return 0.0
        closes = history["close"].astype(float).values[-15:]
        highs = history["high"].astype(float).values[-15:] if "high" in history.columns else closes
        lows = history["low"].astype(float).values[-15:] if "low" in history.columns else closes
        prev_closes = closes[:-1]
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - prev_closes),
                np.abs(lows[1:] - prev_closes)
            )
        )
        return float(np.mean(tr))

    def check_technical_deterioration(self, history: pd.DataFrame) -> bool:
        """中长期：MA10 跌破 MA20 才算技术面恶化（避免短期噪音洗下车）。"""
        if history is None or history.empty or "close" not in history.columns:
            return False
        ma10 = self._ma(history["close"], 10)
        ma20 = self._ma(history["close"], 20)
        if ma10 is None or ma20 is None:
            return False
        return ma10 < ma20

    def _volume_shrink(self, history: pd.DataFrame) -> bool:
        if history is None or history.empty or "volume" not in history.columns:
            return False
        vols = history["volume"].dropna().values
        if len(vols) < 20:
            return False
        avg20 = float(np.mean(vols[-20:]))
        if avg20 <= 0:
            return False
        return float(vols[-1]) < avg20 * 0.4

    def generate_signal(
        self,
        change_percent: float,
        history: Optional[pd.DataFrame] = None,
        hold_days: int = 0,
        is_initial: bool = False,
        entry_price: float = 0,
    ) -> Tuple[str, str]:
        """返回 (signal, reason)。change_percent 为相对推荐价的涨跌幅，单位为小数。"""
        if is_initial:
            return "buy", "首次推荐买入"

        # 计算有效止盈止损（ATR 动态 or 固定）
        effective_tp = self.take_profit
        effective_sl = self.stop_loss

        if self.use_atr_stop and entry_price > 0 and history is not None:
            atr = self._calc_atr(history)
            if atr > 0:
                atr_stop_pct = -self.atr_mult * atr / entry_price
                # ATR止损和固定止损取更宽松的（允许更大波动）
                effective_sl = max(self.stop_loss, atr_stop_pct)

                # 移动止盈：盈利超过 trailing_atr_mult * ATR 后，止损提到成本价
                trailing_threshold = self.trailing_atr_mult * atr / entry_price
                if change_percent >= trailing_threshold:
                    effective_sl = max(effective_sl, 0.0)

        if change_percent >= effective_tp:
            return "sell", f"止盈：累计涨幅 {change_percent * 100:.2f}% ≥ {effective_tp * 100:.1f}%"
        if change_percent <= effective_sl:
            if effective_sl >= 0:
                return "sell", f"保本止损：回落至成本价（ATR移动止盈触发后）"
            return "sell", f"止损：累计跌幅 {change_percent * 100:.2f}% ≤ {effective_sl * 100:.1f}%"

        if hold_days >= self.max_hold_days:
            return "sell", f"持有 {hold_days} 个交易日，到期平仓（当前 {change_percent*100:.2f}%）"

        # 中长期：只有持有 >= 5 天 + MA10 跌破 MA20 + 已经亏损 才认定趋势破坏
        if hold_days >= 5:
            deteriorated = self.check_technical_deterioration(history) if history is not None else False
            if deteriorated and change_percent < 0:
                return "sell", "趋势破坏：MA10 跌破 MA20 且已亏损"

        return "hold", f"持有中，当前涨跌幅 {change_percent * 100:.2f}%"

    def compute_price_targets(
        self,
        entry_price: float,
        history: Optional[pd.DataFrame] = None,
    ) -> dict:
        """计算具体的止盈价、止损价、移动止盈触发价，供用户设条件单。"""
        if entry_price <= 0:
            return {}

        atr = 0.0
        if self.use_atr_stop and history is not None:
            atr = self._calc_atr(history)

        if atr > 0:
            atr_pct = atr / entry_price
            sl_pct = self.atr_mult * atr_pct
            tp_pct = 4.0 * atr_pct  # 4倍ATR止盈
            trail_trigger_pct = 2.0 * atr_pct  # 2倍ATR启动移动止盈
            # 限制范围
            sl_pct = max(0.03, min(0.08, sl_pct))
            tp_pct = max(0.08, min(0.25, tp_pct))
        else:
            sl_pct = abs(self.stop_loss)
            tp_pct = self.take_profit
            trail_trigger_pct = 0.07

        stop_loss_price = entry_price * (1 - sl_pct)
        take_profit_price = entry_price * (1 + tp_pct)
        trail_trigger_price = entry_price * (1 + trail_trigger_pct)

        return {
            "entry_price": round(entry_price, 2),
            "stop_loss_price": round(stop_loss_price, 2),
            "stop_loss_pct": round(sl_pct * 100, 1),
            "take_profit_price": round(take_profit_price, 2),
            "take_profit_pct": round(tp_pct * 100, 1),
            "trail_trigger_price": round(trail_trigger_price, 2),
            "trail_trigger_pct": round(trail_trigger_pct * 100, 1),
            "atr": round(atr, 3),
        }
