"""ETF 数据服务层 — 查询 ETF 系统的 SQLite 数据库。"""

import json
import sqlite3
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ETF_DB_PATH = r"F:\datax\etf_right_side_trader-master\etf_trader.db"

ETF_POOL = [
    {"code": "588000", "name": "科创50ETF", "category": "宽基"},
    {"code": "513180", "name": "恒生科技ETF", "category": "宽基"},
    {"code": "513100", "name": "纳指ETF", "category": "宽基"},
    {"code": "159949", "name": "创业板50ETF", "category": "宽基"},
    {"code": "159227", "name": "航空航天ETF", "category": "行业"},
    {"code": "512480", "name": "半导体ETF", "category": "行业"},
    {"code": "515700", "name": "新能源车ETF", "category": "行业"},
    {"code": "515050", "name": "通信ETF", "category": "行业"},
    {"code": "159755", "name": "电池ETF", "category": "行业"},
    {"code": "159611", "name": "电力ETF", "category": "行业"},
    {"code": "159326", "name": "电网设备ETF", "category": "行业"},
    {"code": "159278", "name": "机器人ETF", "category": "行业"},
    {"code": "515790", "name": "光伏ETF", "category": "行业"},
    {"code": "159805", "name": "传媒ETF", "category": "行业"},
    {"code": "159825", "name": "农业ETF", "category": "行业"},
    {"code": "159870", "name": "化工ETF", "category": "行业"},
    {"code": "512400", "name": "有色金属ETF", "category": "行业"},
    {"code": "561360", "name": "石油ETF", "category": "行业"},
    {"code": "515220", "name": "煤炭ETF", "category": "行业"},
    {"code": "515210", "name": "钢铁ETF", "category": "行业"},
    {"code": "516970", "name": "基建ETF", "category": "行业"},
    {"code": "512170", "name": "医疗ETF", "category": "行业"},
    {"code": "515290", "name": "银行ETF", "category": "行业"},
    {"code": "515450", "name": "红利低波ETF", "category": "行业"},
    {"code": "512880", "name": "证券ETF", "category": "行业"},
    {"code": "510150", "name": "消费ETF", "category": "行业"},
]

# ETF → 东方财富板块映射
ETF_SECTOR_MAP = {
    "512480": "半导体", "515700": "汽车整车", "515050": "通信服务",
    "159755": "电池", "159611": "电力行业", "159326": "电网设备",
    "515790": "光伏设备", "159805": "文化传媒", "159825": "农牧饲渔",
    "159870": "化学制品", "512400": "有色金属", "561360": "石油行业",
    "515220": "煤炭行业", "515210": "钢铁行业", "516970": "工程建设",
    "512170": "医疗器械", "515290": "银行", "515450": "电力行业",
    "512880": "证券", "510150": "酿酒行业", "159227": "航天航空",
    "159278": "机器人概念",
}


def _get_conn():
    if not os.path.exists(ETF_DB_PATH):
        return None
    conn = sqlite3.connect(ETF_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 基础数据 ──

def get_etf_latest_quotes() -> list[dict]:
    conn = _get_conn()
    if not conn: return []
    try:
        cur = conn.cursor()
        codes = [e["code"] for e in ETF_POOL]
        ph = ",".join(["?" for _ in codes])
        cur.execute(f"""
            SELECT q.* FROM quote q
            INNER JOIN (SELECT code, MAX(date) as max_date FROM quote
                        WHERE code IN ({ph}) GROUP BY code) latest
            ON q.code = latest.code AND q.date = latest.max_date
        """, codes)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_etf_latest_signals() -> dict[str, dict]:
    conn = _get_conn()
    if not conn: return {}
    try:
        cur = conn.cursor()
        codes = [e["code"] for e in ETF_POOL]
        ph = ",".join(["?" for _ in codes])
        cur.execute(f"""
            SELECT s.* FROM signals s
            INNER JOIN (SELECT code, MAX(date) as max_date FROM signals
                        WHERE code IN ({ph}) GROUP BY code) latest
            ON s.code = latest.code AND s.date = latest.max_date
        """, codes)
        result = {}
        for r in cur.fetchall():
            row = dict(r)
            meta = row.get("signal_meta", "")
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except (json.JSONDecodeError, ValueError): meta = {}
            result[row["code"]] = {
                "date": row["date"], "signal": row["signal"],
                "version": row.get("strategy_version", ""),
                "meta": meta,
            }
        return result
    finally:
        conn.close()


def get_etf_latest_advice() -> dict[str, dict]:
    conn = _get_conn()
    if not conn: return {}
    try:
        cur = conn.cursor()
        codes = [e["code"] for e in ETF_POOL]
        ph = ",".join(["?" for _ in codes])
        cur.execute(f"""
            SELECT a.* FROM operation_advice a
            INNER JOIN (SELECT code, MAX(date) as max_date FROM operation_advice
                        WHERE code IN ({ph}) GROUP BY code) latest
            ON a.code = latest.code AND a.date = latest.max_date
        """, codes)
        return {r["code"]: dict(r) for r in cur.fetchall()}
    finally:
        conn.close()


def get_sector_flows(date_str: str = None) -> list[dict]:
    conn = _get_conn()
    if not conn: return []
    try:
        cur = conn.cursor()
        if date_str:
            cur.execute(
                "SELECT * FROM sector_flow WHERE date = ? ORDER BY main_net_inflow DESC",
                (date_str,))
        else:
            cur.execute("""
                SELECT * FROM sector_flow
                WHERE date = (SELECT MAX(date) FROM sector_flow)
                ORDER BY main_net_inflow DESC
            """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_etf_daily_history(code: str, days: int = 60) -> list[dict]:
    conn = _get_conn()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT date, open, close, high, low, volume, nav, premium_rate
            FROM quote WHERE code = ? ORDER BY date DESC LIMIT ?
        """, (code, days))
        rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()
        return rows
    finally:
        conn.close()


# ── 大盘环境 ──

def get_market_status() -> dict:
    """获取大盘环境：SH300 实时价 + MA60 对比。"""
    try:
        url = "http://qt.gtimg.cn/q=sh000300"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
        parts = raw.split("~")
        sh300_price = float(parts[3])
        sh300_change = float(parts[32])
    except Exception:
        return {"status": "unknown", "message": "行情获取失败"}

    stock_db = r"F:\datax\stock-recommendation-platform\backtest\data\market_data.db"
    try:
        c2 = sqlite3.connect(stock_db)
        cur2 = c2.cursor()
        cur2.execute("SELECT close FROM index_daily ORDER BY trade_date DESC LIMIT 60")
        rows = cur2.fetchall()
        c2.close()
        if rows:
            ma60 = sum(r[0] for r in rows) / len(rows)
        else:
            ma60 = None
    except Exception:
        ma60 = None

    if ma60:
        diff_pct = (sh300_price - ma60) / ma60 * 100
        status = "bull" if sh300_price > ma60 else "bear"
        return {
            "status": status,
            "sh300": sh300_price,
            "ma60": round(ma60, 2),
            "diff_pct": round(diff_pct, 2),
            "change_pct": sh300_change,
            "message": f"SH300 {sh300_price:.0f} | MA60 {ma60:.0f} | {'偏强 ✅' if status == 'bull' else '偏弱 ⚠️'}",
        }
    return {"status": "unknown", "sh300": sh300_price, "message": "MA60 数据缺失"}


# ── 智能选基：多因子排名 ──

def get_etf_ranking() -> list[dict]:
    """智能选基：综合评分 + 板块资金流，排名输出。"""
    signals = get_etf_latest_signals()
    quotes = get_etf_latest_quotes()
    flows = get_sector_flows()
    advice = get_etf_latest_advice()

    quote_map = {q["code"]: q for q in quotes}
    flow_map = {}
    if flows:
        for f in flows:
            flow_map[f["name"]] = float(f.get("main_net_inflow", 0) or 0)

    result = []
    for etf in ETF_POOL:
        code = etf["code"]
        sig = signals.get(code, {})
        q = quote_map.get(code, {})
        adv = advice.get(code, {})

        # 信号分数
        meta = sig.get("meta", {})
        score = meta.get("score", 0)
        s_trend = meta.get("s_trend", 0)
        s_macd = meta.get("s_macd", 0)
        s_rsi = meta.get("s_rsi", 0)
        s_bb = meta.get("s_bb", 0)
        vol_mult = meta.get("vol_mult", 1.0)

        # 板块资金流加分
        sector_name = ETF_SECTOR_MAP.get(code, "")
        sector_inflow = flow_map.get(sector_name, 0)
        if sector_inflow > 1_000_000_000:
            flow_bonus = 10
        elif sector_inflow > 300_000_000:
            flow_bonus = 7
        elif sector_inflow > 0:
            flow_bonus = 3
        elif sector_inflow > -300_000_000:
            flow_bonus = -3
        elif sector_inflow > -1_000_000_000:
            flow_bonus = -7
        else:
            flow_bonus = -10

        final_score = score + flow_bonus

        # 信心度
        if final_score >= 70:
            confidence = "⭐⭐⭐ 高"
            confidence_level = 3
        elif final_score >= 50:
            confidence = "⭐⭐ 中"
            confidence_level = 2
        elif final_score >= 30:
            confidence = "⭐ 低"
            confidence_level = 1
        else:
            confidence = "— 观望"
            confidence_level = 0

        # 仓位建议（总资金 20 万，4 等分）
        if confidence_level >= 2 and sig.get("signal") == "BUY":
            position_advice = "建仓 5万"
        elif confidence_level == 1 and sig.get("signal") == "BUY":
            position_advice = "轻仓 2.5万"
        else:
            position_advice = "观望"

        result.append({
            "code": code, "name": etf["name"], "category": etf["category"],
            "score": round(score, 1),
            "flow_bonus": flow_bonus,
            "final_score": round(final_score, 1),
            "confidence": confidence,
            "confidence_level": confidence_level,
            "signal": sig.get("signal", "N/A"),
            "advice_raw": adv.get("advice", ""),
            "position_advice": position_advice,
            "s_trend": round(s_trend, 2),
            "s_macd": round(s_macd, 2),
            "s_rsi": round(s_rsi, 2),
            "s_bb": round(s_bb, 2),
            "vol_mult": round(vol_mult, 2),
            "sector_name": sector_name,
            "sector_inflow_yi": round(sector_inflow / 100_000_000, 2) if sector_inflow else 0,
            "close": float(q.get("close", 0) or 0),
            "nav": float(q.get("nav", 0) or 0),
            "premium_rate": round(float(q.get("premium_rate", 0) or 0) * 100, 2),
        })

    result.sort(key=lambda x: x["final_score"], reverse=True)
    return result


# ── 盈亏分析 ──

def get_etf_profit_summary() -> dict:
    """ETF 虚拟交易盈亏分析（基于历史 advice 重建交易对）。"""
    conn = _get_conn()
    if not conn: return {"trades": [], "summary": {}}
    try:
        cur = conn.cursor()
        # 取所有 advice 记录
        cur.execute("""
            SELECT code, date, advice, pnl_pct, signal_source
            FROM operation_advice ORDER BY code, date ASC
        """)
        all_advice = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM positions")
        positions = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    # 状态机重建虚拟交易
    trades = []
    holding = {}  # {code: {entry_date, entry_advice_date}}

    for adv in all_advice:
        code = adv["code"]
        a = adv["advice"]

        if a in ("建仓", "加仓", "BUY"):
            if code not in holding:
                holding[code] = {"entry_date": adv["date"], "advices": [adv]}
            else:
                holding[code]["advices"].append(adv)
        elif a in ("清仓", "SELL"):
            if code in holding:
                entry = holding.pop(code)
                trades.append({
                    "code": code,
                    "entry_date": entry["entry_date"],
                    "exit_date": adv["date"],
                    "pnl_pct": adv.get("pnl_pct"),
                })

    # 仍在持有的
    for code, h in holding.items():
        trades.append({
            "code": code, "entry_date": h["entry_date"],
            "exit_date": None, "pnl_pct": None,
            "status": "持有中",
        })

    # 汇总
    closed = [t for t in trades if t.get("exit_date")]
    win = sum(1 for t in closed if (t.get("pnl_pct") or 0) > 0)
    loss = sum(1 for t in closed if (t.get("pnl_pct") or 0) < 0)

    total_pnl = sum(t.get("pnl_pct") or 0 for t in closed)
    avg_pnl = total_pnl / len(closed) if closed else 0

    # 按 ETF 名查找
    name_map = {e["code"]: e["name"] for e in ETF_POOL}
    for t in trades:
        t["name"] = name_map.get(t["code"], t["code"])

    return {
        "trades": trades,
        "positions": positions,
        "summary": {
            "total_trades": len(closed),
            "win_count": win,
            "loss_count": loss,
            "win_rate": round(win / len(closed) * 100, 1) if closed else 0,
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(avg_pnl, 2),
            "holding_count": len(holding),
        }
    }


def get_etf_pool_with_data() -> list[dict]:
    """组装 ETF 池完整数据：行情 + 信号 + 建议（保留兼容）。"""
    quotes = get_etf_latest_quotes()
    signals = get_etf_latest_signals()
    advices = get_etf_latest_advice()
    quote_map = {q["code"]: q for q in quotes}

    result = []
    for etf in ETF_POOL:
        code = etf["code"]
        q = quote_map.get(code, {})
        sig = signals.get(code, {})
        adv = advices.get(code, {})

        close_val = float(q.get("close", 0) or 0)
        nav_val = float(q.get("nav", 0) or 0)
        premium = float(q.get("premium_rate", 0) or 0)

        meta = sig.get("meta", {})
        result.append({
            "code": code, "name": etf["name"], "category": etf["category"],
            "date": q.get("date", ""),
            "close": close_val, "nav": nav_val,
            "premium_rate": round(premium * 100, 2) if premium else None,
            "volume": float(q.get("volume", 0) or 0),
            "signal": sig.get("signal", "N/A"),
            "signal_date": sig.get("date", ""),
            "advice": adv.get("advice", "N/A"),
            "pnl_pct": adv.get("pnl_pct"),
            "score": meta.get("score", 0),
        })

    return result
