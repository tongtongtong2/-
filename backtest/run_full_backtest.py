"""完整回测：每天选1只最强股买2.5万，ATR动态止盈止损。"""
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
import time

DB_PATH = Path(__file__).parent / "data" / "market_data.db"
INITIAL_CASH = 200_000.0
BUY_AMOUNT = 25_000.0
COMMISSION = 0.00025
STAMP_TAX = 0.001
SLIPPAGE = 0.001
ATR_SL_MULT = 2.0
ATR_TP_MULT = 4.0
ATR_TRAIL_MULT = 2.0
ATR_TRAIL_BACK = 1.0
MAX_HOLD_DAYS = 30
MIN_DAILY_BARS = 70
MAX_RET_5 = 0.10
MAX_RET_20 = 0.30
MAX_VOL_STD = 0.04
LIMIT_UP_PCT = 9.5

def compute_indicators(closes, highs, lows, volumes):
    n = len(closes)
    if n < MIN_DAILY_BARS: return None
    last = closes[-1]
    if last <= 0: return None
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:])
    ret_5 = last / closes[-6] - 1 if closes[-6] > 0 else 0
    ret_20 = last / closes[-21] - 1 if closes[-21] > 0 else 0
    ret_60 = last / closes[-61] - 1 if n >= 62 and closes[-61] > 0 else 0
    daily_ret_20 = np.diff(closes[-21:]) / np.where(closes[-21:-1] > 0, closes[-21:-1], 1)
    vol_std = np.std(daily_ret_20)
    peak = np.maximum.accumulate(closes[-20:])
    drawdown = np.where(peak > 0, (closes[-20:] / peak) - 1, 0)
    max_dd = np.min(drawdown)
    avg5 = np.mean(volumes[-5:])
    avg20 = np.mean(volumes[-20:])
    vol_ratio = avg5 / avg20 if avg20 > 0 else 0.0
    avg_turnover20 = avg20 * np.mean(closes[-20:])
    high60 = np.max(closes[-60:])
    dist_high60 = (high60 - last) / high60 if high60 > 0 else 0.0
    atr14 = 0.0
    if n >= 15:
        tr = np.maximum(highs[-14:] - lows[-14:], np.maximum(np.abs(highs[-14:] - closes[-15:-1]), np.abs(lows[-14:] - closes[-15:-1])))
        atr14 = np.mean(tr)
    return {"last": last, "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "ret_5": ret_5, "ret_20": ret_20, "ret_60": ret_60,
            "vol_std": vol_std, "max_dd": max_dd, "vol_ratio_5_20": vol_ratio,
            "avg_turnover_20": avg_turnover20, "dist_high60": dist_high60, "atr14": atr14}

def passes_hard_filter(ind):
    if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]): return False
    if ind["last"] <= ind["ma60"]: return False
    if ind["ret_5"] >= MAX_RET_5: return False
    if ind["ret_20"] >= MAX_RET_20: return False
    if ind["vol_std"] >= MAX_VOL_STD: return False
    return True

def score_stock(ind):
    score = ind["ret_60"] * 100 * 0.25
    score += min((ind["last"] / ind["ma20"] - 1) * 100, 10) * 0.15
    score += (0.04 - ind["vol_std"]) * 500 * 0.20
    score += (ind["max_dd"] + 0.15) * 100 * 0.10
    vr = ind["vol_ratio_5_20"]
    if 1.0 <= vr <= 2.0: score += (1 - abs(vr - 1.5) / 0.5) * 10 * 0.10
    dist = ind["dist_high60"]
    if 0.05 <= dist <= 0.20: score += (1 - abs(dist - 0.125) / 0.075) * 10 * 0.10
    score += min(ind["avg_turnover_20"] / 1e8, 10) * 0.10
    return score

if __name__ == "__main__":
    main()
