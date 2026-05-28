"""量化选股引擎：中长期稳健趋势策略。

设计目标：选 10-30 个交易日为持有周期的、走势平稳向上的票，避开短线妖股。

打分组成（满分 100）：
    - 趋势强度  30%   60 日涨幅 + 当前价/MA20 偏离度
    - 趋势平滑  25%   20 日最大回撤 + 20 日日收益率 std
    - 量能配合  20%   5/20 量比落在温和放量区间
    - 位置因子  15%   离 60 日高点的距离（不太近也不太远）
    - 流动性    10%   日均成交额排名

打分前的硬过滤会先把妖股 / 熊股 / 涨停板 / 小盘股全部踢掉。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.data_fetcher import DataFetcher, get_default_fetcher
from app.utils import get_logger

logger = get_logger(__name__)


_DAILY_FETCH_WORKERS = 12

# ---- 硬过滤阈值（中长期稳健，与 run_select.py 保持一致）----
MIN_FLOAT_MCAP = 5e9          # 流通市值 >= 50 亿
MAX_RET_5 = 0.10              # 5 日累计涨幅 < 10%
MAX_RET_20 = 0.30             # 20 日累计涨幅 < 30%
MAX_VOL_STD = 0.04            # 20 日日收益率 std < 4%
LIMIT_UP_MAIN = 0.095         # 主板涨停判定 9.5%
LIMIT_UP_GROWTH = 0.195       # 创业板/科创板涨停判定 19.5%
MIN_DAILY_BARS = 70           # 上市/数据 >= 70 个交易日（覆盖 60 日均线）


def _is_growth_board(code: str) -> bool:
    """30 开头创业板，68 开头科创板（已被前面过滤掉但保留判定）。"""
    return str(code).startswith(("30", "68"))


class StockSelector:
    """中长期稳健趋势选股。"""

    def __init__(self, fetcher: Optional[DataFetcher] = None, min_volume: float = 1e8):
        self.fetcher = fetcher or get_default_fetcher()
        self.min_volume = min_volume

    # ==================================================================
    # 一、初筛（基于 spot 表，便宜的过滤）
    # ==================================================================
    def _prefilter(self, spot: pd.DataFrame) -> pd.DataFrame:
        df = spot.copy()
        # 排除 ST / 退市
        if "stock_name" in df.columns:
            names = df["stock_name"].astype(str)
            df = df[~names.str.contains("ST", case=False, na=False)]
            df = df[~names.str.contains("退", na=False)]

        # 只保留沪深主板 + 创业板，剔除科创板 / 北交所
        if "stock_code" in df.columns:
            code = df["stock_code"].astype(str)
            keep = (
                code.str.startswith(("60", "00", "30"))
                & ~code.str.startswith("688")
                & ~code.str.startswith("8")
                & ~code.str.startswith("4")
            )
            df = df[keep]

        # 价格 > 0
        if "current_price" in df.columns:
            df = df[df["current_price"].fillna(0) > 0]

        # 成交额 >= 1 亿（基础流动性）
        if "turnover" in df.columns:
            df = df[df["turnover"].fillna(0) >= self.min_volume]

        # 流通市值 >= 50 亿
        if "float_market_cap" in df.columns:
            df = df[df["float_market_cap"].fillna(0) >= MIN_FLOAT_MCAP]

        # 当日不能涨停（主板 9.5%，创业板 19.5%）
        if "change_percent" in df.columns:
            cp = pd.to_numeric(df["change_percent"], errors="coerce").fillna(0) / 100.0
            code = df["stock_code"].astype(str)
            growth = code.str.startswith("30")
            df = df[~((growth & (cp >= LIMIT_UP_GROWTH)) | (~growth & (cp >= LIMIT_UP_MAIN)))]

        return df.reset_index(drop=True)

    # ==================================================================
    # 二、技术指标（基于日线，贵）
    # ==================================================================
    @staticmethod
    def _compute_indicators(daily: pd.DataFrame) -> Optional[Dict[str, float]]:
        """一次性算出所有需要的技术指标，返回 None 表示数据不足。"""
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

        # 均线
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:]))

        # 区间收益
        ret_5 = last / closes[-6] - 1 if len(closes) >= 6 else 0.0
        ret_10 = last / closes[-11] - 1 if len(closes) >= 11 else 0.0
        ret_20 = last / closes[-21] - 1 if len(closes) >= 21 else 0.0
        ret_60 = last / closes[-61] - 1 if len(closes) >= 61 else 0.0

        # 平滑度：20 日日收益率 std + 20 日最大回撤
        daily_ret_20 = np.diff(closes[-21:]) / closes[-21:-1]
        vol_std = float(np.std(daily_ret_20))
        peak = np.maximum.accumulate(closes[-20:])
        drawdown = (closes[-20:] / peak) - 1
        max_dd = float(np.min(drawdown))  # 负数，越小代表回撤越深

        # 量能
        avg5 = float(np.mean(vols[-5:]))
        avg20 = float(np.mean(vols[-20:]))
        vol_ratio = avg5 / avg20 if avg20 > 0 else 0.0
        avg_turnover20 = avg20 * np.mean(closes[-20:])  # 近似日均成交额

        # 位置
        high60 = float(np.max(closes[-60:]))
        dist_high60 = (high60 - last) / high60 if high60 > 0 else 0.0  # 离60日高点的下降幅度，0 表示就在高点

        return {
            "last": last,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "ret_5": float(ret_5), "ret_10": float(ret_10),
            "ret_20": float(ret_20), "ret_60": float(ret_60),
            "vol_std": vol_std,
            "max_dd": max_dd,
            "vol_ratio_5_20": vol_ratio,
            "avg_turnover_20": avg_turnover20,
            "dist_high60": dist_high60,
        }

    # ==================================================================
    # 三、硬过滤（基于日线指标）
    # ==================================================================
    @staticmethod
    def _passes_hard_filter(ind: Dict[str, float]) -> tuple[bool, str]:
        """返回 (是否通过, 失败原因)。"""
        # 均线多头排列
        if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]):
            return False, "均线非多头排列"
        # 站在年线之上
        if ind["last"] <= ind["ma60"]:
            return False, "未站上 MA60"
        # 涨幅过热
        if ind["ret_5"] >= MAX_RET_5:
            return False, f"5日涨幅过热 {ind['ret_5']*100:.1f}%"
        if ind["ret_20"] >= MAX_RET_20:
            return False, f"20日涨幅过热 {ind['ret_20']*100:.1f}%"
        # 波动率过高
        if ind["vol_std"] >= MAX_VOL_STD:
            return False, f"波动率过高 std={ind['vol_std']*100:.1f}%"
        return True, ""

    # ==================================================================
    # 四、打分
    # ==================================================================
    @staticmethod
    def _zrank(series: pd.Series) -> pd.Series:
        """rank 归一化到 0-100。"""
        return series.rank(method="average", pct=True) * 100

    @staticmethod
    def _bell_score(value: pd.Series, low: float, high: float) -> pd.Series:
        """value 在 [low, high] 区间得满分 100，离开区间线性衰减。"""
        half = (high - low) / 2
        center = (low + high) / 2
        dist = (value - center).abs()
        over = (dist - half).clip(lower=0)  # 超出区间的部分
        score = 100 * (1 - over / half)
        return score.clip(lower=0, upper=100)

    def _score_dataframe(self, factors: pd.DataFrame) -> pd.DataFrame:
        df = factors.copy()

        # ---- 趋势强度 30 ----
        df["score_ret60"] = self._zrank(df["ret_60"])
        df["bias_ma20"] = (df["last"] / df["ma20"]) - 1  # 高于 MA20 多少
        df["score_bias"] = self._zrank(df["bias_ma20"])
        df["trend_strength"] = df["score_ret60"] * 0.18 + df["score_bias"] * 0.12

        # ---- 趋势平滑度 25（std 越小越好，max_dd 越浅越好）----
        df["score_smooth_std"] = self._zrank(-df["vol_std"])  # 取负 → 小者得高分
        df["score_smooth_dd"] = self._zrank(df["max_dd"])     # max_dd 是负数，越小越坏 → 直接 rank
        df["trend_smooth"] = df["score_smooth_std"] * 0.15 + df["score_smooth_dd"] * 0.10

        # ---- 量能配合 20（温和放量 1.0~2.0 最优）----
        df["score_vol"] = self._bell_score(df["vol_ratio_5_20"], 1.0, 2.0)
        df["volume_factor"] = df["score_vol"] * 0.20

        # ---- 位置 15（离 60 日高点 5%~15% 最优，太近=高位接盘 太远=尚未确认趋势）----
        df["score_pos"] = self._bell_score(df["dist_high60"], 0.05, 0.15)
        df["position"] = df["score_pos"] * 0.15

        # ---- 流动性 10 ----
        df["score_liq"] = self._zrank(df["avg_turnover_20"])
        df["liquidity"] = df["score_liq"] * 0.10

        df["total_score"] = (
            df["trend_strength"]
            + df["trend_smooth"]
            + df["volume_factor"]
            + df["position"]
            + df["liquidity"]
        )
        return df

    # ==================================================================
    # 五、单股分析（用户输入代码 → 体检 + 打分 + 结论）
    # ==================================================================
    def _spot_lookup(self, code: str) -> Optional[pd.Series]:
        """从 spot 表里找一行；找不到（或 spot 拉取失败）返回 None。"""
        try:
            spot = self.fetcher.get_stock_spot()
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_stock_spot 失败：%s", exc)
            return None
        if spot is None or spot.empty or "stock_code" not in spot.columns:
            return None
        spot = spot.copy()
        spot["stock_code"] = spot["stock_code"].astype(str).str.zfill(6)
        hit = spot[spot["stock_code"] == code]
        return hit.iloc[0] if not hit.empty else None

    def analyze_single(self, stock_code: str) -> Dict:
        """对单只票做硬过滤体检 + 综合打分 + 结论。

        返回结构：
            {
              "stock_code", "stock_name", "current_price",
              "indicators": {...原始技术指标...},
              "checks": [{"name", "passed", "detail"}, ...],   # 硬过滤逐条
              "score": {"total", "trend_strength", ...},        # 五因子绝对分（无横向排名）
              "verdict": "强烈推荐|可买入|观望|不建议|风险警示",
              "verdict_reason": "结论的一句话解释",
              "warnings": [...]                                 # 风险提示
            }

        说明：单股分析没有"全市场排名"，因子分数用 0-100 区间的近似映射（基于
        合理阈值），不是 zrank。这点和批量选股不同。
        """
        code = str(stock_code).strip().zfill(6)

        # 1) 拉 spot；失败或缺该股 → 走"日线降级模式"（仅靠日线分析，部分指标缺失）
        spot_row = self._spot_lookup(code)
        spot_degraded = spot_row is None

        if spot_degraded:
            stock_name = ""
            current_price = 0.0
            change_percent = 0.0
            float_mcap = 0.0
            turnover_today = 0.0
        else:
            stock_name = str(spot_row.get("stock_name", ""))
            current_price = float(spot_row.get("current_price") or 0)
            change_percent = float(spot_row.get("change_percent") or 0) / 100.0
            float_mcap = float(spot_row.get("float_market_cap") or 0)
            turnover_today = float(spot_row.get("turnover") or 0)

        # 2) 拉日线（必须成功，否则没法分析）
        try:
            daily = self.fetcher.get_recent_daily(code, days=120)
        except Exception as exc:  # noqa: BLE001
            return {"stock_code": code, "stock_name": stock_name,
                    "error": f"拉取日线失败：{exc}"}

        ind = self._compute_indicators(daily)
        if ind is None:
            return {"stock_code": code, "stock_name": stock_name,
                    "error": "日线数据不足（次新股或停牌时间过长）"}

        # 降级模式：用日线最新收盘价兜底当作"现价"
        if spot_degraded:
            current_price = round(ind["last"], 2)

        # 3) 硬过滤逐条体检
        checks: List[Dict] = []

        # 板块判定
        is_main_or_growth = code.startswith(("60", "00", "30")) and not code.startswith("688")
        is_kechuang_or_bj = code.startswith(("688", "8", "4"))
        is_st = "ST" in stock_name.upper() or "退" in stock_name

        checks.append({
            "name": "非 ST / 退市",
            "passed": not is_st,
            "detail": f"股票名 {stock_name}",
        })
        checks.append({
            "name": "主板/创业板",
            "passed": is_main_or_growth and not is_kechuang_or_bj,
            "detail": "科创板/北交所不在策略覆盖范围" if is_kechuang_or_bj else "主板或创业板",
        })

        # 涨停（spot 不可用时跳过这条）
        is_growth = code.startswith("30")
        limit_threshold = LIMIT_UP_GROWTH if is_growth else LIMIT_UP_MAIN
        if spot_degraded:
            checks.append({
                "name": "未涨停",
                "passed": True,  # 没数据，按通过算（不阻挡判断）
                "detail": "实时行情暂不可用，无法判断今日是否涨停",
            })
        else:
            is_limit_up = change_percent >= limit_threshold
            checks.append({
                "name": "未涨停",
                "passed": not is_limit_up,
                "detail": f"今日涨幅 {change_percent*100:+.2f}%（涨停阈值 {limit_threshold*100:.1f}%）",
            })

        # 流通市值（spot 不可用时跳过这条）
        if spot_degraded:
            checks.append({
                "name": f"流通市值 ≥ {MIN_FLOAT_MCAP/1e8:.0f} 亿",
                "passed": True,
                "detail": "实时行情暂不可用，无法获取流通市值",
            })
        else:
            checks.append({
                "name": f"流通市值 ≥ {MIN_FLOAT_MCAP/1e8:.0f} 亿",
                "passed": float_mcap >= MIN_FLOAT_MCAP,
                "detail": f"流通市值 {float_mcap/1e8:.1f} 亿" if float_mcap > 0 else "流通市值数据缺失",
            })

        # 均线多头
        ma_bullish = ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]
        checks.append({
            "name": "均线多头排列",
            "passed": ma_bullish,
            "detail": (
                f"MA5 {ind['ma5']:.2f} > MA10 {ind['ma10']:.2f} > "
                f"MA20 {ind['ma20']:.2f} > MA60 {ind['ma60']:.2f}"
                if ma_bullish else
                f"MA5 {ind['ma5']:.2f} / MA10 {ind['ma10']:.2f} / "
                f"MA20 {ind['ma20']:.2f} / MA60 {ind['ma60']:.2f}（顺序错乱）"
            ),
        })

        # 站上 MA60
        above_ma60 = ind["last"] > ind["ma60"]
        checks.append({
            "name": "站上 MA60（年线）",
            "passed": above_ma60,
            "detail": f"现价 {ind['last']:.2f} vs MA60 {ind['ma60']:.2f}（"
                      f"{(ind['last']/ind['ma60']-1)*100:+.1f}%）",
        })

        # 5 日不过热
        ret5_ok = ind["ret_5"] < MAX_RET_5
        checks.append({
            "name": f"5日涨幅 < {MAX_RET_5*100:.0f}%",
            "passed": ret5_ok,
            "detail": f"5日涨幅 {ind['ret_5']*100:+.2f}%",
        })

        # 20 日不过热
        ret20_ok = ind["ret_20"] < MAX_RET_20
        checks.append({
            "name": f"20日涨幅 < {MAX_RET_20*100:.0f}%",
            "passed": ret20_ok,
            "detail": f"20日涨幅 {ind['ret_20']*100:+.2f}%",
        })

        # 波动率
        vol_ok = ind["vol_std"] < MAX_VOL_STD
        checks.append({
            "name": f"20日波动率 < {MAX_VOL_STD*100:.0f}%",
            "passed": vol_ok,
            "detail": f"日收益率 std {ind['vol_std']*100:.2f}%",
        })

        passed_count = sum(1 for c in checks if c["passed"])
        total_count = len(checks)

        # 4) 五因子绝对打分（基于阈值映射，不依赖全市场排名）
        # 趋势强度（30 分）：60 日涨幅 + 偏离 MA20
        ret60_score = max(0.0, min(1.0, ind["ret_60"] / 0.30)) * 18  # 60日涨 30%=满分
        bias = ind["last"] / ind["ma20"] - 1
        bias_score = max(0.0, min(1.0, bias / 0.10)) * 12  # 偏离 MA20 10% = 满分
        trend_strength = ret60_score + bias_score

        # 趋势平滑（25 分）：std 越小越好（<2% 满分），回撤越浅越好（>-3% 满分）
        std_score = max(0.0, min(1.0, (MAX_VOL_STD - ind["vol_std"]) / 0.02)) * 15
        dd_score = max(0.0, min(1.0, (ind["max_dd"] + 0.10) / 0.07)) * 10  # -10% 到 -3% 线性
        trend_smooth = std_score + dd_score

        # 量能（20 分）：钟形，1.0~2.0 满分
        vr = ind["vol_ratio_5_20"]
        if 1.0 <= vr <= 2.0:
            vol_score = 1.0
        elif vr < 1.0:
            vol_score = max(0.0, vr / 1.0)
        else:
            vol_score = max(0.0, 1.0 - (vr - 2.0) / 2.0)
        volume_factor = vol_score * 20

        # 位置（15 分）：钟形，距高点 5%~15% 满分
        d = ind["dist_high60"]
        if 0.05 <= d <= 0.15:
            pos_score = 1.0
        elif d < 0.05:
            pos_score = max(0.0, d / 0.05)
        else:
            pos_score = max(0.0, 1.0 - (d - 0.15) / 0.20)
        position = pos_score * 15

        # 流动性（10 分）：日均成交额 > 5 亿满分
        liq_score = min(1.0, ind["avg_turnover_20"] / 5e8)
        liquidity = liq_score * 10

        total = trend_strength + trend_smooth + volume_factor + position + liquidity

        score = {
            "total": round(total, 1),
            "trend_strength": round(trend_strength, 1),
            "trend_smooth": round(trend_smooth, 1),
            "volume_factor": round(volume_factor, 1),
            "position": round(position, 1),
            "liquidity": round(liquidity, 1),
        }

        # 5) 给结论
        critical_failed = [
            c for c in checks
            if not c["passed"] and c["name"] in ("均线多头排列", "站上 MA60（年线）",
                                                  "非 ST / 退市", "主板/创业板", "未涨停")
        ]
        verdict, verdict_reason = self._make_verdict(
            passed=passed_count, total=total_count,
            score_total=total, critical_failed=critical_failed, ind=ind,
        )

        warnings: List[str] = []
        if ind["ret_5"] >= 0.10:
            warnings.append(f"近 5 日已涨 {ind['ret_5']*100:.1f}%，短期追高风险")
        if ind["vol_std"] >= 0.035:
            warnings.append(f"波动率偏高（std {ind['vol_std']*100:.2f}%），回撤可能较深")
        if ind["dist_high60"] < 0.02:
            warnings.append(f"距 60 日高点仅 {ind['dist_high60']*100:.1f}%，处于高位")
        if float_mcap < 5e9 and float_mcap > 0:
            warnings.append(f"流通市值 {float_mcap/1e8:.1f} 亿，小盘股流动性和波动风险大")

        return {
            "stock_code": code,
            "stock_name": stock_name,
            "current_price": round(current_price, 2),
            "change_percent": round(change_percent, 4),
            "float_market_cap": float_mcap,
            "turnover_today": turnover_today,
            "spot_degraded": spot_degraded,
            "indicators": {
                "ma5": round(ind["ma5"], 2), "ma10": round(ind["ma10"], 2),
                "ma20": round(ind["ma20"], 2), "ma60": round(ind["ma60"], 2),
                "ret_5": round(ind["ret_5"] * 100, 2),
                "ret_20": round(ind["ret_20"] * 100, 2),
                "ret_60": round(ind["ret_60"] * 100, 2),
                "vol_std": round(ind["vol_std"] * 100, 2),
                "max_dd_20": round(ind["max_dd"] * 100, 2),
                "vol_ratio_5_20": round(ind["vol_ratio_5_20"], 2),
                "dist_high60": round(ind["dist_high60"] * 100, 2),
                "avg_turnover_20": ind["avg_turnover_20"],
            },
            "checks": checks,
            "passed_count": passed_count,
            "total_count": total_count,
            "score": score,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "warnings": warnings,
        }

    @staticmethod
    def _make_verdict(passed: int, total: int, score_total: float,
                      critical_failed: List[Dict], ind: Dict) -> tuple[str, str]:
        """五档结论。"""
        # 关键项不过 -> 风险警示 / 不建议
        if critical_failed:
            names = "、".join(c["name"] for c in critical_failed)
            if any(c["name"] in ("非 ST / 退市", "主板/创业板") for c in critical_failed):
                return "风险警示", f"硬性条件不通过：{names}"
            if any(c["name"] == "未涨停" for c in critical_failed):
                return "不建议", "今日已涨停，次日大概率高开低走，不建议追"
            # 趋势条件不过
            return "不建议", f"趋势条件不通过：{names}"

        # 全过 + 高分
        if passed == total and score_total >= 70:
            return "强烈推荐", f"硬过滤全部通过，综合分 {score_total:.1f}，达到系统选股标准"
        # 全过 + 中分
        if passed == total and score_total >= 50:
            return "可买入", f"硬过滤全部通过，综合分 {score_total:.1f}，趋势在但强度一般"
        if passed == total:
            return "观望", f"硬过滤全部通过但综合分较低（{score_total:.1f}），"\
                          "可能是流动性差或位置不佳"
        # 漏 1-2 条非关键项
        if total - passed <= 2 and score_total >= 60:
            return "观望", f"有 {total-passed} 条非关键项未过，但其余表现不错"
        # 漏多条
        return "不建议", f"未通过 {total-passed} 项体检，建议另寻他票"

    # ==================================================================
    # 六、批量选股主入口
    # ==================================================================

    def _check_market_regime(self) -> bool:
        """Check if CSI 300 is above MA60."""
        from config import Config
        if not Config.MARKET_FILTER:
            return True
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if df is None or df.empty or len(df) < Config.INDEX_MA_PERIOD:
                return True
            import numpy as np
            closes = df["close"].astype(float).values
            ma = float(np.mean(closes[-Config.INDEX_MA_PERIOD:]))
            return closes[-1] > ma
        except Exception:
            return True

    def select_stocks(
        self,
        top_n: int = 10,
        candidate_limit: int = 400,
        as_of: Optional[date] = None,
    ) -> List[Dict]:
        as_of = as_of or date.today()
        
        # Market regime filter
        if not self._check_market_regime():
            logger.info("Market below MA60, skipping selection")
            return []
        
        spot = self.fetcher.get_stock_spot()
        if spot.empty:
            logger.error("A 股实时行情为空，无法选股")
            return []

        candidates = self._prefilter(spot)
        if candidates.empty:
            logger.warning("初筛后没有候选股票")
            return []

        # 按成交额取 top N 缩小拉日线的范围
        if "turnover" in candidates.columns:
            candidates = candidates.sort_values("turnover", ascending=False)
        candidates = candidates.head(candidate_limit).reset_index(drop=True)

        logger.info(
            "初筛后候选 %d 只（市值≥50亿 + 非ST + 非涨停），并发拉日线 (workers=%d)",
            len(candidates), _DAILY_FETCH_WORKERS,
        )

        candidate_records = candidates.to_dict("records")

        def _load_daily(rec_row: dict) -> tuple[str, dict, pd.DataFrame]:
            code = rec_row["stock_code"]
            try:
                df = self.fetcher.get_recent_daily(code, days=120)
            except Exception as exc:  # noqa: BLE001
                logger.warning("拉取日线失败 %s: %s", code, exc)
                df = pd.DataFrame()
            return code, rec_row, df

        rows: List[Dict] = []
        rejected: Dict[str, int] = {}
        processed = 0
        with ThreadPoolExecutor(max_workers=_DAILY_FETCH_WORKERS) as pool:
            futures = [pool.submit(_load_daily, r) for r in candidate_records]
            for fut in as_completed(futures):
                processed += 1
                code, rec_row, daily = fut.result()
                ind = self._compute_indicators(daily)
                if ind is None:
                    rejected["数据不足"] = rejected.get("数据不足", 0) + 1
                    continue
                ok, reason = self._passes_hard_filter(ind)
                if not ok:
                    key = reason.split(" ")[0]  # 归类
                    rejected[key] = rejected.get(key, 0) + 1
                    continue
                rec = {
                    "stock_code": code,
                    "stock_name": rec_row.get("stock_name", ""),
                    "industry": rec_row.get("行业", "") or rec_row.get("industry", ""),
                    "current_price": float(rec_row.get("current_price", ind["last"])),
                    "turnover": float(rec_row.get("turnover", 0) or 0),
                    **ind,
                }
                rows.append(rec)
                if processed % 100 == 0:
                    logger.info("已处理 %d/%d", processed, len(candidate_records))

        logger.info(
            "硬过滤后剩 %d 只进入打分；被踢出原因统计：%s",
            len(rows), rejected,
        )

        if not rows:
            logger.warning("硬过滤后无候选，今日无推荐")
            return []

        factors = pd.DataFrame(rows)
        scored = self._score_dataframe(factors)
        scored = scored.sort_values("total_score", ascending=False)

        # 行业分散：每个行业最多取 2 只，凑满 top_n
        selected_rows: List[Dict] = []
        sector_counts: Dict[str, int] = {}
        for _, row in scored.iterrows():
            sector = str(row.get("industry", "")).strip() or "其他"
            if sector_counts.get(sector, 0) < 2:
                selected_rows.append(row.to_dict())
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if len(selected_rows) >= top_n:
                break

        logger.info("行业分散选取：%s", {k: v for k, v in sector_counts.items() if v > 0})

        results: List[Dict] = []
        for row in selected_rows:
            ref_close = round(float(row["current_price"]), 2)
            reason = {
                "total_score": round(float(row["total_score"]), 2),
                "trend_strength": round(float(row["trend_strength"]), 2),
                "trend_smooth": round(float(row["trend_smooth"]), 2),
                "volume_factor": round(float(row["volume_factor"]), 2),
                "position": round(float(row["position"]), 2),
                "liquidity": round(float(row["liquidity"]), 2),
                "ret_5": round(float(row["ret_5"]) * 100, 2),
                "ret_20": round(float(row["ret_20"]) * 100, 2),
                "ret_60": round(float(row["ret_60"]) * 100, 2),
                "vol_std": round(float(row["vol_std"]) * 100, 2),
                "max_dd_20": round(float(row["max_dd"]) * 100, 2),
                "vol_ratio_5_20": round(float(row["vol_ratio_5_20"]), 2),
                "dist_high60": round(float(row["dist_high60"]) * 100, 2),
                "reference_close": ref_close,
                "industry": str(row.get("industry", "")).strip() or "其他",
            }
            results.append({
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "reference_close": ref_close,
                "recommend_reason": reason,
            })

        logger.info("选股完成，推荐 %d 只", len(results))
        return results
