"""Web 路由：页面 + JSON API。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, Optional
import time

from flask import Blueprint, current_app, jsonify, render_template, request
from sqlalchemy import desc, func

from app.database import db
import sqlite3
import os
import urllib.request
from app.models import StockDailyPerformance, StockRecommendation, StrategyStatistics
from app.scheduler import (
    run_daily_selection,
    run_daily_statistics,
    run_daily_update,
    run_open_price_fill,
)
from app.utils import get_logger
from config import Config

logger = get_logger(__name__)
bp = Blueprint("main", __name__)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _latest_perf_subquery():
    """每个推荐对应最新一条 daily_performance 的 id。"""
    return (
        db.session.query(
            StockDailyPerformance.recommendation_id.label("rid"),
            func.max(StockDailyPerformance.id).label("max_id"),
        )
        .group_by(StockDailyPerformance.recommendation_id)
        .subquery()
    )


def _calc_fee(amount: float, is_buy: bool = True) -> float:
    """计算交易费用。买入：佣金万2.5最低5元。卖出：佣金万2.5最低5元 + 印花税0.1%。"""
    commission = max(amount * 0.00025, 5.0)
    if is_buy:
        return round(commission, 2)
    stamp_duty = amount * 0.001
    return round(commission + stamp_duty, 2)


def _breakeven_price(total_cost: float, shares: int) -> float:
    """计算回本卖出价：卖出净得 = total_cost。"""
    if shares <= 0:
        return 0.0
    # 卖出净得 = P * shares - max(P*shares*0.00025, 5) - P*shares*0.001
    # 当 P*shares >= 20000 时简化为：P*shares*(1-0.00025-0.001) = total_cost
    sell_amount_min = total_cost + 5 + total_cost * 0.001  # 最坏情况估算
    if sell_amount_min >= 20000:
        return round(total_cost / (shares * 0.99875), 4)
    # 否则迭代求解（小额情况）
    lo, hi = 0.01, total_cost / shares * 2
    for _ in range(30):
        mid = (lo + hi) / 2
        sell_amount = mid * shares
        sell_fee = _calc_fee(sell_amount, is_buy=False)
        net = sell_amount - sell_fee
        if net < total_cost:
            lo = mid
        else:
            hi = mid
    return round(hi, 4)


def _recommendation_to_dict(rec: StockRecommendation, latest: Optional[StockDailyPerformance] = None) -> dict:
    reason = rec.recommend_reason or {}
    reference_close = reason.get("reference_close") if isinstance(reason, dict) else None
    shares = int(rec.shares or 0)
    cost = float(rec.recommend_price) if rec.recommend_price else 0
    cur = float(latest.current_price) if latest and latest.current_price else 0
    # 已平仓的记录：优先用 close_price
    if cur == 0 and rec.status == "closed" and rec.close_price:
        cur = float(rec.close_price)
    # Fallback: 如果 daily_performance 无数据，从 recommend_reason 中取
    reason_cur = reason.get("current_price") if isinstance(reason, dict) else None
    reason_chg = reason.get("change_percent") if isinstance(reason, dict) else None
    if cur == 0 and reason_cur:
        cur = float(reason_cur)
    chg = float(latest.change_percent) if latest and latest.change_percent is not None else None
    if chg is None and reason_chg is not None:
        chg = float(reason_chg)
        # recommend_reason 中的 change_percent 可能是百分数(如2.4)而非小数(0.024)
        if abs(chg) > 1:
            chg = chg / 100

    # 简单 P&L（不含费）
    simple_pnl = round((cur - cost) * shares, 2) if shares > 0 else 0

    # 含手续费计算
    buy_amount = cost * shares if shares > 0 else 0
    buy_fee = _calc_fee(buy_amount, is_buy=True) if shares > 0 else 0
    total_cost = round(buy_amount + buy_fee, 2) if shares > 0 else 0
    breakeven = _breakeven_price(total_cost, shares) if shares > 0 else 0

    # 当前市值和含费盈亏
    cur_value = round(cur * shares, 2) if shares > 0 and cur > 0 else 0
    if cur_value > 0:
        sell_fee = _calc_fee(cur_value, is_buy=False)
        net_pnl = round(cur_value - sell_fee - total_cost, 2)
    else:
        sell_fee = 0
        net_pnl = 0

    return {
        "id": rec.id,
        "stock_code": rec.stock_code,
        "stock_name": rec.stock_name,
        "shares": shares,
        "pnl_amount": simple_pnl,
        "net_pnl": net_pnl,
        "buy_amount": buy_amount,
        "buy_fee": buy_fee,
        "total_cost": total_cost,
        "breakeven_price": breakeven,
        "recommend_date": rec.recommend_date.isoformat() if rec.recommend_date else None,
        "recommend_price": float(rec.recommend_price) if rec.recommend_price is not None else None,
        "price_status": rec.price_status,
        "reference_close": float(reference_close) if reference_close is not None else None,
        "recommend_reason": rec.recommend_reason,
        "status": rec.status,
        "close_date": rec.close_date.isoformat() if rec.close_date else None,
        "close_price": float(rec.close_price) if rec.close_price is not None else None,
        "final_return": float(rec.final_return) if rec.final_return is not None else None,
        "is_watched": bool(rec.is_watched),
        "watched_at": rec.watched_at.isoformat() if rec.watched_at else None,
        "current_price": cur if cur > 0 else (float(latest.current_price) if latest and latest.current_price is not None else None),
        "change_percent": chg,
        "signal": latest.signal if latest else None,
        "signal_reason": latest.signal_reason if latest else None,
    }


# ----------------------------------------------------------------------
# 页面
# ----------------------------------------------------------------------
@bp.route("/")
def index():
    today = date.today()
    latest_date = (
        db.session.query(func.max(StockRecommendation.recommend_date)).scalar()
    )
    target_date = latest_date or today

    # ── 真正的持仓（用户有股数且有成本价的 active 记录）──
    holdings = (
        StockRecommendation.query
        .filter(StockRecommendation.status == "active")
        .filter(StockRecommendation.shares > 0)
        .filter(StockRecommendation.recommend_price.isnot(None))
        .order_by(StockRecommendation.id.desc())
        .all()
    )

    # ── 今日推荐（限 TOP_N 条，按 recommend_reason 中的 total_score 降序）──
    recs = (
        StockRecommendation.query.filter_by(recommend_date=target_date)
        .filter(StockRecommendation.source == "system")
        .order_by(StockRecommendation.id.asc())
        .limit(Config.TOP_N_STOCKS)
        .all()
    )

    # ── 历史推荐频次（近7天 system 来源，用于 UI 标注连续性）──
    seven_days_ago = today - timedelta(days=7)
    history_rows = (
        db.session.query(
            StockRecommendation.stock_code,
            func.count(StockRecommendation.id).label("cnt")
        )
        .filter(StockRecommendation.source == "system")
        .filter(StockRecommendation.recommend_date >= seven_days_ago)
        .group_by(StockRecommendation.stock_code)
        .all()
    )
    history_freq = {row[0]: row[1] for row in history_rows}

    latest_sub = _latest_perf_subquery()
    perf_map = {}

    # 持仓的 performance
    if holdings:
        ids = [r.id for r in holdings]
        perfs = (
            db.session.query(StockDailyPerformance)
            .join(latest_sub, StockDailyPerformance.id == latest_sub.c.max_id)
            .filter(StockDailyPerformance.recommendation_id.in_(ids))
            .all()
        )
        perf_map = {p.recommendation_id: p for p in perfs}

    holding_items = [_recommendation_to_dict(r, perf_map.get(r.id)) for r in holdings]

    # 推荐的 performance（去重，避免覆盖）
    perf_map2 = {}
    if recs:
        ids2 = [r.id for r in recs]
        perfs2 = (
            db.session.query(StockDailyPerformance)
            .join(latest_sub, StockDailyPerformance.id == latest_sub.c.max_id)
            .filter(StockDailyPerformance.recommendation_id.in_(ids2))
            .all()
        )
        perf_map2 = {p.recommendation_id: p for p in perfs2}

    rec_items = [_recommendation_to_dict(r, perf_map2.get(r.id)) for r in recs]
    # 注入历史频次
    for item in rec_items:
        item["history_count"] = history_freq.get(item["stock_code"], 0)

    # ── 获取推荐股的实时行情（解决"现价=推荐价"问题）──
    rec_no_shares = [r for r in recs if (r.shares or 0) == 0]
    if rec_no_shares:
        try:
            from app.data_fetcher import get_default_fetcher
            fetcher = get_default_fetcher()
            spot = fetcher.get_realtime_prices([r.stock_code for r in rec_no_shares])
            if not spot.empty and "stock_code" in spot.columns:
                spot_map = spot.set_index("stock_code")
                for item in rec_items:
                    code = item.get("stock_code", "")
                    if item.get("shares", 0) == 0 and code in spot_map.index:
                        row = spot_map.loc[code]
                        real_price = float(row["current_price"])
                        rec_price = item.get("recommend_price", 0)
                        if real_price > 0 and rec_price > 0:
                            item["current_price"] = round(real_price, 2)
                            item["change_percent"] = round((real_price - rec_price) / rec_price, 4)
        except Exception:
            pass  # 行情获取失败时保持原样

    # ── 持仓总盈亏（含手续费）──
    total_pnl = sum(
        (item.get("net_pnl") or item.get("pnl_amount") or 0) for item in holding_items
    )
    total_cost = sum(
        (item.get("total_cost") or 0) for item in holding_items
    )

    # ── 已平仓累计盈亏 ──
    closed_recs = (
        StockRecommendation.query
        .filter_by(status="closed")
        .filter(StockRecommendation.shares > 0)
        .filter(StockRecommendation.final_return.isnot(None))
        .all()
    )
    realized_pnl = 0.0
    for cr in closed_recs:
        cr_cost = float(cr.recommend_price) if cr.recommend_price else 0
        cr_close = float(cr.close_price) if cr.close_price else 0
        cr_shares = int(cr.shares or 0)
        if cr_shares > 0 and cr_cost > 0 and cr_close > 0:
            buy_amt = cr_cost * cr_shares
            buy_f = max(buy_amt * 0.00025, 5)
            sell_amt = cr_close * cr_shares
            sell_f = max(sell_amt * 0.00025, 5) + sell_amt * 0.001
            realized_pnl += sell_amt - sell_f - (buy_amt + buy_f)

    stats = StrategyStatistics.query.order_by(desc(StrategyStatistics.stat_date)).first()
    return render_template(
        "index.html",
        recommend_date=target_date,
        holdings=holding_items,
        total_pnl=total_pnl,
        total_cost=total_cost,
        realized_pnl=realized_pnl,
        recommendations=rec_items,
        stats=stats,
    )


@bp.route("/recommendations")
def recommendations():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    status = request.args.get("status") or ""

    q = StockRecommendation.query
    if start:
        q = q.filter(StockRecommendation.recommend_date >= start)
    if end:
        q = q.filter(StockRecommendation.recommend_date <= end)
    if status in ("active", "closed"):
        q = q.filter(StockRecommendation.status == status)

    recs = q.order_by(desc(StockRecommendation.recommend_date), StockRecommendation.id.asc()).limit(500).all()

    latest_sub = _latest_perf_subquery()
    perf_map = {}
    if recs:
        ids = [r.id for r in recs]
        perfs = (
            db.session.query(StockDailyPerformance)
            .join(latest_sub, StockDailyPerformance.id == latest_sub.c.max_id)
            .filter(StockDailyPerformance.recommendation_id.in_(ids))
            .all()
        )
        perf_map = {p.recommendation_id: p for p in perfs}

    items = [_recommendation_to_dict(r, perf_map.get(r.id)) for r in recs]
    return render_template(
        "recommendations.html",
        items=items,
        start=start.isoformat() if start else "",
        end=end.isoformat() if end else "",
        status=status,
    )


@bp.route("/performance")
def performance():
    actives = StockRecommendation.query.filter_by(status="active", is_watched=True).all()
    latest_sub = _latest_perf_subquery()
    perf_map = {}
    if actives:
        ids = [r.id for r in actives]
        perfs = (
            db.session.query(StockDailyPerformance)
            .join(latest_sub, StockDailyPerformance.id == latest_sub.c.max_id)
            .filter(StockDailyPerformance.recommendation_id.in_(ids))
            .all()
        )
        perf_map = {p.recommendation_id: p for p in perfs}

    items = [_recommendation_to_dict(r, perf_map.get(r.id)) for r in actives]
    items.sort(key=lambda x: (x["change_percent"] is None, -(x["change_percent"] or 0)))
    return render_template("performance.html", items=items)


@bp.route("/watchlist")
def watchlist():
    """已加入观察池的全部推荐（活跃 + 已平仓）。"""
    recs = (
        StockRecommendation.query
        .filter_by(is_watched=True)
        .order_by(StockRecommendation.status.asc(), StockRecommendation.recommend_date.desc())
        .all()
    )
    perf_map = {}
    if recs:
        latest_sub = _latest_perf_subquery()
        ids = [r.id for r in recs]
        perfs = (
            db.session.query(StockDailyPerformance)
            .join(latest_sub, StockDailyPerformance.id == latest_sub.c.max_id)
            .filter(StockDailyPerformance.recommendation_id.in_(ids))
            .all()
        )
        perf_map = {p.recommendation_id: p for p in perfs}
    items = [_recommendation_to_dict(r, perf_map.get(r.id)) for r in recs]
    return render_template("watchlist.html", items=items)


@bp.route("/statistics")
def statistics():
    history = (
        StrategyStatistics.query.order_by(StrategyStatistics.stat_date.asc()).limit(180).all()
    )
    latest = history[-1] if history else None

    # 计算已平仓累计收益金额
    closed_recs = (
        StockRecommendation.query
        .filter_by(status="closed")
        .filter(StockRecommendation.shares > 0)
        .filter(StockRecommendation.final_return.isnot(None))
        .all()
    )
    realized_pnl = 0.0
    for cr in closed_recs:
        cr_cost = float(cr.recommend_price) if cr.recommend_price else 0
        cr_close = float(cr.close_price) if cr.close_price else 0
        cr_shares = int(cr.shares or 0)
        if cr_shares > 0 and cr_cost > 0 and cr_close > 0:
            buy_amt = cr_cost * cr_shares
            buy_f = max(buy_amt * 0.00025, 5)
            sell_amt = cr_close * cr_shares
            sell_f = max(sell_amt * 0.00025, 5) + sell_amt * 0.001
            realized_pnl += sell_amt - sell_f - (buy_amt + buy_f)

    # 同样计算最大盈利/亏损的金额
    max_win_amt = 0.0
    max_loss_amt = 0.0
    for cr in closed_recs:
        cr_cost = float(cr.recommend_price) if cr.recommend_price else 0
        cr_close = float(cr.close_price) if cr.close_price else 0
        cr_shares = int(cr.shares or 0)
        if cr_shares > 0 and cr_cost > 0 and cr_close > 0:
            buy_amt = cr_cost * cr_shares
            buy_f = max(buy_amt * 0.00025, 5)
            sell_amt = cr_close * cr_shares
            sell_f = max(sell_amt * 0.00025, 5) + sell_amt * 0.001
            pnl = sell_amt - sell_f - (buy_amt + buy_f)
            if pnl > max_win_amt:
                max_win_amt = pnl
            if pnl < max_loss_amt:
                max_loss_amt = pnl

    return render_template("statistics.html", history=history, latest=latest,
                           realized_pnl=realized_pnl, max_win_amt=max_win_amt,
                           max_loss_amt=max_loss_amt)


@bp.route("/analyze")
def analyze():
    """已合并到投资顾问页。"""
    from flask import redirect, url_for
    return redirect(url_for("main.advisor"))


# ----------------------------------------------------------------------
# JSON API
# ----------------------------------------------------------------------
@bp.route("/api/recommendations")
def api_recommendations():
    target_date = _parse_date(request.args.get("date")) or (
        db.session.query(func.max(StockRecommendation.recommend_date)).scalar()
        or date.today()
    )
    recs = StockRecommendation.query.filter_by(recommend_date=target_date).all()
    return jsonify([_recommendation_to_dict(r) for r in recs])


@bp.route("/api/stats_chart")
def api_stats_chart():
    days = int(request.args.get("days", 60))
    since = date.today() - timedelta(days=days)
    rows = (
        StrategyStatistics.query.filter(StrategyStatistics.stat_date >= since)
        .order_by(StrategyStatistics.stat_date.asc())
        .all()
    )
    return jsonify({
        "labels": [r.stat_date.isoformat() for r in rows],
        "win_rate": [float(r.win_rate or 0) * 100 for r in rows],
        "avg_return": [float(r.avg_return or 0) * 100 for r in rows],
        "total_return": [float(r.total_return or 0) * 100 for r in rows],
    })


@bp.route("/api/trigger_selection", methods=["POST"])
def api_trigger_selection():
    try:
        inserted = run_daily_selection(current_app._get_current_object(), force=True)
        return jsonify({"success": True, "inserted": inserted})
    except Exception as exc:  # noqa: BLE001
        logger.exception("手动选股失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/recommendations/delete", methods=["POST"])
def api_delete_recommendations():
    """批量删除推荐记录（勾选删除）。"""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    if not ids or not isinstance(ids, list):
        return jsonify({"success": False, "error": "请提供要删除的ID列表"}), 400
    
    try:
        deleted = (
            StockRecommendation.query
            .filter(StockRecommendation.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.session.commit()
        logger.info("手动删除 %d 条推荐记录", deleted)
        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        db.session.rollback()
        logger.error("批量删除失败: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/recommendations/cleanup", methods=["POST"])
def api_cleanup_old_recommendations():
    """清理 30 天前的系统推荐（自动+手动触发）。"""
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=30)
    try:
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
        logger.info("自动清理 %d 条过期系统推荐（%s 之前）", deleted, cutoff.isoformat())
        return jsonify({"success": True, "deleted": deleted, "cutoff": cutoff.isoformat()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/trigger_update", methods=["POST"])
def api_trigger_update():
    try:
        result = run_daily_update(current_app._get_current_object(), force=True)
        run_daily_statistics(current_app._get_current_object(), force=True)
        return jsonify({"success": True, **result})
    except Exception as exc:  # noqa: BLE001
        logger.exception("手动更新失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/watch/<int:rec_id>", methods=["POST"])
def api_toggle_watch(rec_id: int):
    """切换观察状态。加入观察时自动拉现价成交，立刻写入买入记录。"""
    rec = StockRecommendation.query.get(rec_id)
    if rec is None:
        return jsonify({"success": False, "error": "推荐不存在"}), 404
    if rec.price_status == "void":
        return jsonify({"success": False, "error": "该推荐已作废（次日未成交）"}), 400
    try:
        if rec.is_watched:
            # 移出观察池：删除关联的 daily_performance 记录，再删除推荐本身
            StockDailyPerformance.query.filter_by(recommendation_id=rec.id).delete()
            db.session.delete(rec)
            db.session.commit()
            return jsonify({"success": True, "is_watched": False, "deleted": True})

        rec.is_watched = True
        rec.watched_at = datetime.utcnow()

        # pending 的先拉现价成交，再写买入记录
        if rec.price_status == "pending":
            from decimal import Decimal
            from app.data_fetcher import get_default_fetcher

            price = None
            try:
                fetcher = get_default_fetcher()
                spot = fetcher.get_stock_spot()
                if spot is not None and not spot.empty and "stock_code" in spot.columns:
                    spot["stock_code"] = spot["stock_code"].astype(str).str.zfill(6)
                    hit = spot[spot["stock_code"] == rec.stock_code]
                    if not hit.empty:
                        price = float(hit.iloc[0].get("current_price", 0) or 0)
            except Exception:
                pass

            # 拉不到现价，用参考收盘价兜底
            if not price or price <= 0:
                reason = rec.recommend_reason or {}
                price = float(reason.get("reference_close", 0) or 0)

            if not price or price <= 0:
                db.session.rollback()
                return jsonify({"success": False, "error": "无法获取现价，请稍后重试或手动输入"}), 500

            rec.recommend_price = Decimal(f"{price:.2f}")
            rec.price_status = "filled"

        # 写入买入记录
        if rec.price_status == "filled":
            from app.performance_tracker import PerformanceTracker
            existing = StockDailyPerformance.query.filter_by(recommendation_id=rec.id).count()
            if existing == 0:
                tracker = PerformanceTracker()
                tracker.insert_initial_performance(rec, rec.recommend_date)

        db.session.commit()
        return jsonify({
            "success": True,
            "is_watched": True,
            "price_status": rec.price_status,
            "filled_price": float(rec.recommend_price) if rec.recommend_price else None,
        })
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception("toggle watch 失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/trigger_open_fill", methods=["POST"])
def api_trigger_open_fill():
    """手动触发昨日 pending 推荐的开盘价回填（用于盘中或测试）。"""
    try:
        result = run_open_price_fill(current_app._get_current_object(), force=True)
        return jsonify({"success": True, **result})
    except Exception as exc:  # noqa: BLE001
        logger.exception("手动开盘回填失败")
        return jsonify({"success": False, "error": str(exc)}), 500


# ----------------------------------------------------------------------
# 单股分析 + 用户加观察
# ----------------------------------------------------------------------
_analyze_cache: Dict[str, tuple[float, Dict]] = {}  # code -> (timestamp, result)
_ANALYZE_CACHE_TTL = 300  # 5 分钟内同股票不重复拉 API
_ANALYZE_CACHE_MAX = 200  # 最多缓存 200 只股票


@bp.route("/api/analyze/<stock_code>", methods=["GET"])
def api_analyze(stock_code: str):
    """对单只票做体检 + 打分 + 结论。GET 不写库，只返回分析结果。
    结果缓存 5 分钟，避免重复拉 API 导致分数抖动。
    """
    code = (stock_code or "").strip()
    if not code.isdigit() or len(code) != 6:
        return jsonify({"success": False, "error": "股票代码必须是 6 位数字"}), 400

    # 检查缓存
    cached = _analyze_cache.get(code)
    if cached:
        ts, result = cached
        if time.time() - ts < _ANALYZE_CACHE_TTL:
            return jsonify({"success": True, "cached": True, **result})

    try:
        from app.stock_selector import StockSelector
        selector = StockSelector()
        result = selector.analyze_single(code)
        if "error" in result:
            return jsonify({"success": False, **result}), 404
        # 同时返回数据库里这只票现存的、未关闭的推荐（用于"已加入观察池"按钮态）
        existing = (
            StockRecommendation.query
            .filter_by(stock_code=result["stock_code"], status="active")
            .order_by(desc(StockRecommendation.id))
            .first()
        )
        if existing:
            result["existing_rec"] = {
                "id": existing.id,
                "is_watched": bool(existing.is_watched),
                "source": existing.source,
                "recommend_date": existing.recommend_date.isoformat(),
                "price_status": existing.price_status,
            }

        _analyze_cache[code] = (time.time(), result)
        # 超过上限时清除最旧的条目
        if len(_analyze_cache) > _ANALYZE_CACHE_MAX:
            oldest_key = min(_analyze_cache, key=lambda k: _analyze_cache[k][0])
            del _analyze_cache[oldest_key]
        return jsonify({"success": True, **result})
    except Exception as exc:  # noqa: BLE001
        logger.exception("单股分析失败 %s", code)
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/watch/by_code", methods=["POST"])
def api_watch_by_code():
    """用户输入代码 + 当前价格 → 入库为 user 来源的推荐 + 加观察池。

    Body JSON: {"stock_code": "600519", "stock_name": "贵州茅台", "current_price": 1689.5}

    规则：
      - 同一只票若已有 active 推荐，直接把它设为 is_watched=True（不重复入库）
      - 否则新建一条 source='user' 的推荐：
          recommend_date=today, price_status='filled',
          recommend_price=用户看到的现价（视为成交价）
        并立刻写一条 buy daily_performance
    """
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("stock_code", "")).strip().zfill(6)
    name = str(payload.get("stock_name", "")).strip()
    try:
        price = float(payload.get("current_price"))
    except (TypeError, ValueError):
        price = 0.0

    if not code.isdigit() or len(code) != 6:
        return jsonify({"success": False, "error": "股票代码必须是 6 位数字"}), 400
    if price <= 0:
        return jsonify({"success": False, "error": "缺少有效现价"}), 400

    try:
        # 已存在 active 的推荐 → 直接观察
        existing = (
            StockRecommendation.query
            .filter_by(stock_code=code, status="active")
            .order_by(desc(StockRecommendation.id))
            .first()
        )
        if existing is not None:
            if not existing.is_watched:
                existing.is_watched = True
                existing.watched_at = datetime.utcnow()
                # 若没有 daily_performance 且已 filled，补一条买入
                if existing.price_status == "filled":
                    has_perf = StockDailyPerformance.query.filter_by(
                        recommendation_id=existing.id
                    ).count() > 0
                    if not has_perf:
                        from app.performance_tracker import PerformanceTracker
                        PerformanceTracker().insert_initial_performance(
                            existing, existing.recommend_date
                        )
                db.session.commit()
            return jsonify({
                "success": True,
                "rec_id": existing.id,
                "reused": True,
                "source": existing.source,
            })

        # 新建 user 推荐
        from decimal import Decimal
        rec = StockRecommendation(
            stock_code=code,
            stock_name=name or code,
            recommend_date=date.today(),
            recommend_price=Decimal(f"{price:.2f}"),
            price_status="filled",   # 用户加的票直接当作以当前价成交
            recommend_reason={"manual": True, "entry_price": round(price, 2)},
            status="active",
            is_watched=True,
            watched_at=datetime.utcnow(),
            source="user",
        )
        db.session.add(rec)
        db.session.flush()

        # 立刻写一条 buy daily_performance
        from app.performance_tracker import PerformanceTracker
        PerformanceTracker().insert_initial_performance(rec, rec.recommend_date)
        db.session.commit()

        return jsonify({
            "success": True,
            "rec_id": rec.id,
            "reused": False,
            "source": "user",
        })
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception("api_watch_by_code 失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/rec/<int:rec_id>/price", methods=["POST"])
def api_update_price(rec_id: int):
    """更新推荐的成本价。"""
    rec = StockRecommendation.query.get(rec_id)
    if rec is None:
        return jsonify({"success": False, "error": "推荐不存在"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        new_price = float(payload.get("price", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "无效价格"}), 400
    if new_price <= 0:
        return jsonify({"success": False, "error": "价格必须大于 0"}), 400
    try:
        from decimal import Decimal
        rec.recommend_price = Decimal(f"{new_price:.2f}")
        db.session.commit()
        return jsonify({"success": True, "price": float(rec.recommend_price)})
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception("更新成本价失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/rec/<int:rec_id>/curprice", methods=["POST"])
def api_update_curprice(rec_id: int):
    """更新最新现价，自动重算涨跌幅。"""
    rec = StockRecommendation.query.get(rec_id)
    if rec is None:
        return jsonify({"success": False, "error": "推荐不存在"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        new_price = float(payload.get("price", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "无效价格"}), 400
    if new_price <= 0:
        return jsonify({"success": False, "error": "价格必须大于 0"}), 400
    try:
        latest = (
            StockDailyPerformance.query
            .filter_by(recommendation_id=rec.id)
            .order_by(desc(StockDailyPerformance.id))
            .first()
        )
        cost = float(rec.recommend_price) if rec.recommend_price else float(new_price)
        change = (new_price - cost) / cost if cost > 0 else 0.0

        if latest:
            latest.current_price = new_price
            latest.change_percent = change
        else:
            from app.performance_tracker import PerformanceTracker
            perf = StockDailyPerformance(
                recommendation_id=rec.id,
                trade_date=date.today(),
                current_price=new_price,
                change_percent=change,
                signal="hold",
                signal_reason="手动更新现价",
            )
            db.session.add(perf)

        db.session.commit()
        return jsonify({
            "success": True,
            "price": new_price,
            "change_percent": round(change * 100, 2),
        })
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception("更新现价失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/rec/<int:rec_id>/shares", methods=["POST"])
def api_update_shares(rec_id: int):
    """更新持仓股数。"""
    rec = StockRecommendation.query.get(rec_id)
    if rec is None:
        return jsonify({"success": False, "error": "推荐不存在"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        new_shares = int(payload.get("shares", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "无效股数"}), 400
    if new_shares < 0:
        return jsonify({"success": False, "error": "股数不能为负"}), 400
    try:
        rec.shares = new_shares
        db.session.commit()

        cost = float(rec.recommend_price) if rec.recommend_price else 0
        latest = (
            StockDailyPerformance.query
            .filter_by(recommendation_id=rec.id)
            .order_by(desc(StockDailyPerformance.id))
            .first()
        )
        cur = float(latest.current_price) if latest and latest.current_price else 0
        pnl = round((cur - cost) * new_shares, 2) if new_shares > 0 else 0

        return jsonify({"success": True, "shares": new_shares, "pnl_amount": pnl})
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception("更新股数失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/market_status")
def api_market_status():
    """返回大盘状态：沪深300现价、MA60、过滤状态。"""
    result = {"sh300": None, "ma60": None, "status": "unknown", "diff_pct": 0}
    try:
        # 1) 从 SQLite 获取 MA60
        db_path = os.path.join(current_app.root_path, "..", "backtest", "data", "market_data.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT close FROM index_daily ORDER BY trade_date DESC LIMIT 60")
            closes = [r[0] for r in cursor.fetchall()]
            conn.close()
            if closes:
                result["ma60"] = round(sum(closes) / len(closes), 2)
    except Exception:
        pass

    # 2) 从腾讯获取沪深300实时价格
    try:
        req = urllib.request.Request(
            "http://qt.gtimg.cn/q=sh000300",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk")
            parts = raw.split("~")
            if len(parts) > 33:
                result["sh300"] = float(parts[3])
                result["change_pct"] = float(parts[32]) if parts[32] else 0
    except Exception:
        pass

    # 3) 判断状态
    if result["sh300"] and result["ma60"]:
        diff = result["sh300"] - result["ma60"]
        result["diff_pct"] = round(diff / result["ma60"] * 100, 2)
        result["status"] = "above" if diff > 0 else "below"
    elif result["sh300"]:
        result["status"] = "no_ma"

    return jsonify(result)



# ═══════════════════════════════════════════
# 投资顾问模块
# ═══════════════════════════════════════════

@bp.route("/advisor")
def advisor():
    """投资顾问页面"""
    return render_template("advisor.html", nav="advisor")


@bp.route("/api/advisor/long-term/<stock_code>")
def api_advisor_long_term(stock_code: str):
    """长期投资总结 API"""
    try:
        from app.advisor import generate_long_term_summary
        result = generate_long_term_summary(stock_code)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        logger.exception("长期分析失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/advisor/short-term/<stock_code>")
def api_advisor_short_term(stock_code: str):
    """短线总结 API"""
    try:
        from app.advisor import generate_short_term_summary
        result = generate_short_term_summary(stock_code)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        logger.exception("短线分析失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/advisor/buy-sell/<stock_code>")
def api_advisor_buy_sell(stock_code: str):
    """买卖点分析 API"""
    try:
        from app.advisor import find_buy_sell_points
        result = find_buy_sell_points(stock_code)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        logger.exception("买卖点分析失败")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/advisor/pattern/<stock_code>")
def api_advisor_pattern(stock_code: str):
    """历史图形匹配 API"""
    try:
        from app.advisor import find_similar_patterns
        result = find_similar_patterns(stock_code)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        logger.exception("图形匹配失败")
        return jsonify({"success": False, "error": str(exc)}), 500
