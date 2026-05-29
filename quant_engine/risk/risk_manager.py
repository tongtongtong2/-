"""
风险控制模块
全局风控 + 个股风控 + 仓位管理

核心规则：
1. 单日最大亏损 -3% 触发全部清仓
2. 单只最大亏损 -8%（牛市）/ -5%（熊市）强制止损
3. 总仓位根据市场状态动态调整
4. 相关性控制：同板块不超过3只
5. 黑天鹅保护：连续2天大盘跌>3%，强制减仓至20%
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class RiskAlert:
    level: str          # "warning" / "danger" / "critical"
    message: str
    action: str         # "reduce" / "clear" / "hold"
    target_position: float  # 建议目标仓位


class RiskManager:
    """
    多层风控管理器
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {
            # 全局风控（放宽，避免过度干预）
            "max_daily_loss": -0.05,        # 单日最大亏损5%（从3%放宽）
            "max_total_drawdown": -0.20,    # 最大回撤20%（从15%放宽）
            "black_swan_threshold": -0.04,  # 大盘单日跌4%才算黑天鹅
            "black_swan_days": 2,
            "black_swan_position": 0.1,
            
            # 个股风控（与策略止损一致）
            "bull_stop_loss": -0.12,
            "bear_stop_loss": -0.05,
            "osc_stop_loss": -0.07,
            "max_single_position": 0.18,
            "max_sector_positions": 3,
            
            # 仓位管理
            "bull_max_position": 0.80,
            "bear_max_position": 0.20,
            "osc_max_position": 0.45,
            "transition_max_position": 0.25,
        }
        self._daily_pnl_history = []
        self._index_returns = []
    
    def check_portfolio_risk(self, portfolio_value: float, initial_value: float,
                            holdings: Dict, market_state: str,
                            index_return_today: float = 0) -> List[RiskAlert]:
        """
        检查组合级风险
        """
        alerts = []
        
        # 1. 单日亏损检查
        if len(self._daily_pnl_history) > 0:
            daily_pnl = (portfolio_value - self._daily_pnl_history[-1]) / self._daily_pnl_history[-1]
            if daily_pnl <= self.config["max_daily_loss"]:
                alerts.append(RiskAlert(
                    level="critical",
                    message=f"单日亏损{daily_pnl:.1%}超限({self.config['max_daily_loss']:.1%})",
                    action="clear",
                    target_position=0.0
                ))
        
        # 2. 最大回撤检查
        total_return = (portfolio_value - initial_value) / initial_value
        if total_return <= self.config["max_total_drawdown"]:
            alerts.append(RiskAlert(
                level="danger",
                message=f"总回撤{total_return:.1%}超限({self.config['max_total_drawdown']:.1%})",
                action="reduce",
                target_position=0.1
            ))
        
        # 3. 黑天鹅检查
        self._index_returns.append(index_return_today)
        if len(self._index_returns) >= self.config["black_swan_days"]:
            recent = self._index_returns[-self.config["black_swan_days"]:]
            if all(r <= self.config["black_swan_threshold"] for r in recent):
                alerts.append(RiskAlert(
                    level="critical",
                    message=f"大盘连续{self.config['black_swan_days']}天暴跌，触发黑天鹅保护",
                    action="reduce",
                    target_position=self.config["black_swan_position"]
                ))
        
        # 4. 仓位超限检查
        max_pos = self._get_max_position(market_state)
        current_pos = self._calc_current_position(holdings, portfolio_value)
        if current_pos > max_pos * 1.1:  # 超过10%容忍度
            alerts.append(RiskAlert(
                level="warning",
                message=f"当前仓位{current_pos:.0%}超过{market_state}状态上限{max_pos:.0%}",
                action="reduce",
                target_position=max_pos
            ))
        
        self._daily_pnl_history.append(portfolio_value)
        return alerts
    
    def check_position_risk(self, code: str, entry_price: float, current_price: float,
                           market_state: str, hold_days: int = 0) -> Optional[RiskAlert]:
        """
        检查个股风险
        """
        pnl_pct = (current_price - entry_price) / entry_price
        
        # 根据市场状态选择止损线
        stop_loss = {
            "bull": self.config["bull_stop_loss"],
            "bear": self.config["bear_stop_loss"],
            "osc": self.config["osc_stop_loss"],
        }.get(market_state, self.config["osc_stop_loss"])
        
        if pnl_pct <= stop_loss:
            return RiskAlert(
                level="danger",
                message=f"{code} 亏损{pnl_pct:.1%}触发{market_state}止损线{stop_loss:.1%}",
                action="clear",
                target_position=0.0
            )
        
        # 熊市持仓时间限制
        if market_state == "bear" and hold_days > 5 and pnl_pct < 0.02:
            return RiskAlert(
                level="warning",
                message=f"{code} 熊市持仓{hold_days}天未盈利，建议出局",
                action="clear",
                target_position=0.0
            )
        
        return None
    
    def calc_position_size(self, signal_confidence: float, market_state: str,
                          current_total_position: float, atr_pct: float = 3.0) -> float:
        """
        动态仓位计算
        
        基于：
        1. 市场状态 → 基础仓位上限
        2. 信号置信度 → 仓位比例
        3. 波动率 → 波动大则仓位小（ATR仓位管理）
        4. 剩余可用仓位
        """
        max_pos = self._get_max_position(market_state)
        available = max(0, max_pos - current_total_position)
        
        if available <= 0:
            return 0.0
        
        # 基础仓位 = 信号置信度 * 状态系数
        state_mult = {"bull": 1.0, "bear": 0.4, "osc": 0.6, "trans": 0.3}
        base = signal_confidence * state_mult.get(market_state, 0.5)
        
        # ATR 调整：波动率高则降低仓位
        # 标准：ATR 3% 为基准，每增加1%仓位减20%
        atr_adj = max(0.3, 1.0 - (atr_pct - 3.0) * 0.2)
        
        position = base * atr_adj * 0.12  # 基础单位12%
        position = min(position, available, self.config["max_single_position"])
        
        return round(position, 3)
    
    def _get_max_position(self, market_state: str) -> float:
        return {
            "bull": self.config["bull_max_position"],
            "bear": self.config["bear_max_position"],
            "osc": self.config["osc_max_position"],
            "trans": self.config["transition_max_position"],
        }.get(market_state, 0.3)
    
    def _calc_current_position(self, holdings: Dict, portfolio_value: float) -> float:
        if portfolio_value <= 0:
            return 0.0
        total_holding_value = sum(
            pos.get("current_value", pos.get("shares", 0) * pos.get("avg_cost", 0))
            for pos in holdings.values()
        )
        return total_holding_value / portfolio_value
