"""买卖信号生成器：根据收益率、均线、量能、持有时长生成 buy/hold/sell。"""
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
    ):
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.max_hold_days = max_hold_days

    @staticmethod
    def _ma(series: pd.Series, n: int) -> Optional[float]:
        s = series.dropna()
        if len(s) < n:
            return None
        return float(s.tail(n).mean())

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
    ) -> Tuple[str, str]:
        """返回 (signal, reason)。change_percent 为相对推荐价的涨跌幅，单位为小数。"""
        if is_initial:
            return "buy", "首次推荐买入"

        if change_percent >= self.take_profit:
            return "sell", f"止盈：累计涨幅 {change_percent * 100:.2f}% ≥ {self.take_profit * 100:.0f}%"
        if change_percent <= self.stop_loss:
            return "sell", f"止损：累计跌幅 {change_percent * 100:.2f}% ≤ {self.stop_loss * 100:.0f}%"

        if hold_days >= self.max_hold_days:
            return "sell", f"持有 {hold_days} 个交易日，到期平仓（当前 {change_percent*100:.2f}%）"

        # 中长期：只有持有 >= 5 天 + MA10 跌破 MA20 + 已经亏损 才认定趋势破坏
        if hold_days >= 5:
            deteriorated = self.check_technical_deterioration(history) if history is not None else False
            if deteriorated and change_percent < 0:
                return "sell", "趋势破坏：MA10 跌破 MA20 且已亏损"

        return "hold", f"持有中，当前涨跌幅 {change_percent * 100:.2f}%"
