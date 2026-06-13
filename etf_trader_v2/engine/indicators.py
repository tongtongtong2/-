"""技术指标计算 — 纯函数，输入numpy数组，输出标量"""
import numpy as np
from typing import Tuple, Optional


def bollinger_bands(
    closes: np.ndarray,
    period: int = 20,
    num_std: float = 2.0,
) -> Tuple[float, float, float, float]:
    """计算布林带

    Args:
        closes: 收盘价数组（按时间升序，最新在最后）
        period: 均线周期
        num_std: 标准差倍数

    Returns:
        (ma, upper, lower, bb_pos)
        bb_pos: 0~1之间，价格在布林带中的相对位置
    """
    if len(closes) < period:
        return (0.0, 0.0, 0.0, 0.5)

    ma = float(np.mean(closes[-period:]))
    std = float(np.std(closes[-period:], ddof=1))

    if std == 0:
        upper = ma
        lower = ma
    else:
        upper = ma + num_std * std
        lower = ma - num_std * std

    current = float(closes[-1])
    bb_range = upper - lower
    bb_pos = float((current - lower) / bb_range) if bb_range > 0 else 0.5

    return (ma, upper, lower, bb_pos)


def rsi(
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """计算RSI（相对强弱指标）

    Args:
        closes: 收盘价数组
        period: 周期

    Returns:
        RSI值 (0~100)
    """
    if len(closes) < period + 1:
        return 50.0

    deltas = np.diff(closes[-period - 1:])
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)

    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))

    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0

    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[float, float, float]:
    """计算MACD

    Args:
        closes: 收盘价数组
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        (dif, dea, histogram)
    """
    if len(closes) < slow + signal:
        return (0.0, 0.0, 0.0)

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    if ema_fast is None or ema_slow is None:
        return (0.0, 0.0, 0.0)

    dif_series = ema_fast - ema_slow
    dif = float(dif_series[-1])

    # EMA of DIF = DEA
    dea_series = _ema_from_series(dif_series, signal)
    dea = float(dea_series[-1]) if dea_series is not None else 0.0

    histogram = 2.0 * (dif - dea)

    return (dif, dea, histogram)


def atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """计算ATR（平均真实波幅）

    Args:
        highs: 最高价数组
        lows: 最低价数组
        closes: 收盘价数组
        period: 周期

    Returns:
        ATR值
    """
    n = min(len(highs), len(lows), len(closes))
    if n < 2:
        return 0.0

    highs = highs[-n:]
    lows = lows[-n:]
    closes = closes[-n:]

    tr_list = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

    if not tr_list:
        return 0.0

    if len(tr_list) >= period:
        return float(np.mean(tr_list[-period:]))
    else:
        return float(np.mean(tr_list))


def ma(closes: np.ndarray, period: int = 20) -> float:
    """简单移动平均"""
    if len(closes) < period:
        return 0.0
    return float(np.mean(closes[-period:]))


def ma_trend(closes: np.ndarray, period: int = 20) -> float:
    """计算MA趋势（当前MA相对于N天前MA的变化百分比）"""
    if len(closes) < period + 5:
        return 0.0
    current_ma = float(np.mean(closes[-period:]))
    past_ma = float(np.mean(closes[-(period + 5):-5]))
    if past_ma == 0:
        return 0.0
    return float((current_ma - past_ma) / past_ma * 100)


def chg_pct(closes: np.ndarray, offset: int) -> float:
    """计算涨跌幅百分比

    Args:
        closes: 收盘价数组
        offset: 回看天数

    Returns:
        涨跌幅百分比
    """
    if len(closes) < offset + 1:
        return 0.0
    current = float(closes[-1])
    prev = float(closes[-(offset + 1)])
    if prev == 0:
        return 0.0
    return float((current / prev - 1) * 100)


def vol_ratio(volumes: np.ndarray, period: int = 20) -> float:
    """计算量比（当前成交量 / 均量）"""
    if len(volumes) < period + 1:
        return 1.0
    current_vol = float(volumes[-1])
    ma_vol = float(np.mean(volumes[-(period + 1):-1]))
    if ma_vol == 0:
        return 1.0
    return float(current_vol / ma_vol)


def market_env(closes: np.ndarray) -> dict:
    """判断大盘环境：上升/震荡/下跌

    Args:
        closes: 大盘收盘价数组（至少20天）

    Returns:
        {'state': 'bull'|'bear'|'range', 'ma20': float, 'trend': float, 'current': float}
    """
    if len(closes) < 20:
        return {'state': 'unknown', 'ma20': 0.0, 'trend': 0.0, 'current': float(closes[-1]) if len(closes) > 0 else 0.0}

    arr = np.array(closes)
    ma20_val = float(np.mean(arr[-20:]))
    ma20_5d_ago = float(np.mean(arr[-25:-5])) if len(arr) >= 25 else ma20_val
    current = float(arr[-1])

    if ma20_5d_ago == 0:
        trend = 0.0
    else:
        trend = float((ma20_val - ma20_5d_ago) / ma20_5d_ago * 100)

    if trend > 1:
        state = 'bull'
    elif trend < -1:
        state = 'bear'
    else:
        state = 'range'

    return {
        'state': state,
        'current': current,
        'ma20': ma20_val,
        'trend': trend,
    }


# === 内部辅助 ===

def _ema(series: np.ndarray, period: int) -> Optional[np.ndarray]:
    """计算EMA序列"""
    if len(series) < period:
        return None

    alpha = 2.0 / (period + 1)
    result = np.zeros(len(series))
    result[0] = float(series[0])

    for i in range(1, len(series)):
        result[i] = alpha * float(series[i]) + (1 - alpha) * result[i - 1]

    return result


def _ema_from_series(series: np.ndarray, period: int) -> Optional[np.ndarray]:
    """对已有序列计算EMA（用于MACD的DEA线）"""
    return _ema(series, period)
