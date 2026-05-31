"""优质股波段模型 — ROE筛选 + 支撑位买入 + 压力位卖出
逻辑：好公司+好价格，不追涨不猜底，赚确定性差价
"""
import pymysql, numpy as np
from collections import defaultdict
from datetime import datetime

MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root",
              "database": "stock_recommendation", "charset": "utf8mb4"}


def load_quality_stocks():
    """选优质股：ROE>10% + 非ST + 上市>3年 + 日均成交>5000万"""
    conn = pymysql.connect(**MYSQL_CFG)
    cur = conn.cursor()

    # 1. 先拿最近一期ROE>10%的股票
    cur.execute("""
        SELECT ts_code, MAX(end_date) as latest_date
        FROM financials 
        WHERE roe >= 10 AND end_date >= '2025-01-01'
        GROUP BY ts_code
        HAVING COUNT(*) >= 2
    """)
    quality = {r[0]: str(r[1]) for r in cur.fetchall()}
    print(f"ROE≥10%: {len(quality)}只")

    # 2. 过滤ST + 上市>3年
    cur.execute("SELECT stock_code, stock_name, list_date FROM stock_info")
    stock_info = {}
    for code, name, ld in cur.fetchall():
        if 'ST' in (name or ''):
            continue
        if ld:
            list_dt = ld if isinstance(ld, datetime) else datetime.strptime(str(ld)[:10], '%Y-%m-%d')
            if (datetime.now() - list_dt).days < 1095:  # 3年
                continue
        stock_info[code] = name

    valid = {c: stock_info[c] for c in quality if c in stock_info}
    print(f"过滤ST+次新: {len(valid)}只")

    # 3. 流动性过滤：近20日日均成交>5000万
    result = {}
    for code in list(valid.keys()):
        cur.execute("""
            SELECT AVG(close*volume) FROM daily_bars 
            WHERE stock_code=%s AND trade_date>='2026-04-01'
        """, (code,))
        avg_amt = cur.fetchone()[0]
        if avg_amt and avg_amt > 50000000:
            result[code] = valid[code]

    conn.close()
    print(f"流动性过滤: {len(result)}只")
    return result


def analyze_stock(code, name):
    """分析单只股票当前是否在好买点"""
    conn = pymysql.connect(**MYSQL_CFG)
    cur = conn.cursor()
    cur.execute("""
        SELECT trade_date, open, high, low, close, volume 
        FROM daily_bars WHERE stock_code=%s AND trade_date>='2025-01-01'
        ORDER BY trade_date
    """, (code,))
    data = [(str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0))
            for r in cur.fetchall()]
    conn.close()

    if len(data) < 60:
        return None

    closes = np.array([d[4] for d in data])
    lows = np.array([d[3] for d in data])
    highs = np.array([d[2] for d in data])
    volumes = np.array([d[5] for d in data])
    last = closes[-1]

    # Bollinger Bands (20,2)
    ma20 = np.mean(closes[-20:])
    std20 = np.std(closes[-20:])
    bb_lower = ma20 - 2 * std20
    bb_upper = ma20 + 2 * std20
    bb_pos = (last - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    # ATR
    tr = np.maximum(highs[-14:] - lows[-14:],
                    np.maximum(np.abs(highs[-14:] - closes[-15:-1]),
                               np.abs(lows[-14:] - closes[-15:-1])))
    atr = float(np.mean(tr))

    # 评分
    score = 0

    # 接近布林下轨（0-30%区间）→ 好买点
    if bb_pos < 0.3:
        score += 40
    elif bb_pos < 0.5:
        score += 20

    # MA60趋势向上（中期趋势好）
    ma60 = np.mean(closes[-60:])
    if last > ma60:
        score += 20

    # 近期缩量（卖压减弱）
    vol5 = np.mean(volumes[-5:])
    vol20 = np.mean(volumes[-20:])
    if vol5 < vol20 * 0.8:
        score += 15

    # ROE得分（已经在优质池里了，额外加分）
    score += 15  # 优质股基础分

    # 不是追高（距20日高点<10%）
    high20 = np.max(highs[-20:])
    if (last / high20 - 1) > -0.05:
        score += 10

    # 价格位置描述
    if bb_pos < 0.2:
        zone = "🔵 超卖"
    elif bb_pos < 0.4:
        zone = "🟢 低位"
    elif bb_pos < 0.6:
        zone = "🟡 中位"
    elif bb_pos < 0.8:
        zone = "🟠 高位"
    else:
        zone = "🔴 超买"

    # 预期收益
    target = bb_upper - atr
    stop = max(bb_lower - atr, last * 0.95)
    upside = (target / last - 1) * 100 if last > 0 else 0
    risk = (stop / last - 1) * 100 if last > 0 else 0

    return {
        'code': code, 'name': name,
        'score': score, 'zone': zone,
        'price': last, 'bb_lower': bb_lower, 'bb_upper': bb_upper,
        'target': target, 'stop': stop,
        'upside': upside, 'risk': risk,
        'atr_pct': atr / last * 100,
        'bb_pos': bb_pos,
    }


# 主程序
print("筛选优质股...")
stocks = load_quality_stocks()
print(f"\n分析买点...")
results = []
for code, name in stocks.items():
    r = analyze_stock(code, name)
    if r and r['score'] >= 70:
        results.append(r)

results.sort(key=lambda x: x['score'], reverse=True)

print(f"\n{'='*70}")
print(f"  优质股+好买点 (评分≥70)")
print(f"{'='*70}")
print(f"{'排名':<4} {'代码':<10} {'名称':<12} {'评分':>4} {'位置':>6} {'现价':>8} {'目标':>8} {'空间':>7} {'风险':>7}")
print(f"{'-'*70}")
for i, r in enumerate(results[:15]):
    print(f"#{i+1:<3} {r['code']:<10} {r['name']:<10} {r['score']:>4}分 "
          f"{r['zone']} {r['price']:>7.2f} {r['target']:>7.2f} "
          f"{r['upside']:+5.1f}% {r['risk']:+5.1f}%")

if not results:
    print("  没有评分≥70的——市场整体偏高，等回调")

# 你关心的几只
print(f"\n{'='*70}")
print(f"  你的自选股")
print(f"{'='*70}")
for code in ['601985', '601288', '600900']:
    r = analyze_stock(code, '')
    if r:
        name_map = {'601985': '中国核电', '601288': '农业银行', '600900': '长江电力'}
        print(f"  {code} {name_map.get(code,code)}  评分:{r['score']}分  "
              f"{r['zone']}  现价:{r['price']:.2f}  目标:{r['target']:.2f}  "
              f"空间:{r['upside']:+.1f}%  止损:{r['stop']:.2f}({r['risk']:+.1f}%)")
