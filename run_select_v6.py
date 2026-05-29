"""V6 选股策略 — 动态仓位 + 复利 + 移动止盈
数据源: SQLite (market_data.db) + 搜狐财经实时更新
大盘判断: 沪深300 MA20/MA60
仓位: 牛市5只 / 中性3只 / 熊市2只
止损: 固定7%  止盈: 涨8%激活, 回撤3%卖出  最长持有20天
"""
import os, sys, time, json, sqlite3
import numpy as np
from datetime import date, datetime, timedelta
from pathlib import Path

# 禁用代理
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

import requests

# ============================================================
# 配置
# ============================================================
DB_PATH = Path(__file__).parent / "backtest" / "data" / "market_data.db"
STOP_LOSS = -0.07        # 固定7%止损
TRAIL_ACTIVATE = 0.08    # 涨8%激活移动止盈
TRAIL_BACK_PCT = 0.03    # 回撤3%卖出
MAX_HOLD_DAYS = 20       # 最长持有20天
SCORE_THRESHOLD = 0.02   # 最低评分阈值

# ============================================================
# 大盘状态判断
# ============================================================
def get_market_state(conn):
    """根据沪深300 MA20/MA60判断牛熊"""
    cur = conn.execute(
        "SELECT trade_date, close FROM index_daily ORDER BY trade_date DESC LIMIT 80"
    )
    rows = cur.fetchall()
    if len(rows) < 60:
        return "中性", 3, {}
    rows.reverse()
    closes = [r[1] for r in rows]
    dates = [r[0] for r in rows]
    
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    latest = closes[-1]
    latest_date = dates[-1]
    
    if latest >= ma60 and ma20 >= ma60:
        state = "牛市"
        max_pos = 5
    elif latest >= ma60:
        state = "中性"
        max_pos = 3
    else:
        state = "熊市"
        max_pos = 2
    
    info = {
        "date": latest_date,
        "close": latest,
        "ma20": ma20,
        "ma60": ma60,
        "state": state,
        "max_pos": max_pos,
    }
    return state, max_pos, info


# ============================================================
# V6 评分函数
# ============================================================
def score_stock_v6(bars):
    """对一只股票评分，bars = [(date, open, high, low, close, volume), ...]
    返回 score 或 None（不通过筛选）
    """
    if len(bars) < 61:
        return None, {}
    
    idx = len(bars) - 1
    close = bars[idx][4]
    if close < 3:
        return None, {}
    
    # 涨幅
    c5 = bars[idx-5][4]
    c10 = bars[idx-10][4]
    c20 = bars[idx-20][4]
    c60 = bars[max(0, idx-60)][4]
    if c5 == 0 or c10 == 0 or c20 == 0 or c60 == 0:
        return None, {}
    
    ret5 = (close - c5) / c5
    ret10 = (close - c10) / c10
    ret20 = (close - c20) / c20
    
    # 不追涨停
    prev_c = bars[idx-1][4]
    if prev_c > 0 and (close - prev_c) / prev_c > 0.095:
        return None, {}
    
    # 过热过滤
    if ret5 > 0.12 or ret20 > 0.30:
        return None, {}
    if ret5 < -0.03:
        return None, {}
    
    # 成交量
    vol_20 = np.mean([bars[idx-j][5] for j in range(20)])
    if vol_20 < 3000:
        return None, {}
    vol_5 = np.mean([bars[idx-j][5] for j in range(5)])
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
    if vol_ratio < 0.8:
        return None, {}
    
    # 均线
    ma5 = np.mean([bars[idx-j][4] for j in range(5)])
    ma20 = np.mean([bars[idx-j][4] for j in range(20)])
    ma60 = np.mean([bars[idx-j][4] for j in range(min(60, idx+1))])
    
    if close < ma5 or close < ma20:
        return None, {}
    if ma5 < ma20:
        return None, {}
    
    trend = (0.5 if ma20 > ma60 else 0) + (0.5 if ma5 > ma20 else 0)
    
    # 波动率
    rets = []
    for j in range(1, 21):
        if bars[idx-j-1][4] > 0:
            rets.append((bars[idx-j][4] - bars[idx-j-1][4]) / bars[idx-j-1][4])
    if rets and np.std(rets) > 0.04:
        return None, {}
    
    # 上影线
    hi, op = bars[idx][2], bars[idx][1]
    body = abs(close - op)
    upper = hi - max(close, op)
    if body > 0 and upper > 1.5 * body:
        return None, {}
    
    # 评分: 动量45% + 量价20% + 趋势35%
    momentum = (ret5 * 2 + ret10 + ret20 * 0.5) / 3.5
    score = momentum * 0.45 + min(vol_ratio, 2.5) / 2.5 * 0.20 + trend * 0.35
    
    if score <= 0:
        return None, {}
    
    details = {
        "ret5": ret5 * 100,
        "ret10": ret10 * 100,
        "ret20": ret20 * 100,
        "vol_ratio": vol_ratio,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "close": close,
        "vol_std": np.std(rets) * 100 if rets else 0,
    }
    return score, details


# ============================================================
# 出货信号检测
# ============================================================
def check_distribution_signals(bars):
    """检查最后一天是否有出货信号"""
    if len(bars) < 5:
        return []
    
    warnings = []
    last = bars[-1]
    cl, op, hi, lo = last[4], last[1], last[2], last[3]
    body = abs(cl - op)
    upper = hi - max(cl, op)
    
    # 长上影线
    if body > 0 and upper > 2 * body:
        warnings.append("长上影线")
    
    # 高开低走大阴线
    if hi > lo and cl < op and (op - cl) / (hi - lo) > 0.6:
        warnings.append("高开低走")
    
    # 放量滞涨
    if len(bars) >= 5:
        vol_today = bars[-1][5]
        vol_avg = np.mean([b[5] for b in bars[-5:-1]])
        if vol_avg > 0 and vol_today > vol_avg * 1.5:
            chg = (bars[-1][4] - bars[-2][4]) / bars[-2][4] if bars[-2][4] > 0 else 0
            if chg < 0.01:
                warnings.append("放量滞涨")
    
    return warnings


# ============================================================
# 搜狐实时行情更新（盘中用）
# ============================================================
def update_today_from_sohu(conn, codes_to_update):
    """从搜狐拉取今日行情更新到DB（盘中使用）"""
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    
    today_str = date.today().strftime("%Y%m%d")
    updated = 0
    
    for i in range(0, len(codes_to_update), 20):
        batch = codes_to_update[i:i+20]
        for code in batch:
            prefix = "cn_" if code.startswith("6") else "cn_"
            url = f"https://q.stock.sohu.com/hisHq?code={prefix}{code}&start={today_str}&end={today_str}&stat=1&order=D&period=d&rt=json"
            try:
                r = session.get(url, timeout=8)
                data = r.json()
                if data and isinstance(data, list) and data[0].get("hq"):
                    for row in data[0]["hq"]:
                        d = row[0].replace("-", "")
                        op, cl, chg, chg_pct, lo, hi, vol, amount = row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8]
                        conn.execute(
                            "INSERT OR REPLACE INTO daily_bars (stock_code, trade_date, open, high, low, close, volume, turnover) VALUES (?,?,?,?,?,?,?,?)",
                            (code, d, float(op), float(hi), float(lo), float(cl), float(vol.replace(",", "")), float(amount.replace(",", "")))
                        )
                        updated += 1
            except Exception:
                pass
        time.sleep(0.1)
    
    if updated:
        conn.commit()
    return updated


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 60)
    print(f"  V6 量化选股  {date.today().isoformat()}")
    print(f"  策略: 动态仓位 + 复利 + 移动止盈")
    print("=" * 60)
    
    conn = sqlite3.connect(str(DB_PATH))
    
    # 1) 大盘状态
    state, max_pos, info = get_market_state(conn)
    print(f"\n[大盘状态] {state} (最多持 {max_pos} 只)")
    print(f"  沪深300: {info['close']:.2f} (日期: {info['date']})")
    print(f"  MA20: {info['ma20']:.2f}  MA60: {info['ma60']:.2f}")
    print(f"  收盘{'>' if info['close']>=info['ma60'] else '<'}MA60  MA20{'>' if info['ma20']>=info['ma60'] else '<'}MA60")
    
    # 2) 加载股票数据
    print(f"\n[选股] 加载数据...")
    _cutoff = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
    cur = conn.execute(
        "SELECT stock_code, trade_date, open, high, low, close, volume "
        "FROM daily_bars WHERE trade_date >= ? ORDER BY stock_code, trade_date",
        (_cutoff,)
    )
    
    from collections import defaultdict
    stock_data = defaultdict(list)
    for row in cur:
        code, dt, op, hi, lo, cl, vol = row
        if op and cl and hi and lo:
            stock_data[code].append((dt, float(op), float(hi), float(lo), float(cl), float(vol) if vol else 0))
    
    print(f"  加载 {len(stock_data)} 只股票")
    
    # 3) 获取股票名称
    code_names = {}
    cur = conn.execute("SELECT stock_code, stock_name FROM stock_info")
    for row in cur:
        code_names[row[0]] = row[1]
    
    # 4) V6评分
    print(f"\n[评分] V6多因子评分...")
    candidates = []
    for code, bars in stock_data.items():
        if len(bars) < 61:
            continue
        # 排除ST
        name = code_names.get(code, "")
        if "ST" in name or "退" in name:
            continue
        
        score, details = score_stock_v6(bars)
        if score and score >= SCORE_THRESHOLD:
            warnings = check_distribution_signals(bars)
            candidates.append({
                "code": code,
                "name": name,
                "score": score,
                "warnings": warnings,
                **details,
            })
    
    candidates.sort(key=lambda x: -x["score"])
    
    # 5) 输出结果
    print(f"  通过筛选: {len(candidates)} 只")
    
    # 分为推荐和备选
    clean = [c for c in candidates if not c["warnings"]]
    warned = [c for c in candidates if c["warnings"]]
    
    print(f"\n{'='*60}")
    print(f"  推荐买入 TOP {max_pos}（无出货信号）")
    print(f"{'='*60}\n")
    
    # 假设20万本金
    capital = 200000
    slot_size = capital / max_pos
    
    for i, c in enumerate(clean[:max_pos]):
        shares = int(slot_size / c["close"] / 100) * 100  # 整手
        cost = shares * c["close"]
        stop_price = c["close"] * (1 + STOP_LOSS)
        trail_price = c["close"] * (1 + TRAIL_ACTIVATE)
        
        print(f"  {i+1}. [{c['code']}] {c['name']}  评分 {c['score']:.3f}")
        print(f"     现价 {c['close']:.2f}  5日{c['ret5']:+.1f}%  10日{c['ret10']:+.1f}%  量比{c['vol_ratio']:.2f}")
        print(f"     买入: {shares}股 × {c['close']:.2f} = {cost:.0f}元")
        print(f"     止损: {stop_price:.2f} (亏7%)")
        print(f"     移动止盈激活: {trail_price:.2f} (涨8%后回撤3%卖)")
        print(f"     最长持有: {MAX_HOLD_DAYS}天")
        print()
    
    if warned:
        print(f"\n{'─'*60}")
        print(f"  有出货信号（谨慎）:")
        print(f"{'─'*60}")
        for c in warned[:5]:
            print(f"  [{c['code']}] {c['name']}  评分{c['score']:.3f}  ⚠️ {'、'.join(c['warnings'])}")
    
    # 备选列表
    if len(clean) > max_pos:
        print(f"\n{'─'*60}")
        print(f"  备选（如推荐股高开>3%不追，用备选替换）:")
        print(f"{'─'*60}")
        for c in clean[max_pos:max_pos+5]:
            print(f"  [{c['code']}] {c['name']}  评分{c['score']:.3f}  现价{c['close']:.2f}  5日{c['ret5']:+.1f}%")
    
    # 操作提示
    print(f"\n{'='*60}")
    print(f"  操作规则")
    print(f"{'='*60}")
    print(f"  大盘: {state} → 持仓上限 {max_pos} 只")
    print(f"  每只仓位: {slot_size:.0f}元 (总资产/{max_pos})")
    print(f"  建仓节奏: 每天买1只，{max_pos}天建满仓")
    print(f"  止损: 买入价×0.93 (固定7%)")
    print(f"  止盈: 涨8%后激活，最高价×0.97 跟踪")
    print(f"  超时: 持仓满20天强制卖出")
    print(f"{'='*60}")
    
    conn.close()
    return candidates


if __name__ == "__main__":
    main()
