"""每日表现跟踪：更新 active 推荐的当日数据，触发平仓条件则关单。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import pandas as pd
from sqlalchemy import func

from app.data_fetcher import DataFetcher, get_default_fetcher
from app.database import db
from app.models import StockDailyPerformance, StockRecommendation, StrategyStatistics
from app.signal_generator import SignalGenerator
from app.utils import get_logger

logger = get_logger(__name__)


def _to_decimal(value, places: int = 4) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(f"{float(value):.{places}f}")
    except (TypeError, ValueError):
        return None


def _trading_days_between(history: pd.DataFrame, start: date) -> int:
    if history is None or history.empty or "trade_date" not in history.columns:
        return 0
    return int((history["trade_date"] >= start).sum())


class PerformanceTracker:
    def __init__(
        self,
        fetcher: Optional[DataFetcher] = None,
        signal_generator: Optional[SignalGenerator] = None,
    ):
        self.fetcher = fetcher or get_default_fetcher()
        self.signal_generator = signal_generator or SignalGenerator()

    # ------------------------------------------------------------------
    def insert_initial_performance(
        self,
        recommendation: StockRecommendation,
        trade_date: date,
    ) -> StockDailyPerformance:
        """推荐当天写入一条 buy 记录。"""
        perf = StockDailyPerformance(
            recommendation_id=recommendation.id,
            trade_date=trade_date,
            current_price=recommendation.recommend_price,
            change_percent=Decimal("0.0000"),
            volume=None,
            turnover=None,
            signal="buy",
            signal_reason="首次推荐买入",
        )
        db.session.add(perf)
        return perf

    # ------------------------------------------------------------------
    def update_daily_performance(self, trade_date: Optional[date] = None) -> dict:
        """遍历所有 active 且已加入观察池的推荐，写入今日表现并按需平仓。返回汇总信息。"""
        trade_date = trade_date or date.today()
        actives = (
            StockRecommendation.query
            .filter_by(status="active", is_watched=True, price_status="filled")
            .all()
        )
        if not actives:
            logger.info("没有已观察+已成交的 active 推荐需要更新")
            return {"updated": 0, "closed": 0}

        spot = self.fetcher.get_realtime_prices([r.stock_code for r in actives])
        spot_idx = (
            spot.set_index("stock_code") if not spot.empty and "stock_code" in spot.columns else None
        )

        updated = 0
        closed = 0

        for rec in actives:
            try:
                row = spot_idx.loc[rec.stock_code] if spot_idx is not None and rec.stock_code in spot_idx.index else None
                current_price = float(row["current_price"]) if row is not None else None
                volume = float(row.get("volume")) if row is not None and pd.notna(row.get("volume")) else None
                turnover = float(row.get("turnover")) if row is not None and pd.notna(row.get("turnover")) else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取 %s 实时行情失败：%s", rec.stock_code, exc)
                current_price, volume, turnover = None, None, None

            if current_price is None or current_price <= 0:
                logger.warning("跳过 %s：缺少有效行情", rec.stock_code)
                continue

            recommend_price = float(rec.recommend_price)
            change_percent = (current_price - recommend_price) / recommend_price if recommend_price else 0.0

            history = self.fetcher.get_recent_daily(rec.stock_code, days=40)
            hold_days = _trading_days_between(history, rec.recommend_date)

            signal, reason = self.signal_generator.generate_signal(
                change_percent=change_percent,
                history=history,
                hold_days=hold_days,
                is_initial=False,
            )

            perf = StockDailyPerformance(
                recommendation_id=rec.id,
                trade_date=trade_date,
                current_price=_to_decimal(current_price, 2),
                change_percent=_to_decimal(change_percent, 4),
                volume=int(volume) if volume is not None else None,
                turnover=_to_decimal(turnover, 2),
                signal=signal,
                signal_reason=reason[:200],
            )
            db.session.add(perf)
            updated += 1

            if signal == "sell":
                rec.status = "closed"
                rec.close_date = trade_date
                rec.close_price = _to_decimal(current_price, 2)
                rec.final_return = _to_decimal(change_percent, 4)
                closed += 1

        db.session.commit()
        logger.info("表现更新完成：updated=%d closed=%d", updated, closed)
        return {"updated": updated, "closed": closed}

    # ------------------------------------------------------------------
    def compute_statistics(self, stat_date: Optional[date] = None) -> StrategyStatistics:
        """计算累计统计并写入 strategy_statistics（按日唯一，存在则更新）。
        统计基于已加入观察池的推荐——未观察的视为未持仓，不计入胜率。
        """
        stat_date = stat_date or date.today()
        # 只统计已成交的（filled）；pending 还没买入价、void 是作废未成交，都不计入
        recs = (
            StockRecommendation.query
            .filter(StockRecommendation.shares > 0)
            .filter_by(price_status="filled")
            .all()
        )
        total = len(recs)
        active = sum(1 for r in recs if r.status == "active")
        closed_recs = [r for r in recs if r.status == "closed" and r.final_return is not None]
        closed = len(closed_recs)
        returns = [float(r.final_return) for r in closed_recs]
        win_count = sum(1 for x in returns if x > 0)
        loss_count = sum(1 for x in returns if x <= 0)
        win_rate = (win_count / closed) if closed else 0.0
        avg_return = (sum(returns) / closed) if closed else 0.0
        max_return = max(returns) if returns else 0.0
        max_loss = min(returns) if returns else 0.0
        total_return = sum(returns) if returns else 0.0

        stats = StrategyStatistics.query.filter_by(stat_date=stat_date).first()
        if stats is None:
            stats = StrategyStatistics(stat_date=stat_date)
            db.session.add(stats)

        stats.total_recommendations = total
        stats.active_positions = active
        stats.closed_positions = closed
        stats.win_count = win_count
        stats.loss_count = loss_count
        stats.win_rate = _to_decimal(win_rate, 4)
        stats.avg_return = _to_decimal(avg_return, 4)
        stats.max_return = _to_decimal(max_return, 4)
        stats.max_loss = _to_decimal(max_loss, 4)
        stats.total_return = _to_decimal(total_return, 4)

        db.session.commit()
        logger.info(
            "统计完成：total=%d active=%d closed=%d win_rate=%.2f%% avg=%.2f%%",
            total, active, closed, win_rate * 100, avg_return * 100,
        )
        return stats
