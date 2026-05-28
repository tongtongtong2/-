"""APScheduler 调度器：选股 / 表现更新 / 统计三个任务。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler

from app.database import db
from app.data_fetcher import get_default_fetcher
from app.models import StockDailyPerformance, StockRecommendation
from app.performance_tracker import PerformanceTracker
from app.stock_selector import StockSelector
from app.utils import get_logger, is_trading_day
from config import Config

logger = get_logger(__name__)


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = value.split(":", 1)
        return int(h), int(m)
    except (ValueError, AttributeError):
        return default


def run_daily_selection(app, force: bool = False) -> int:
    """执行选股，写入 stock_recommendations。返回新写入条数。

    新规则：选股时不写 recommend_price，只标 price_status='pending'，等次日 09:35
    由 run_open_price_fill 用次日开盘价回填。
    """
    with app.app_context():
        today = date.today()
        if not force and not is_trading_day(today):
            logger.info("非交易日，跳过选股")
            return 0

        # 市场环境检查
        selector = StockSelector(min_volume=Config.MIN_VOLUME)
        if Config.MARKET_FILTER and not selector._check_market_regime():
            logger.info("市场环境不佳（沪深300低于MA%d），跳过选股", Config.INDEX_MA_PERIOD)
            return 0
        picks = selector.select_stocks(top_n=Config.TOP_N_STOCKS)
        if not picks:
            logger.warning("选股结果为空")
            return 0

        # 选股成功后再删旧数据（避免选股失败导致当天数据丢失）
        deleted = (
            StockRecommendation.query
            .filter_by(recommend_date=today, source="system")
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.info("已清除今日 %d 条旧系统推荐，替换为新结果", deleted)

        inserted = 0
        for p in picks:
            rec = StockRecommendation(
                stock_code=p["stock_code"],
                stock_name=p["stock_name"],
                recommend_date=today,
                recommend_price=None,
                price_status="pending",
                recommend_reason=p["recommend_reason"],
                status="active",
                is_watched=False,
            )
            db.session.add(rec)
            db.session.flush()
            inserted += 1
        db.session.commit()
        logger.info("选股入库完成，共 %d 条（待次日开盘回填买入价）", inserted)
        return inserted


def run_open_price_fill(app, force: bool = False) -> dict:
    """次日开盘后回填昨日 pending 推荐的买入价（用今日开盘价）。

    - 取昨天的 pending 推荐
    - 拉今日开盘价
    - 有开盘价 -> recommend_price = open, price_status = filled
                  若已加入观察池，补一条买入 daily_performance
    - 拉不到（停牌/接口失败）-> price_status = void, status = closed, 当作未成交
    """
    with app.app_context():
        today = date.today()
        if not force and not is_trading_day(today):
            logger.info("非交易日，跳过开盘价回填")
            return {"filled": 0, "voided": 0}

        pending = (
            StockRecommendation.query
            .filter_by(price_status="pending")
            .filter(StockRecommendation.recommend_date < today)
            .all()
        )
        if not pending:
            logger.info("没有待回填开盘价的推荐")
            return {"filled": 0, "voided": 0}

        fetcher = get_default_fetcher()
        # 强制拉今日 spot（不要用昨天缓存）
        spot = fetcher.get_stock_spot(force_refresh=True)
        spot_idx = (
            spot.set_index("stock_code")
            if spot is not None and not spot.empty and "stock_code" in spot.columns
            else None
        )

        from app.performance_tracker import PerformanceTracker
        tracker = PerformanceTracker(fetcher=fetcher)

        filled = 0
        voided = 0

        for rec in pending:
            open_price = None
            # 优先从 spot 拿 "今日开盘"；akshare 的 stock_zh_a_spot_em 字段名为 "今开"
            try:
                if spot_idx is not None and rec.stock_code in spot_idx.index:
                    row = spot_idx.loc[rec.stock_code]
                    for key in ("today_open", "open", "今开", "开盘"):
                        if key in row.index and pd.notna(row[key]):
                            open_price = float(row[key])
                            break
            except Exception as exc:  # noqa: BLE001
                logger.warning("从 spot 取 %s 开盘价失败: %s", rec.stock_code, exc)

            # spot 拿不到则回退日线接口
            if open_price is None or open_price <= 0:
                try:
                    hist = fetcher.get_recent_daily(rec.stock_code, days=5)
                    if hist is not None and not hist.empty and "open" in hist.columns:
                        last = hist.sort_values("trade_date").iloc[-1]
                        if pd.to_datetime(last["trade_date"]).date() == today:
                            open_price = float(last["open"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("从日线取 %s 开盘价失败: %s", rec.stock_code, exc)

            if open_price is None or open_price <= 0:
                # 停牌/数据缺失 -> 作废
                rec.price_status = "void"
                rec.status = "closed"
                rec.close_date = today
                rec.final_return = None
                voided += 1
                logger.info("作废 %s：次日无法获取开盘价（停牌或数据缺失）", rec.stock_code)
                continue

            rec.recommend_price = Decimal(f"{open_price:.2f}")
            rec.price_status = "filled"
            filled += 1

            # 如果已加入观察池，补一条买入 daily_performance（trade_date = 今日开盘日）
            if rec.is_watched:
                existing = StockDailyPerformance.query.filter_by(
                    recommendation_id=rec.id
                ).count()
                if existing == 0:
                    tracker.insert_initial_performance(rec, today)

        db.session.commit()
        logger.info("开盘价回填完成：filled=%d voided=%d", filled, voided)
        return {"filled": filled, "voided": voided}


def run_daily_update(app, force: bool = False) -> dict:
    with app.app_context():
        today = date.today()
        if not force and not is_trading_day(today):
            logger.info("非交易日，跳过表现更新")
            return {"updated": 0, "closed": 0}
        tracker = PerformanceTracker()
        return tracker.update_daily_performance(today)


def run_daily_statistics(app, force: bool = False):
    with app.app_context():
        today = date.today()
        if not force and not is_trading_day(today):
            logger.info("非交易日，跳过统计")
            return None
        tracker = PerformanceTracker()
        return tracker.compute_statistics(today)



def run_weekly_cleanup(app):
    """每周一清理 30 天前的系统推荐。"""
    from datetime import timedelta
    today = date.today()
    if today.weekday() != 0:
        return 0
    with app.app_context():
        try:
            cutoff = today - timedelta(days=30)
            deleted = (
                StockRecommendation.query
                .filter(
                    StockRecommendation.source == "system",
                    StockRecommendation.recommend_date < cutoff,
                    StockRecommendation.status == "active",
                )
                .delete(synchronize_session=False)
            )
            db.session.commit()
            if deleted:
                logger.info("每周清理: 删除 %d 条过期系统推荐 (%s 前)", deleted, cutoff.isoformat())
            return deleted
        except Exception as e:
            db.session.rollback()
            logger.warning("自动清理失败: %s", e)
            return 0


class TaskScheduler:
    def __init__(self, app):
        self.app = app
        self.scheduler: Optional[BackgroundScheduler] = None

    def start(self) -> None:
        if self.scheduler is not None:
            return
        sel_h, sel_m = _parse_hhmm(Config.SELECTION_TIME, (15, 30))
        upd_h, upd_m = _parse_hhmm(Config.UPDATE_TIME, (15, 35))
        sta_h, sta_m = _parse_hhmm(Config.STATISTICS_TIME, (15, 40))
        fil_h, fil_m = _parse_hhmm(getattr(Config, "OPEN_FILL_TIME", "09:35"), (9, 35))

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            lambda: run_daily_selection(self.app),
            "cron", day_of_week="mon-fri", hour=sel_h, minute=sel_m,
            id="daily_selection", replace_existing=True,
        )
        sched.add_job(
            lambda: run_open_price_fill(self.app),
            "cron", day_of_week="mon-fri", hour=fil_h, minute=fil_m,
            id="open_price_fill", replace_existing=True,
        )
        sched.add_job(
            lambda: run_daily_update(self.app),
            "cron", day_of_week="mon-fri", hour=upd_h, minute=upd_m,
            id="daily_update", replace_existing=True,
        )
        sched.add_job(
            lambda: run_daily_statistics(self.app),
            "cron", day_of_week="mon-fri", hour=sta_h, minute=sta_m,
            id="daily_statistics", replace_existing=True,
        )
        sched.start()
        self.scheduler = sched
        logger.info(
            "调度器已启动：选股 %02d:%02d，开盘回填 %02d:%02d，更新 %02d:%02d，统计 %02d:%02d",
            sel_h, sel_m, fil_h, fil_m, upd_h, upd_m, sta_h, sta_m,
        )

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
            logger.info("调度器已关闭")
