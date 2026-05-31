"""回测引擎：逐日模拟选股 → 买入 → 止盈止损。"""
from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd

from data_store import DataStore

# ---- 策略参数 ----
TAKE_PROFIT = 0.15
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 30
TOP_N = 10
MAX_POSITIONS = 8
MIN_DAILY_BARS = 70
MAX_RET_5 = 0.15
MAX_RET_20 = 0.40
MAX_VOL_STD = 0.04
LIMIT_UP_MAIN = 9.5
LIMIT_UP_GROWTH = 19.5

# ATR 动态止盈止损参数
ATR_SL_MULT = 2.0       # 止损跟踪 2倍ATR
ATR_TP_MULT = 4.0       # 止盈 = 4倍ATR
ATR_TRAIL_MULT = 2.0    # 盈利超过2倍ATR后启动移动止盈
ATR_TRAIL_BACK = 1.0    # 移动止盈回撤1倍ATR平仓


# ---- 数据结构 ----
@dataclass
class Position:
    code: str
    name: str
    entry_price: float
    entry_date: str
    hold_days: int = 0
    highest_price: float = 0.0
    atr_at_entry: float = 0.0


@dataclass
class Trade:
    code: str
    name: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    exit_reason: str
    hold_days: int


# ---- 技术指标（复制自 stock_selector.py）----
def compute_indicators(daily: pd.DataFrame) -> Optional[dict]:
    if daily is None or daily.empty or "close" not in daily.columns:
        return None
    df = daily.sort_values("trade_date").reset_index(drop=True)
    if len(df) < MIN_DAILY_BARS:
        return None

    closes = df["close"].astype(float).values
    vols = df["volume"].astype(float).values if "volume" in df.columns else None
    if vols is None or len(vols) < MIN_DAILY_BARS:
        return None

    last = float(closes[-1])
    ma5 = float(np.mean(closes[-5:]))
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))

    ret_5 = last / closes[-6] - 1 if len(closes) >= 6 else 0.0
    ret_10 = last / closes[-11] - 1 if len(closes) >= 11 else 0.0
    ret_20 = last / closes[-21] - 1 if len(closes) >= 21 else 0.0
    ret_60 = last / closes[-61] - 1 if len(closes) >= 61 else 0.0

    daily_ret_20 = np.diff(closes[-21:]) / closes[-21:-1]
    vol_std = float(np.std(daily_ret_20))
    peak = np.maximum.accumulate(closes[-20:])
    drawdown = (closes[-20:] / peak) - 1
    max_dd = float(np.min(drawdown))

    avg5 = float(np.mean(vols[-5:]))
    avg20 = float(np.mean(vols[-20:]))
    vol_ratio = avg5 / avg20 if avg20 > 0 else 0.0
    avg_turnover20 = avg20 * np.mean(closes[-20:])

    high60 = float(np.max(closes[-60:]))
    dist_high60 = (high60 - last) / high60 if high60 > 0 else 0.0

    # ATR(14)
    atr14 = 0.0
    if len(closes) >= 15 and "high" in df.columns and "low" in df.columns:
        highs = df["high"].astype(float).values[-15:]
        lows = df["low"].astype(float).values[-15:]
        prev_closes = closes[-15:-1]  # closes[-15] to closes[-2], 14 values for t-1
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - prev_closes),
                np.abs(lows[1:] - prev_closes)
            )
        )
        atr14 = float(np.mean(tr))

    return {
        "last": last, "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ret_5": float(ret_5), "ret_10": float(ret_10),
        "ret_20": float(ret_20), "ret_60": float(ret_60),
        "vol_std": vol_std, "max_dd": max_dd,
        "vol_ratio_5_20": vol_ratio,
        "avg_turnover_20": avg_turnover20,
        "dist_high60": dist_high60,
        "atr14": atr14,
    }


def passes_hard_filter(ind: dict) -> tuple[bool, str]:
    if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]):
        return False, "均线非多头"
    if ind["last"] <= ind["ma60"]:
        return False, "未站上MA60"
    if ind["ret_5"] >= MAX_RET_5:
        return False, "5日过热"
    if ind["ret_20"] >= MAX_RET_20:
        return False, "20日过热"
    if ind["vol_std"] >= MAX_VOL_STD:
        return False, "波动率高"
    return True, ""


def score_dataframe(factors: pd.DataFrame) -> pd.DataFrame:
    """v8 新版打分：Config权重 + 策略引擎 + dd_penalty。
    回测中跳过需要API的因子（板块/北向/股东/基本面），中性处理。"""
    df = factors.copy()

    def zrank(s):
        return s.rank(method="average", pct=True) * 100

    def bell_score(value, low, high):
        half = (high - low) / 2
        center = (low + high) / 2
        dist = (value - center).abs()
        over = (dist - half).clip(lower=0)
        score = 100 * (1 - over / half)
        return score.clip(lower=0, upper=100)

    # ── 六因子 ──
    df["score_ret60"] = zrank(df["ret_60"])
    df["bias_ma20"] = (df["last"] / df["ma20"]) - 1
    df["score_bias"] = zrank(df["bias_ma20"])
    df["trend_strength"] = df["score_ret60"] * 0.64 + df["score_bias"] * 0.36

    df["score_smooth_std"] = zrank(-df["vol_std"])
    df["score_smooth_dd"] = zrank(df["max_dd"])
    df["trend_smooth"] = df["score_smooth_std"] * 0.60 + df["score_smooth_dd"] * 0.40

    df["score_vol"] = bell_score(df["vol_ratio_5_20"], 1.0, 2.0)
    df["volume_factor"] = df["score_vol"]

    df["score_pos"] = bell_score(df["dist_high60"], 0.05, 0.20)
    df["position"] = df["score_pos"]

    df["score_liq"] = zrank(df["avg_turnover_20"])
    df["liquidity"] = df["score_liq"]

    # ── 回测中性值 ──
    df["sector_flow_factor"] = 50.0
    df["individual_flow_score"] = 50.0
    df["northbound_score"] = 50.0
    df["shareholder_bonus"] = 0.0
    df["history_factor"] = 0.0

    # ── 回撤惩罚 ──
    df["dd_penalty"] = df["max_dd"].apply(lambda x: max(0, abs(x) - 0.15) * 200)
    df["dd_penalty"] = df["dd_penalty"].clip(upper=15)

    # ── 多策略命中 ──
    from strategy_engine import StrategyEngine; engine = StrategyEngine()
    strategy_results = []
    for _, row in df.iterrows():
        stock_data = {
            "close": row.get("last", row.get("close", 0)),
            "open": row.get("open", 0),
            "high": row.get("high", 0),
            "low": row.get("low", 0),
            "prev_close": row.get("prev_close", 0),
            "change_pct": row.get("change_percent", 0),
            "ma5": row.get("ma5", 0),
            "ma10": row.get("ma10", 0),
            "ma20": row.get("ma20", 0),
            "ma60": row.get("ma60", 0),
            "ma20_slope": (row.get("ma20", 0) / row.get("ma60", 1) - 1) if row.get("ma60", 0) > 0 else 0,
            "vol_ratio_5_20": row.get("vol_ratio_5_20", 1.0),
            "volume_ratio": row.get("vol_ratio_5_20", 1.0),
            "dist_from_high_60d": row.get("dist_high60", 0),
            "dist_from_high_20d": row.get("dist_high20", row.get("dist_high60", 0)),
            "ret_60": row.get("ret_60", 0),
            "ret_5": row.get("ret_5", 0),
            "ma5_cross_ma10_days": row.get("ma5_cross_ma10_days", 99),
            "macd_golden_cross": row.get("macd_golden_cross", False),
        }
        result = engine.evaluate(stock_data)
        strategy_results.append(result)

    df["strategy_hit_count"] = [r["hit_count"] for r in strategy_results]
    df["strategy_bonus"] = [r["total_bonus"] for r in strategy_results]

    from config import Config
    # ── 总分 ──
    df["total_score"] = (
        df["trend_strength"] * Config.W_TREND +
        df["trend_smooth"] * Config.W_SMOOTH +
        df["volume_factor"] * Config.W_VOLUME +
        df["position"] * Config.W_POSITION +
        df["liquidity"] * Config.W_LIQUIDITY +
        df["history_factor"] * Config.W_HISTORY +
        df["sector_flow_factor"] * Config.W_SECTOR_FLOW +
        df["individual_flow_score"] * Config.W_INDIVIDUAL_FLOW +
        df["northbound_score"] * Config.W_NORTHBOUND +
        df["shareholder_bonus"] +
        df["strategy_bonus"] * Config.W_STRATEGY -
        df["dd_penalty"]
    )
    return df


# ---- 回测主引擎 ----
class BacktestEngine:
    def __init__(self, store: DataStore,
                 take_profit: float = TAKE_PROFIT,
                 stop_loss: float = STOP_LOSS,
                 max_hold: int = MAX_HOLD_DAYS,
                 top_n: int = TOP_N,
                 max_positions: int = MAX_POSITIONS,
                 no_chase_pct: float = 0,
                 min_dist_high: float = 0,
                 use_market_filter: bool = True,
                 use_atr_stop: bool = True,
                 atr_mult: float = ATR_SL_MULT,
                 atr_tp_mult: float = ATR_TP_MULT,
                 atr_trail_mult: float = ATR_TRAIL_MULT,
                 atr_trail_back: float = ATR_TRAIL_BACK,
                 max_per_sector: int = 2,
                 trailing_stop: float = 0.0):
        self.store = store
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.max_hold = max_hold
        self.top_n = top_n
        self.max_positions = max_positions
        self.no_chase_pct = no_chase_pct
        self.min_dist_high = min_dist_high
        self.use_market_filter = use_market_filter
        self.use_atr_stop = use_atr_stop
        self.atr_mult = atr_mult
        self.atr_tp_mult = atr_tp_mult
        self.atr_trail_mult = atr_trail_mult
        self.atr_trail_back = atr_trail_back
        self.max_per_sector = max_per_sector
        self.trailing_stop = trailing_stop
        self.positions: list[Position] = []
        self.trades: list[Trade] = []
        self.daily_equity: list[tuple[str, float]] = []  # (date, equity_pct)

    def _is_bull_market(self, today: str) -> bool:
        """Check market regime: only trade when trend is clear (not sideways)."""
        if not self.use_market_filter:
            return True
        idx_df = self.store.get_index_daily("2000-01-01", today)
        if idx_df.empty or len(idx_df) < 60:
            return True
        closes = idx_df["close"].astype(float).values
        ma60 = float(np.mean(closes[-60:]))
        current = closes[-1]
        
        # 必须在 MA60 上方
        if current <= ma60:
            return False
        
        # 震荡市检测：近20日振幅 < 5% 且 价格在MA60±3%内 → 横盘不交易
        recent20 = closes[-20:]
        range20 = (np.max(recent20) - np.min(recent20)) / np.mean(recent20)
        deviation = abs(current - ma60) / ma60
        if range20 < 0.05 and deviation < 0.03:
            return False  # 窄幅震荡，不交易
        
        return True

    def run(self, start_date: str, end_date: str) -> list[Trade]:
        trade_dates = self.store.get_trade_dates(start_date, end_date)
        if len(trade_dates) < 2:
            print("交易日不足，无法回测")
            return []

        print(f"  回测区间: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)} 个交易日)")
        if self.use_atr_stop:
            print(f"  参数: ATR动态止盈止损 (SL={self.atr_mult}x, TP={self.atr_tp_mult}x, Trail={self.atr_trail_mult}x/{self.atr_trail_back}x) / 最长 {self.max_hold} 天")
        else:
            print(f"  参数: 固定止盈 {self.take_profit*100:.0f}% / 止损 {self.stop_loss*100:.0f}% / 最长 {self.max_hold} 天")
        print()

        for i, today in enumerate(trade_dates):
            # 1. 检查持仓是否触发平仓
            self._check_exits(today)

            # 2. 如果持仓未满 + 市场环境允许（牛市），选股并在"次日"开盘买入
            market_ok = self._is_bull_market(today)
            if i + 1 < len(trade_dates) and len(self.positions) < self.max_positions and market_ok:
                next_day = trade_dates[i + 1]
                picks = self._select_stocks(today)
                slots = self.max_positions - len(self.positions)
                for pick in picks[:slots]:
                    bar = self.store.get_bar(pick["stock_code"], next_day)
                    if bar and bar["open"] and bar["open"] > 0:
                        # 不追高开超5%的
                        ref_close = pick["last"]
                        if bar["open"] > ref_close * 1.05:
                            continue
                        # 记录入场时ATR
                        daily = self.store.get_daily(pick["stock_code"], today, days=120)
                        entry_atr = self._calc_atr(daily)
                        self.positions.append(Position(
                            code=pick["stock_code"],
                            name=pick.get("stock_name", ""),
                            entry_price=bar["open"],
                            entry_date=next_day,
                            highest_price=bar["open"],
                            atr_at_entry=entry_atr,
                        ))

            # 3. 更新持有天数
            for pos in self.positions:
                pos.hold_days += 1

            # 4. 记录当日权益
            equity = self._calc_equity(today)
            self.daily_equity.append((today, equity))

            if (i + 1) % 20 == 0:
                wins = sum(1 for t in self.trades if t.return_pct > 0)
                total = len(self.trades)
                wr = wins / total * 100 if total > 0 else 0
                print(f"  {today} | 持仓 {len(self.positions)} | 已平仓 {total} | 胜率 {wr:.1f}%")

        # 回测结束，强制平掉所有持仓
        last_date = trade_dates[-1]
        for pos in list(self.positions):
            bar = self.store.get_bar(pos.code, last_date)
            if bar and bar["close"]:
                self._close_position(pos, bar["close"], last_date, "回测结束")
        self.positions.clear()

        return self.trades

    def _check_exits(self, today: str):
        to_remove = []
        for pos in self.positions:
            bar = self.store.get_bar(pos.code, today)
            if not bar or not bar["close"]:
                continue

            # 更新最高价（用于移动止盈）
            if bar["high"] and bar["high"] > pos.highest_price:
                pos.highest_price = bar["high"]

            entry = pos.entry_price
            atr = pos.atr_at_entry

            # 计算动态止盈止损线
            if self.use_atr_stop and atr > 0:
                atr_pct = atr / entry
                tp_pct = self.atr_tp_mult * atr_pct
                sl_pct = self.atr_mult * atr_pct
                # 限制范围：止盈 8%~25%，止损 3%~8%
                tp_pct = max(0.08, min(0.25, tp_pct))
                sl_pct = max(0.03, min(0.08, sl_pct))
            else:
                tp_pct = self.take_profit
                sl_pct = abs(self.stop_loss)

            # 1. 止盈：最高价触及止盈线
            if bar["high"] and bar["high"] / entry - 1 >= tp_pct:
                exit_price = entry * (1 + tp_pct)
                self._close_position(pos, exit_price, today, "止盈")
                to_remove.append(pos)
                continue

            # 2. 移动止盈：盈利超过 trail_mult*ATR 后，从最高点回撤 trail_back*ATR 就平仓
            if self.use_atr_stop and atr > 0:
                trail_trigger = self.atr_trail_mult * atr
                if pos.highest_price - entry >= trail_trigger:
                    trail_stop_price = pos.highest_price - self.atr_trail_back * atr
                    if bar["low"] and bar["low"] <= trail_stop_price:
                        exit_price = max(trail_stop_price, entry)
                        self._close_position(pos, exit_price, today, "移动止盈")
                        to_remove.append(pos)
                        continue

            # 3. 止损
            if bar["low"] and bar["low"] / entry - 1 <= -sl_pct:
                exit_price = entry * (1 - sl_pct)
                self._close_position(pos, exit_price, today, "止损")
                to_remove.append(pos)
                continue

            # 4. 超时
            if pos.hold_days >= self.max_hold:
                self._close_position(pos, bar["close"], today, "超时")
                to_remove.append(pos)
                continue

        for pos in to_remove:
            self.positions.remove(pos)

    def _close_position(self, pos: Position, exit_price: float, exit_date: str, reason: str):
        ret = exit_price / pos.entry_price - 1
        self.trades.append(Trade(
            code=pos.code, name=pos.name,
            entry_date=pos.entry_date, entry_price=pos.entry_price,
            exit_date=exit_date, exit_price=exit_price,
            return_pct=ret, exit_reason=reason, hold_days=pos.hold_days,
        ))

    def _select_stocks(self, today: str) -> list[dict]:
        """在 today 这天执行选股逻辑。"""
        spot = self.store.get_spot_on_date(today)
        if spot.empty:
            return []

        # 初筛
        df = spot.copy()
        df = df[df["close"] > 0]
        df = df[df["turnover"] >= 1e8]
        # 去ST
        df = df[~df["stock_name"].str.contains("ST|退", case=False, na=False)]
        # 去涨停
        is_growth = df["stock_code"].str.startswith("30")
        limit = np.where(is_growth, LIMIT_UP_GROWTH, LIMIT_UP_MAIN)
        df = df[df["change_percent"] < limit]
        # 今日涨幅 > 7% 不追（可选）
        if self.no_chase_pct > 0:
            df = df[df["change_percent"] <= self.no_chase_pct]
        # 已持仓的不重复买
        held_codes = {p.code for p in self.positions}
        df = df[~df["stock_code"].isin(held_codes)]

        if df.empty:
            return []

        # 按成交额取前200
        df = df.sort_values("turnover", ascending=False).head(200)

        # 计算指标 + 硬过滤
        rows = []
        for _, row in df.iterrows():
            code = row["stock_code"]
            daily = self.store.get_daily(code, today, days=120)
            ind = compute_indicators(daily)
            if ind is None:
                continue
            ok, _ = passes_hard_filter(ind)
            if not ok:
                continue
            # 主力资金过滤：近5日主力净流入必须为正
            mf_data = self.store.get_moneyflow(code, today, days=5)
            mf_ratio_5 = 0.0
            if mf_data is not None and len(mf_data) > 0:
                mf_5d = mf_data["net_mf_amount"].sum()
                if mf_5d < 0:
                    continue  # 主力在卖，跳过
                mf_ratio_5 = float(mf_5d / (ind["avg_turnover_20"] * 5 + 1))
            # 距高点 < min_dist_high 不买（可选）
            if self.min_dist_high > 0 and ind["dist_high60"] < self.min_dist_high:
                continue
            # 需要 OHLC 给策略引擎
            spot_open = row.get("open", 0) if hasattr(row, "get") and "open" in row.index else 0
            spot_high = row.get("high", 0) if hasattr(row, "get") and "high" in row.index else 0
            spot_low = row.get("low", 0) if hasattr(row, "get") and "low" in row.index else 0
            spot_prev = row.get("prev_close", 0) if hasattr(row, "get") and "prev_close" in row.index else 0
            spot_chg = row.get("change_percent", 0) if hasattr(row, "get") and "change_percent" in row.index else 0
            rows.append({
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "open": spot_open,
                "high": spot_high,
                "low": spot_low,
                "prev_close": spot_prev,
                "change_percent": spot_chg,
                "mf_ratio_5": mf_ratio_5,
                **ind,
            })

        if not rows:
            return []

        # 打分
        factors = pd.DataFrame(rows)
        scored = score_dataframe(factors)
        scored = scored.sort_values("total_score", ascending=False)

        # 板块分散：同行业最多 max_per_sector 只（从 stock_info_new 取行业）
        if self.max_per_sector > 0:
            sector_counts: dict[str, int] = {}
            # 先统计已持仓的行业分布
            for pos in self.positions:
                ind = self.store.get_industry(pos.code) or "其他"
                sector_counts[ind] = sector_counts.get(ind, 0) + 1
            diversified = []
            for _, row in scored.iterrows():
                code = str(row["stock_code"])
                ind = self.store.get_industry(code) or "其他"
                if sector_counts.get(ind, 0) < self.max_per_sector:
                    diversified.append(row.to_dict())
                    sector_counts[ind] = sector_counts.get(ind, 0) + 1
                if len(diversified) >= self.top_n:
                    break
            return diversified

        return scored.head(self.top_n).to_dict("records")

    def _calc_atr(self, daily) -> float:
        """Calculate ATR(14) from daily DataFrame."""
        if daily is None or daily.empty or len(daily) < 15:
            return 0.0
        closes = daily["close"].astype(float).values[-15:]
        highs = daily["high"].astype(float).values[-15:] if "high" in daily.columns else closes
        lows = daily["low"].astype(float).values[-15:] if "low" in daily.columns else closes
        prev_closes = daily["close"].astype(float).values[-15:-1]
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - prev_closes),
                np.abs(lows[1:] - prev_closes)
            )
        )
        return float(np.mean(tr))

    def _calc_equity(self, today: str) -> float:
        """计算当日持仓的平均收益率。"""
        if not self.positions:
            return 0.0
        total_ret = 0.0
        count = 0
        for pos in self.positions:
            bar = self.store.get_bar(pos.code, today)
            if bar and bar["close"]:
                total_ret += bar["close"] / pos.entry_price - 1
                count += 1
        return total_ret / count if count > 0 else 0.0
