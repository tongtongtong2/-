"""综合评分引擎 — 趋势+MACD+RSI综合打分"""
import numpy as np
from typing import Tuple


def composite_score(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
) -> Tuple[float, float]:
    """综合评分：趋势+MACD+RSI

    Args:
        closes: 收盘价数组
        highs: 最高价数组
        lows: 最低价数组
        volumes: 成交量数组

    Returns:
        (score, trend_score)
        score: -100 到 +100，正值看多，负值看空
        trend_score: 趋势分（单独返回用于趋势判断）
    """
    from engine.indicators import ma, macd, rsi, chg_pct, bollinger_bands

    if len(closes) < 26:
        return (0.0, 0.0)

    # === 趋势评（0~40分）===
    current = float(closes[-1])
    ma20_val = ma(closes, 20)
    ma60_val = ma(closes, 60)

    trend_score = 0.0

    # 短期趋势：价格在MA20上方
    if ma20_val > 0:
        if current > ma20_val:
            trend_score += 10
            # 偏离度加分
            deviation = (current - ma20_val) / ma20_val * 100
            if 0 < deviation < 5:
                trend_score += 5  # 温和上涨，最佳
            elif deviation >= 5:
                trend_score += 2  # 偏离过大
        else:
            trend_score -= 10

    # 中长期趋势：MA20 > MA60
    if ma60_val > 0 and ma20_val > 0:
        if ma20_val > ma60_val:
            trend_score += 10
            # 金叉幅度
            golden_cross = (ma20_val - ma60_val) / ma60_val * 100
            if golden_cross > 2:
                trend_score += 5
        else:
            trend_score -= 10

    # 20日涨跌幅
    chg_20d = chg_pct(closes, 20)
    if chg_20d > 5:
        trend_score += 5
    elif chg_20d < -10:
        trend_score -= 10

    # 趋势分归一化到 -40~40
    trend_score = max(-40, min(40, trend_score))

    # === MACD评（-30~30分）===
    dif, dea, hist = macd(closes)
    macd_score = 0.0

    if dif != 0 or dea != 0:
        # DIF方向
        if dif > 0:
            macd_score += 10
        else:
            macd_score -= 10

        # DIF vs DEA（金叉/死叉）
        if dif > dea:
            macd_score += 10
        else:
            macd_score -= 10

        # 柱状图趋势
        if hist > 0:
            macd_score += min(10, int(abs(hist) * 10))
        else:
            macd_score -= min(10, int(abs(hist) * 10))

    macd_score = max(-30, min(30, macd_score))

    # === RSI评分（-30~30分）===
    rsi_val = rsi(closes)

    if 40 <= rsi_val <= 60:
        rsi_score = 0.0  # 中性
    elif 30 <= rsi_val < 40:
        rsi_score = 15.0  # 偏弱但可能反弹
    elif rsi_val < 30:
        rsi_score = 20.0  # 超卖，反弹潜力
    elif 60 < rsi_val <= 70:
        rsi_score = -10.0  # 偏强但可能回调
    elif rsi_val > 70:
        rsi_score = -25.0  # 超买
    else:
        rsi_score = 0.0

    # 布林带位置修正
    _, _, _, bb_pos = bollinger_bands(closes)
    if bb_pos < 0.2:
        macd_score += 10  # 布林下轨，增加看多权重
    elif bb_pos > 0.8:
        macd_score -= 10  # 布林上轨，增加看空权重

    # === 综合 ===
    score = trend_score + macd_score + rsi_score
    score = max(-100, min(100, score))

    return (score, trend_score)


def score_to_signal(score: float) -> str:
    """评分 → 信号字符串"""
    if score >= 50:
        return "strong_buy"
    elif score >= 30:
        return "buy"
    elif score > -30:
        return "neutral"
    elif score > -70:
        return "sell"
    else:
        return "strong_sell"
