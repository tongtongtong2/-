"""A股选股模型 — 三道筛子从5000只缩到20只
数据源: MySQL stock_recommendation (已验证准确)
"""
import pymysql, numpy as np
from datetime import datetime
from collections import defaultdict

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root","database":"stock_recommendation","charset":"utf8mb4"}

def run():
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # ═══ 第一道筛: 基本面 ═══
    print("第一道: 基本面筛选...")
    cur.execute("""
        SELECT f.ts_code, f.roe, f.debt_ratio, f.profit_yoy, f.rev_yoy,
               s.stock_name, s.list_date
        FROM financials f
        JOIN stock_info s ON f.ts_code=s.stock_code
        WHERE f.end_date = (SELECT MAX(end_date) FROM financials WHERE ts_code=f.ts_code)
          AND f.roe >= 10
          AND f.debt_ratio <= 60
    """)
    passed = {}
    for r in cur.fetchall():
        code = r['ts_code']
        name = r['stock_name']
        # 过滤ST
        if 'ST' in (name or ''): continue
        # 上市>3年
        ld = r['list_date']
        if ld:
            list_dt = ld if isinstance(ld, datetime) else datetime.strptime(str(ld)[:10], '%Y-%m-%d')
            if (datetime.now() - list_dt).days < 1095: continue
        passed[code] = {
            'name': name,
            'roe': float(r['roe']), 'debt': float(r['debt_ratio']),
            'profit': float(r['profit_yoy'] or 0), 'rev': float(r['rev_yoy'] or 0)
        }
    print(f"  通过: {len(passed)}只 (ROE≥10% + 负债≤60% + 非ST + 上市>3年)")
    
    # ═══ 第二道筛: 流动性 ═══
    print("第二道: 流动性筛选...")
    cur.execute("""
        SELECT ts_code, AVG(total_mv) as avg_mv
        FROM daily_basic
        WHERE trade_date >= '2026-05-01'
        GROUP BY ts_code
        HAVING AVG(total_mv) >= 1000000
    """)  # 100亿市值 (单位:万元)
    big_cap = {r['ts_code'] for r in cur.fetchall()}
    
    cur.execute("""
        SELECT stock_code, AVG(close*volume) as avg_amt
        FROM daily_bars
        WHERE trade_date >= '2026-04-01'
        GROUP BY stock_code
        HAVING AVG(close*volume) >= 50000000
    """)  # 日均5000万
    liquid = {r['stock_code'] for r in cur.fetchall()}
    
    passed2 = {c: v for c, v in passed.items() if c in big_cap and c in liquid}
    print(f"  通过: {len(passed2)}只 (市值>100亿 + 日均成交>5000万)")
    
    # ═══ 第三道筛: 技术面位置 ═══
    print("第三道: 技术面位置...")
    results = []
    for code, info in passed2.items():
        cur.execute("""
            SELECT close, high, low FROM daily_bars
            WHERE stock_code=%s AND trade_date>='2026-04-01'
            ORDER BY trade_date DESC
        """, (code,))
        raw = cur.fetchall()
        if len(raw) < 20: continue
        data = [(float(r['close'] if isinstance(r,dict) else r[0]), 
                 float(r['high'] if isinstance(r,dict) else r[1]), 
                 float(r['low'] if isinstance(r,dict) else r[2])) for r in raw]
        if len(data) < 20: continue
        
        closes = np.array([d[0] for d in data])
        highs = np.array([d[1] for d in data])
        lows = np.array([d[2] for d in data])
        
        last = closes[0]
        ma20 = np.mean(closes[:20])
        std20 = np.std(closes[:20])
        bb_lower = ma20 - 2 * std20
        bb_upper = ma20 + 2 * std20
        bb_pos = (last - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
        
        # 评分: 基本面50 + 位置50
        f_score = min(50, info['roe'] * 2 + (60 - info['debt']) * 0.3 + max(0, info['profit']) * 0.3)
        t_score = (1 - bb_pos) * 50 if bb_pos < 0.5 else max(0, (1 - bb_pos) * 30)
        total = f_score + t_score
        
        results.append({
            'code': code, 'name': info['name'],
            'roe': info['roe'], 'debt': info['debt'], 'profit': info['profit'],
            'price': last, 'bb_pos': bb_pos * 100,
            'f_score': f_score, 't_score': t_score,
            'total': total, 'target': bb_upper, 'buy': bb_lower
        })
    
    results.sort(key=lambda x: x['total'], reverse=True)
    conn.close()
    
    # 输出
    print(f"\n{'='*70}")
    print(f"  最终推荐 TOP20 (从{len(passed2)}只中选出)")
    print(f"{'='*70}")
    print(f"{'排名':<4} {'代码':<10} {'名称':<8} {'总':>4} {'ROE':>5} {'负债':>5} {'利润增':>6} {'现价':>7} {'位置':>6}")
    print(f"{'-'*65}")
    
    for i, r in enumerate(results[:20]):
        icon = '⭐' if i < 5 else '  '
        pos = '低位' if r['bb_pos'] < 30 else '中位' if r['bb_pos'] < 60 else '高位'
        print(f"{icon} {i+1:<2} {r['code']:<10} {r['name']:<8} {r['total']:>4.0f} "
              f"{r['roe']:>5.0f}% {r['debt']:>5.0f}% {r['profit']:+6.0f}% "
              f"{r['price']:>7.2f} {pos}")
    
    # 你的持仓
    print(f"\n{'='*70}")
    print(f"  你的自选股位置")
    print(f"{'='*70}")
    for code in ['601985', '601288', '600900']:
        found = next((r for r in results if r['code'] == code), None)
        if found:
            print(f"  {code} {found['name']}  总分:{found['total']:.0f}  "
                  f"现价:{found['price']:.2f}  布林位置:{found['bb_pos']:.0f}%  "
                  f"买点:{found['buy']:.2f}  目标:{found['target']:.2f}")
    
    return results

if __name__ == "__main__":
    run()
