"""优质股长期持有模型 — 基本面选股 + 风险监控
用法: uv run python quality_hold.py         # 推荐+监控
      uv run python quality_hold.py alert   # 仅检查预警
"""
import pymysql, json, numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

MYSQL = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root",
         "database": "stock_recommendation", "charset": "utf8mb4"}
HOLDINGS_FILE = Path(__file__).parent / "my_stocks.json"


def get_quality_stocks():
    """用基本面筛选优质股"""
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    # 取最新两期财务数据
    cur.execute("""
        SELECT f1.ts_code, f1.roe as roe1, f2.roe as roe2, 
               f1.profit_yoy as py1, f2.profit_yoy as py2,
               f1.debt_ratio as debt, f1.rev_yoy as rev
        FROM financials f1
        JOIN financials f2 ON f1.ts_code=f2.ts_code 
            AND f1.end_date > f2.end_date
            AND YEAR(f1.end_date)=2026 AND YEAR(f2.end_date)=2025
        WHERE f1.roe IS NOT NULL AND f2.roe IS NOT NULL
          AND f1.roe > 0 AND f2.roe > 0
    """)
    fin = {r['ts_code']: r for r in cur.fetchall()}

    # 获取股票名称+上市日期
    cur.execute("SELECT stock_code, stock_name, list_date FROM stock_info")
    info = {r['stock_code']: (r['stock_name'], r['list_date']) for r in cur.fetchall()}

    # 获取市值（最新daily_basic）
    cur.execute("""
        SELECT ts_code, total_mv FROM daily_basic 
        WHERE trade_date >= '2026-05-01'
    """)
    mv_data = defaultdict(list)
    for r in cur.fetchall():
        if r['total_mv']:
            mv_data[r['ts_code']].append(float(r['total_mv']))
    conn.close()

    results = []
    for code, f in fin.items():
        if code not in info:
            continue
        name, list_date = info[code]
        # 过滤：ST + 上市<3年
        if 'ST' in (name or ''):
            continue
        if list_date:
            ld = list_date if isinstance(list_date, datetime) else datetime.strptime(str(list_date)[:10], '%Y-%m-%d')
            if (datetime.now() - ld).days < 1095:
                continue

        # 评分
        score = 0
        reasons = []

        roe_avg = (float(f['roe1']) + float(f['roe2'])) / 2
        if roe_avg >= 20:
            score += 25
            reasons.append(f"ROE{roe_avg:.0f}%")
        elif roe_avg >= 15:
            score += 20
            reasons.append(f"ROE{roe_avg:.0f}%")
        elif roe_avg >= 10:
            score += 10

        debt = float(f['debt']) if f['debt'] else 50
        if debt < 40:
            score += 15
            reasons.append(f"负债{debt:.0f}%")
        elif debt < 60:
            score += 10

        py_avg = (float(f['py1'] or 0) + float(f['py2'] or 0)) / 2
        if py_avg > 20:
            score += 15
            reasons.append(f"利润增{py_avg:.0f}%")
        elif py_avg > 0:
            score += 10

        # 市值>100亿
        mvs = mv_data.get(code, [])
        avg_mv = np.mean(mvs) / 1e8 if mvs else 0
        if avg_mv > 500:
            score += 15
            reasons.append(f"市值{avg_mv:.0f}亿")
        elif avg_mv > 100:
            score += 10

        if score >= 50:
            results.append({
                'code': code, 'name': name, 'score': score,
                'roe': roe_avg, 'debt': debt, 'profit_growth': py_avg,
                'market_cap': avg_mv, 'reasons': reasons
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def check_risk(code, name):
    """检查风险信号"""
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor()
    cur.execute("""
        SELECT trade_date, close, volume FROM daily_bars 
        WHERE stock_code=%s AND trade_date>='2026-04-01'
        ORDER BY trade_date DESC LIMIT 20
    """, (code,))
    data = [(str(r[0]), float(r[1]), float(r[2] or 0)) for r in cur.fetchall()]
    conn.close()

    if len(data) < 10:
        return []

    closes = np.array([d[1] for d in data])
    volumes = np.array([d[2] for d in data])
    dates = [d[0] for d in data]

    alerts = []

    # 1. 近期跌幅>8%
    chg5 = (closes[0] / closes[4] - 1) * 100 if len(closes) > 4 else 0
    if chg5 < -5:
        alerts.append(('🔴', f'近5日跌{chg5:.1f}%'))

    # 2. 放量下跌（恐慌）
    if chg5 < -3 and volumes[0] > np.mean(volumes[5:10]) * 1.5:
        alerts.append(('🔴', '放量恐慌'))

    # 3. 破MA60
    if len(closes) >= 60:
        cur.execute("SELECT AVG(close) FROM daily_bars WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 60", (code,))
        ma60 = float(cur.fetchone()[0])
        if closes[0] < ma60 * 0.97:
            alerts.append(('🟡', f'破60日均线'))

    # 4. 连续下跌
    if len(closes) >= 5 and all(closes[i] < closes[i+1] for i in range(4)):
        alerts.append(('🟡', '连跌5日'))

    return alerts


def cmd_recommend():
    """推荐2只最优股"""
    stocks = get_quality_stocks()
    print(f"\n  {'='*65}")
    print(f"  优质股推荐 (基本面: ROE+负债+利润增速+市值)")
    print(f"  {'='*65}")
    print(f"  {'推荐':<4} {'代码':<10} {'名称':<12} {'ROE':>6} {'负债':>6} {'利润增':>7} {'市值':>7} {'评分':>5}")
    print(f"  {'-'*60}")

    for i, s in enumerate(stocks[:10]):
        icon = '⭐' if i < 2 else '  '
        print(f"  {icon} {i+1:<2} {s['code']:<10} {s['name']:<10} "
              f"{s['roe']:>5.0f}% {s['debt']:>5.0f}% {s['profit_growth']:+6.0f}% "
              f"{s['market_cap']:>6.0f}亿 {s['score']:>4}分")

    # 你的自选股
    print(f"\n  {'='*65}")
    print(f"  你的自选股基本面")
    print(f"  {'='*65}")
    for code, name in [('601985', '中国核电'), ('601288', '农业银行'), ('600900', '长江电力')]:
        found = next((s for s in stocks if s['code'] == code), None)
        if found:
            print(f"  {code} {name:<10} ROE:{found['roe']:.0f}% 负债:{found['debt']:.0f}% "
                  f"利润增:{found['profit_growth']:+.0f}% 市值:{found['market_cap']:.0f}亿")
        else:
            print(f"  {code} {name:<10} ⚠️ 不在优质股池中(ROE<10%或数据缺失)")


def cmd_alert():
    """检查持仓风险"""
    if not HOLDINGS_FILE.exists():
        print("无持仓记录。先运行 recommend 选股，再 python quality_hold.py hold <代码> 记录")
        return

    holdings = json.loads(HOLDINGS_FILE.read_text(encoding='utf-8'))
    print(f"\n  {'='*55}")
    print(f"  持仓风险监控")
    print(f"  {'='*55}")

    any_alert = False
    for h in holdings:
        code = h['code']
        name = h.get('name', code)
        alerts = check_risk(code, name)
        if alerts:
            any_alert = True
            print(f"\n  {code} {name}:")
            for level, msg in alerts:
                print(f"    {level} {msg}")
        else:
            print(f"  {code} {name}: ✅ 无风险")

    if not any_alert:
        print(f"\n  ✅ 所有持仓安全")


def cmd_hold(code):
    """记录持仓"""
    stocks = get_quality_stocks()
    found = next((s for s in stocks if s['code'] == code), None)
    if not found:
        print(f"⚠️ {code} 不在优质股推荐中，请确认")
        return

    holds = []
    if HOLDINGS_FILE.exists():
        holds = json.loads(HOLDINGS_FILE.read_text(encoding='utf-8'))

    if any(h['code'] == code for h in holds):
        print(f"{code} 已记录")
        return

    holds.append({'code': code, 'name': found['name'], 'date': str(datetime.now().date())})
    HOLDINGS_FILE.write_text(json.dumps(holds, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ 已记录: {code} {found['name']}")
    print(f"   ROE:{found['roe']:.0f}% 负债:{found['debt']:.0f}% 利润增:{found['profit_growth']:+.0f}%")
    cmd_alert()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == 'alert':
            cmd_alert()
        elif sys.argv[1] == 'hold' and len(sys.argv) > 2:
            cmd_hold(sys.argv[2])
        else:
            print("用法: quality_hold.py [recommend|alert|hold <代码>]")
    else:
        cmd_recommend()
        # 如果已持仓，自动检查
        if HOLDINGS_FILE.exists():
            print()
            cmd_alert()
