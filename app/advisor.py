"""
投资顾问模块 — 长期/短线总结、买卖点分析、历史图形匹配
"""

from __future__ import annotations

import sqlite3
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.utils import get_logger

logger = get_logger(__name__)

# —— 数据源 ——

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "backtest", "data", "market_data.db")


def _get_db() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH)


def _load_daily(stock_code: str, days: int = 400) -> pd.DataFrame:
    """从 market_data.db 加载日线数据"""
    end = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    conn = _get_db()
    df = pd.read_sql_query(
        "SELECT trade_date, open, high, low, close, volume "
        "FROM daily_bars WHERE stock_code = ? AND trade_date BETWEEN ? AND ? "
        "ORDER BY trade_date",
        conn, params=(stock_code, start, end)
    )
    conn.close()
    if df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed")
    df.set_index("trade_date", inplace=True)
    df.sort_index(inplace=True)
    return df.tail(days)


def _load_index_daily(days: int = 400) -> pd.DataFrame:
    """加载沪深300指数日线"""
    conn = _get_db()
    df = pd.read_sql_query(
        "SELECT trade_date, close FROM index_daily ORDER BY trade_date",
        conn
    )
    conn.close()
    if df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed")
    df.set_index("trade_date", inplace=True)
    df.sort_index(inplace=True)
    return df.tail(days)


# —— 技术指标 ——

def _ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(n).mean()
    avg_loss = loss.rolling(n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal).mean()
    bar = 2 * (dif - dea)
    return dif, dea, bar


def _bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# —— 1. 长期投资总结 ——

def generate_long_term_summary(stock_code: str, months: int = 6) -> Dict:
    """多周期分析：收益率、波动率、最大回撤、与沪深300对比、趋势判断"""
    df = _load_daily(stock_code, days=max(months * 25, 250))
    idx = _load_index_daily(days=max(months * 25, 250))

    if df.empty:
        return {"error": f"未找到 {stock_code} 的日线数据"}

    today = date.today()
    periods = {
        "1个月": (today - timedelta(days=25)),
        "3个月": (today - timedelta(days=70)),
        "6个月": (today - timedelta(days=135)),
        "1年": (today - timedelta(days=260)),
    }

    results = {}
    current_price = float(df["close"].iloc[-1])

    for label, start_date in periods.items():
        subset = df[df.index >= pd.Timestamp(start_date)]
        if len(subset) < 5:
            continue
        start_price = float(subset["close"].iloc[0])
        end_price = float(subset["close"].iloc[-1])
        ret = (end_price - start_price) / start_price

        # 最大回撤
        cummax = subset["close"].cummax()
        drawdown = (subset["close"] - cummax) / cummax
        max_dd = float(drawdown.min())

        # 波动率 (年化)
        daily_ret = subset["close"].pct_change().dropna()
        vol = float(daily_ret.std() * np.sqrt(252)) if len(daily_ret) > 1 else 0.0

        # 胜率
        win_rate = float((daily_ret > 0).mean()) if len(daily_ret) > 1 else 0.0

        # 与沪深300对比
        idx_subset = idx[idx.index >= pd.Timestamp(start_date)] if not idx.empty else pd.DataFrame()
        idx_ret = None
        alpha = None
        if not idx_subset.empty and len(idx_subset) >= 5:
            idx_ret = float((idx_subset["close"].iloc[-1] - idx_subset["close"].iloc[0]) / idx_subset["close"].iloc[0])
            alpha = ret - idx_ret

        results[label] = {
            "区间收益": f"{ret * 100:.2f}%",
            "最大回撤": f"{max_dd * 100:.2f}%",
            "年化波动率": f"{vol * 100:.2f}%",
            "日胜率": f"{win_rate * 100:.1f}%",
            "沪深300收益": f"{idx_ret * 100:.2f}%" if idx_ret is not None else "无数据",
            "超额收益": f"{alpha * 100:.2f}%" if alpha is not None else "无数据",
        }

    # 趋势判断
    ma20 = _ma(df["close"], 20).iloc[-1]
    ma60 = _ma(df["close"], 60).iloc[-1]
    ma120 = _ma(df["close"], 120).iloc[-1] if len(df) >= 120 else None

    trend_signals = []
    if not pd.isna(ma20) and not pd.isna(ma60):
        if current_price > ma20 > ma60:
            trend_signals.append("多头排列(MA20>MA60)，趋势向上")
        elif current_price < ma20 < ma60:
            trend_signals.append("空头排列(MA20<MA60)，趋势向下")
        else:
            trend_signals.append("均线交织，震荡格局")

    if ma120 is not None and not pd.isna(ma120):
        if current_price > ma120:
            trend_signals.append("价格在半年线上方，中长期偏多")
        else:
            trend_signals.append("价格在半年线下方，中长期偏弱")

    return {
        "stock_code": stock_code,
        "current_price": round(current_price, 2),
        "periods": results,
        "trend": trend_signals,
        "data_days": len(df),
    }


# —— 2. 短线总结 ——

def generate_short_term_summary(stock_code: str, days: int = 30) -> Dict:
    """短线分析：近期走势、量价关系、支撑/压力位、短期信号"""
    df = _load_daily(stock_code, days=days + 120)

    if df.empty:
        return {"error": f"未找到 {stock_code} 的日线数据"}

    recent = df.tail(days)
    current_price = float(recent["close"].iloc[-1])

    # 近期收益
    ret_5d = None
    ret_10d = None
    ret_20d = None
    if len(recent) >= 6:
        ret_5d = (current_price - float(recent["close"].iloc[-6])) / float(recent["close"].iloc[-6])
    if len(recent) >= 11:
        ret_10d = (current_price - float(recent["close"].iloc[-11])) / float(recent["close"].iloc[-11])
    if len(recent) >= 21:
        ret_20d = (current_price - float(recent["close"].iloc[-21])) / float(recent["close"].iloc[-21])

    # 量价分析
    avg_vol_20 = float(recent["volume"].tail(20).mean())
    recent_vol = float(recent["volume"].tail(5).mean())
    vol_ratio = recent_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # 连涨/连跌
    up_days = 0
    down_days = 0
    for i in range(len(recent) - 1, 0, -1):
        chg = float(recent["close"].iloc[i]) - float(recent["close"].iloc[i - 1])
        if chg > 0 and down_days == 0:
            up_days += 1
        elif chg < 0 and up_days == 0:
            down_days += 1
        else:
            break

    # 支撑/压力位
    recent_low = float(recent["low"].tail(20).min())
    recent_high = float(recent["high"].tail(20).max())
    ma5 = float(_ma(df["close"], 5).iloc[-1]) if len(df) >= 5 else None
    ma10 = float(_ma(df["close"], 10).iloc[-1]) if len(df) >= 10 else None
    ma20 = float(_ma(df["close"], 20).iloc[-1]) if len(df) >= 20 else None

    support = []
    resistance = []
    if ma5:
        support.append({"name": "MA5", "price": round(ma5, 2)})
    if ma10:
        support.append({"name": "MA10", "price": round(ma10, 2)})
    if ma20:
        support.append({"name": "MA20", "price": round(ma20, 2)})
    support.append({"name": "20日低点", "price": round(recent_low, 2)})
    resistance.append({"name": "20日高点", "price": round(recent_high, 2)})

    # RSI
    rsi_val = float(_rsi(df["close"]).iloc[-1]) if len(df) > 14 else None

    # 短线信号
    signals = []
    if rsi_val is not None:
        if rsi_val > 70:
            signals.append(f"RSI={rsi_val:.1f} 超买区域，注意回调风险")
        elif rsi_val < 30:
            signals.append(f"RSI={rsi_val:.1f} 超卖区域，可能反弹")
        else:
            signals.append(f"RSI={rsi_val:.1f} 正常区间")

    if vol_ratio > 1.5:
        signals.append(f"近5日均量是20日的{vol_ratio:.1f}倍，放量明显")
    elif vol_ratio < 0.6:
        signals.append(f"近5日均量萎缩至20日的{vol_ratio:.1f}倍")

    if up_days >= 3:
        signals.append(f"连涨{up_days}天，短期获利盘压力较大")
    if down_days >= 3:
        signals.append(f"连跌{down_days}天，超跌反弹概率增加")

    return {
        "stock_code": stock_code,
        "current_price": round(current_price, 2),
        "returns": {
            "近5日": f"{ret_5d * 100:.2f}%" if ret_5d is not None else "数据不足",
            "近10日": f"{ret_10d * 100:.2f}%" if ret_10d is not None else "数据不足",
            "近20日": f"{ret_20d * 100:.2f}%" if ret_20d is not None else "数据不足",
        },
        "volume_ratio": round(vol_ratio, 2),
        "consecutive": f"连涨{up_days}天" if up_days >= 1 else (f"连跌{down_days}天" if down_days >= 1 else "震荡"),
        "support": support,
        "resistance": resistance,
        "signals": signals,
    }


# —— 3. 买点卖点分析 ——

def find_buy_sell_points(stock_code: str) -> Dict:
    """基于技术指标识别买卖点：金叉/死叉、RSI、布林带、量价关系"""
    df = _load_daily(stock_code, days=400)

    if df.empty:
        return {"error": f"未找到 {stock_code} 的日线数据"}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    signals = []
    current_price = float(close.iloc[-1])

    # MA 金叉/死叉
    ma5 = _ma(close, 5)
    ma20 = _ma(close, 20)
    for i in range(len(df) - 1, 19, -1):
        if ma5.iloc[i] > ma20.iloc[i] and ma5.iloc[i - 1] <= ma20.iloc[i - 1]:
            signals.append({
                "type": "buy", "name": "MA金叉(MA5上穿MA20)",
                "date": df.index[i].strftime("%Y-%m-%d"),
                "price": round(float(close.iloc[i]), 2),
                "desc": "短期均线上穿中期均线"
            })
            break
    for i in range(len(df) - 1, 19, -1):
        if ma5.iloc[i] < ma20.iloc[i] and ma5.iloc[i - 1] >= ma20.iloc[i - 1]:
            signals.append({
                "type": "sell", "name": "MA死叉(MA5下穿MA20)",
                "date": df.index[i].strftime("%Y-%m-%d"),
                "price": round(float(close.iloc[i]), 2),
                "desc": "短期均线下穿中期均线"
            })
            break

    # MACD 金叉/死叉
    dif, dea, bar = _macd(close)
    for i in range(len(df) - 1, 25, -1):
        if dif.iloc[i] > dea.iloc[i] and dif.iloc[i - 1] <= dea.iloc[i - 1]:
            signals.append({
                "type": "buy", "name": "MACD金叉",
                "date": df.index[i].strftime("%Y-%m-%d"),
                "price": round(float(close.iloc[i]), 2),
                "desc": "DIF上穿DEA"
            })
            break
    for i in range(len(df) - 1, 25, -1):
        if dif.iloc[i] < dea.iloc[i] and dif.iloc[i - 1] >= dea.iloc[i - 1]:
            signals.append({
                "type": "sell", "name": "MACD死叉",
                "date": df.index[i].strftime("%Y-%m-%d"),
                "price": round(float(close.iloc[i]), 2),
                "desc": "DIF下穿DEA"
            })
            break

    # RSI
    rsi = _rsi(close)
    last_rsi = float(rsi.iloc[-1])
    if last_rsi > 70:
        rsi_verdict = f"超买(RSI={last_rsi:.1f})"
    elif last_rsi < 30:
        rsi_verdict = f"超卖(RSI={last_rsi:.1f})"
    else:
        rsi_verdict = f"中性(RSI={last_rsi:.1f})"

    # 布林带
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    last_upper = float(bb_upper.iloc[-1])
    last_lower = float(bb_lower.iloc[-1])
    last_mid = float(bb_mid.iloc[-1])
    if current_price > last_upper:
        bb_verdict = f"突破上轨({last_upper:.2f})，短期过热"
    elif current_price < last_lower:
        bb_verdict = f"跌破下轨({last_lower:.2f})，超跌区域"
    else:
        pct = (current_price - last_lower) / (last_upper - last_lower) * 100 if last_upper != last_lower else 50
        bb_verdict = f"带内{pct:.0f}%位置，中轨{last_mid:.2f}"

    # 量价
    vol_ma20 = _ma(volume, 20)
    vol_ratio = float(volume.iloc[-1] / vol_ma20.iloc[-1]) if vol_ma20.iloc[-1] > 0 else 1.0
    price_chg = float(close.pct_change().iloc[-1])
    if vol_ratio > 1.5 and price_chg > 0:
        vol_verdict = "放量上涨，多头强势"
    elif vol_ratio > 1.5 and price_chg < 0:
        vol_verdict = "放量下跌，注意风险"
    elif vol_ratio < 0.5:
        vol_verdict = "缩量，变盘在即"
    else:
        vol_verdict = "量能正常"

    # 综合评分
    buy_score = sum(1 for s in signals if s["type"] == "buy")
    sell_score = sum(1 for s in signals if s["type"] == "sell")
    if last_rsi < 30:
        buy_score += 1
    elif last_rsi > 70:
        sell_score += 1
    if current_price < last_lower:
        buy_score += 1
    elif current_price > last_upper:
        sell_score += 1

    if buy_score > sell_score:
        overall, detail = "偏向买入", f"买入信号{buy_score} vs 卖出信号{sell_score}"
    elif sell_score > buy_score:
        overall, detail = "偏向卖出", f"卖出信号{sell_score} vs 买入信号{buy_score}"
    else:
        overall, detail = "观望", "信号均衡"

    return {
        "stock_code": stock_code,
        "current_price": round(current_price, 2),
        "signals": signals,
        "indicators": {"RSI": rsi_verdict, "布林带": bb_verdict, "量价": vol_verdict},
        "overall": overall,
        "overall_detail": detail,
    }


# —— 4. 历史图形匹配 ——

def find_similar_patterns(stock_code: str, lookback: int = 60, top_n: int = 5) -> Dict:
    """在当前股票历史中查找与最近走势最相似的片段"""
    df = _load_daily(stock_code, days=800)

    if df.empty or len(df) < lookback + 20:
        return {"error": f"数据不足 ({len(df)}天)"}

    close = df["close"]
    ret_series = close.pct_change().dropna()

    if len(ret_series) < lookback:
        return {"error": "数据不足"}

    query = ret_series.iloc[-lookback:].values
    query_norm = (query - query.mean()) / (query.std() + 1e-10)

    # 自匹配
    self_matches = []
    for start in range(0, len(ret_series) - lookback - 5):
        if start + lookback >= len(ret_series) - 5:
            continue
        candidate = ret_series.iloc[start:start + lookback].values
        candidate_norm = (candidate - candidate.mean()) / (candidate.std() + 1e-10)
        corr = np.corrcoef(query_norm, candidate_norm)[0, 1]
        if not np.isnan(corr) and corr > 0.25:
            future = {}
            for n in [5, 10, 20]:
                if start + lookback + n < len(close):
                    fwd = float((close.iloc[start + lookback + n] - close.iloc[start + lookback]) / close.iloc[start + lookback])
                    future[f"{n}日"] = f"{fwd * 100:.2f}%"
            self_matches.append({
                "start": df.index[start].strftime("%Y-%m-%d"),
                "end": df.index[start + lookback].strftime("%Y-%m-%d"),
                "correlation": round(float(corr), 3),
                "future": future,
            })

    self_matches.sort(key=lambda x: x["correlation"], reverse=True)
    top_self = self_matches[:top_n]

    # 跨股票匹配：在全部股票中搜索相似走势
    cross_matches = []
    try:
        conn = _get_db()
        all_codes = pd.read_sql_query(
            "SELECT DISTINCT stock_code FROM daily_bars", conn
        )["stock_code"].tolist()
        conn.close()
        for code in all_codes[:100]:
            if code == stock_code:
                continue
            other = _load_daily(code, days=800)
            if other.empty or len(other) < lookback + 20:
                continue
            other_ret = other["close"].pct_change().dropna()
            if len(other_ret) < lookback:
                continue
            other_recent = other_ret.iloc[-lookback:].values
            other_norm = (other_recent - other_recent.mean()) / (other_recent.std() + 1e-10)
            corr = np.corrcoef(query_norm, other_norm)[0, 1]
            if not np.isnan(corr) and corr > 0.4:
                cross_matches.append({"stock_code": code, "correlation": round(float(corr), 3)})
        cross_matches.sort(key=lambda x: x["correlation"], reverse=True)
    except Exception as e:
        logger.warning("跨股票匹配失败: %s", e)

    # 统计后续平均收益
    avg_future = {}
    for period in ["5日", "10日", "20日"]:
        vals = []
        for m in top_self:
            v = m["future"].get(period)
            if v:
                try:
                    vals.append(float(v.replace("%", "")))
                except (ValueError, TypeError):
                    pass
        if vals:
            avg_future[period] = f"{np.mean(vals):.2f}%"

    total_windows = len(ret_series) - lookback

    return {
        "stock_code": stock_code,
        "lookback_days": lookback,
        "total_windows": total_windows,
        "self_matches": top_self,
        "cross_matches": cross_matches[:top_n],
        "avg_future": avg_future,
        "note": "历史图形相似不保证未来走势相同，仅供参考",
    }
