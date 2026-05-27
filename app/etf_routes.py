"""ETF 页面路由。"""

from flask import Blueprint, render_template, jsonify, request
from app.etf_service import (
    get_etf_pool_with_data, get_etf_ranking, get_sector_flows,
    get_etf_daily_history, get_market_status, get_etf_profit_summary,
)

etf_bp = Blueprint("etf", __name__, url_prefix="/etf")


@etf_bp.route("/")
def overview():
    """ETF 总览：基金池 + 信号 + 操作建议。"""
    pool = get_etf_pool_with_data()
    market = get_market_status()

    buy_count = sum(1 for e in pool if e["advice"] in ("BUY", "建仓", "加仓"))
    sell_count = sum(1 for e in pool if e["advice"] in ("SELL", "清仓"))
    hold_count = len(pool) - buy_count - sell_count

    broad = [e for e in pool if e["category"] == "宽基"]
    sector = [e for e in pool if e["category"] == "行业"]

    return render_template(
        "etf_overview.html", nav="etf", pool=pool,
        broad=broad, sector=sector,
        buy_count=buy_count, sell_count=sell_count, hold_count=hold_count,
        market=market,
    )


@etf_bp.route("/ranking")
def ranking():
    """智能选基：多因子排名。"""
    ranks = get_etf_ranking()
    market = get_market_status()

    # 分类统计
    top5 = ranks[:5]
    buy_signals = [r for r in ranks if r["signal"] == "BUY"]
    sell_signals = [r for r in ranks if r["signal"] == "SELL"]

    return render_template(
        "etf_ranking.html", nav="etf_rank",
        ranks=ranks, top5=top5, market=market,
        buy_count=len(buy_signals), sell_count=len(sell_signals),
    )


@etf_bp.route("/flow")
def flow():
    """板块资金流。"""
    flows = get_sector_flows()

    top_inflow = sorted(
        [f for f in flows if f["main_net_inflow"] and float(f["main_net_inflow"]) > 0],
        key=lambda x: float(x["main_net_inflow"]), reverse=True
    )[:15]
    top_outflow = sorted(
        [f for f in flows if f["main_net_inflow"] and float(f["main_net_inflow"]) < 0],
        key=lambda x: float(x["main_net_inflow"])
    )[:15]

    return render_template(
        "etf_flow.html", nav="etf_flow",
        flows=flows, top_inflow=top_inflow, top_outflow=top_outflow,
        flow_date=flows[0]["date"] if flows else "",
    )


@etf_bp.route("/pnl")
def pnl():
    """持仓收益 + 盈亏分析。"""
    profit = get_etf_profit_summary()
    return render_template(
        "etf_pnl.html", nav="etf_pnl",
        trades=profit["trades"],
        positions=profit["positions"],
        summary=profit["summary"],
    )


@etf_bp.route("/detail/<code>")
def detail(code):
    """单只 ETF 详情。"""
    history = get_etf_daily_history(code, days=60)
    ranking = get_etf_ranking()
    pool = get_etf_pool_with_data()
    
    etf_info = next((e for e in ranking if e["code"] == code), None)
    quote_info = next((e for e in pool if e["code"] == code), None)

    if not etf_info:
        return render_template("etf_detail.html", nav="etf", error=f"ETF {code} 未找到")

    # Merge: ranking data + quote data
    merged = dict(etf_info)
    if quote_info:
        merged["volume"] = quote_info.get("volume", 0)
        merged["date"] = quote_info.get("date", "")
        merged["advice"] = quote_info.get("advice", "")
    else:
        merged["volume"] = 0
        merged["date"] = ""
        merged["advice"] = etf_info.get("advice_raw", "")

    return render_template(
        "etf_detail.html", nav="etf",
        etf=merged, history=history,
    )


@etf_bp.route("/api/intraday")
def api_intraday():
    """API: 盘中实时估值。"""
    import urllib.request

    codes = [
        "588000", "513180", "513100", "159949", "159227", "512480",
        "515700", "515050", "159755", "159611", "159326", "159278",
        "515790", "159805", "159825", "159870", "512400", "561360",
        "515220", "515210", "516970", "512170", "515290", "515450",
        "512880", "510150",
    ]

    tc_codes = []
    for c in codes:
        tc_codes.append(f"sh{c}" if c.startswith(("5", "6", "9")) else f"sz{c}")

    url = "http://qt.gtimg.cn/q=" + ",".join(tc_codes)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
    except Exception:
        return jsonify({"error": "行情获取失败"}), 500

    results = []
    for line in raw.strip().split("\n"):
        if "~" not in line: continue
        parts = line.split("~")
        if len(parts) < 35: continue
        try:
            results.append({
                "code": parts[2], "name": parts[1],
                "price": float(parts[3]), "change_pct": float(parts[32]),
            })
        except (ValueError, IndexError):
            continue
    return jsonify(results)
