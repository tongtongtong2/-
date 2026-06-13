"""决策引擎 — 唯一权威的买卖决策实现

规则体系：
- 评分为主（趋势+MACD+RSI的综合信号）
- 布林为过滤器（高位不追、低位可接）
- 大盘熊市时只卖不买
"""
from typing import Optional

from config import BOLL_OVERHEAT, BOLL_OVERSOLD, STOP_LOSS


def decide(
    code: str,
    score: float,
    bb_pos: float,
    rsi_val: float,
    ma20: float,
    ma60: float,
    close: float,
    chg_5d: float,
    chg_20d: float,
    atr_pct: float,
    vol_ratio: float,
    market_state: str,
    held: bool = False,
    entry_pnl: float = 0.0,
) -> dict:
    """核心决策逻辑（唯一权威实现）

    Args:
        code: ETF代码
        score: 综合评分 (-100~100)
        bb_pos: 布林带位置 (0~1)
        rsi_val: RSI值 (0~100)
        ma20: 20日均线
        ma60: 60日均线
        close: 当前价格
        chg_5d: 5日涨跌幅%
        chg_20d: 20日涨跌幅%
        atr_pct: ATR百分比
        vol_ratio: 量比
        market_state: 大盘状态 ('bull', 'bear', 'range', 'unknown')
        held: 是否持仓
        entry_pnl: 持仓盈亏比例（持仓时传入）

    Returns:
        {
            'action': 'BUY'|'SELL'|'HOLD'|'WATCH'|'AVOID'|'TAKE_PROFIT'|'STOP'|'NO_DATA',
            'reason': str,
            'score': float,
            'bb_pos': float,
            'rsi': float,
            'ma20': float,
            'ma60': float,
            'close': float,
            'chg_5d': float,
            'chg_20d': float,
            'atr_pct': float,
        }
    """
    # === 评分体系（主导）===
    strong_buy = score >= 50
    buy_signal = score >= 30
    neutral = -30 <= score < 30
    sell_signal = score < -30
    strong_sell = score < -70

    # === 布林过滤器（辅助）===
    overheated = bb_pos > BOLL_OVERHEAT
    oversold = bb_pos < BOLL_OVERSOLD
    mid_low = bb_pos < 0.50

    # === 趋势 ===
    uptrend = ma20 > ma60

    # === 大盘限制 ===
    bear_block = market_state == 'bear'

    # === 决策矩阵 ===
    action = 'HOLD'
    reason = ''

    # 先检查止损
    if held and entry_pnl <= STOP_LOSS:
        return {
            'action': 'STOP',
            'reason': f'硬止损 {entry_pnl*100:.1f}%',
            'score': score, 'bb_pos': bb_pos, 'rsi': rsi_val,
            'ma20': ma20, 'ma60': ma60, 'close': close,
            'chg_5d': chg_5d, 'chg_20d': chg_20d, 'atr_pct': atr_pct,
            'trend': '↑' if uptrend else '↓',
        }

    if strong_buy:
        if oversold:
            action = 'BUY'
            reason = f'超卖+强看多 (布林{bb_pos:.0%} 评分{score:.0f})'
        elif mid_low:
            action = 'BUY'
            reason = f'回调+强看多 (布林{bb_pos:.0%} 评分{score:.0f})'
        elif overheated:
            if held:
                action = 'TAKE_PROFIT'
                reason = f'冲顶止盈 (布林{bb_pos:.0%} RSI{rsi_val:.0f})'
            else:
                action = 'AVOID'
                reason = f'强看多但已冲顶 等回调 (布林{bb_pos:.0%} RSI{rsi_val:.0f})'
        else:
            action = 'HOLD' if held else 'WATCH'
            reason = f'强看多但偏高 等回踩 (布林{bb_pos:.0%})'

    elif buy_signal:
        if oversold:
            if bear_block:
                action = 'WATCH'
                reason = f'超卖但大盘熊市 等企稳 (布林{bb_pos:.0%})'
            else:
                action = 'BUY'
                reason = f'超卖+看多 (布林{bb_pos:.0%} 评分{score:.0f})'
        elif mid_low:
            action = 'WATCH'
            reason = f'中性偏低 评分{score:.0f} 等信号'
        elif overheated:
            if held:
                action = 'TAKE_PROFIT'
                reason = f'高位+评分{score:.0f} 建议止盈'
            else:
                action = 'AVOID'
                reason = f'高位 不追 (布林{bb_pos:.0%})'
        else:
            action = 'HOLD'
            reason = f'评分{score:.0f} 中高位观望'

    elif neutral:
        if oversold:
            action = 'WATCH'
            reason = f'超卖但评分中性({score:.0f}) 等转强'
        elif overheated:
            if held:
                action = 'TAKE_PROFIT'
                reason = f'高位+评分中性 减仓'
            else:
                action = 'AVOID'
                reason = f'高位+无信号 不碰'
        else:
            action = 'HOLD' if held else 'AVOID'
            reason = f'中性({score:.0f}) 无信号'

    elif sell_signal:
        if held:
            action = 'STOP' if strong_sell else 'SELL'
            reason = f'看空信号 评分{score:.0f}'
        else:
            action = 'AVOID'
            reason = f'评分差({score:.0f}) 不参与'

    # 大盘熊市 + 买入信号 → 降级为WATCH
    if action == 'BUY' and bear_block:
        action = 'WATCH'
        reason += ' [大盘熊市]'

    # 趋势过滤器：下跌趋势不买
    if action == 'BUY' and not uptrend:
        action = 'WATCH'
        reason += ' [下跌趋势]'

    # 成交量：缩量不买
    if action == 'BUY' and vol_ratio < 0.5:
        action = 'WATCH'
        reason += ' [缩量]'

    return {
        'action': action,
        'reason': reason,
        'score': score,
        'bb_pos': bb_pos,
        'rsi': rsi_val,
        'ma20': ma20,
        'ma60': ma60,
        'close': close,
        'chg_5d': chg_5d,
        'chg_20d': chg_20d,
        'atr_pct': atr_pct,
        'trend': '↑' if uptrend else '↓',
    }
