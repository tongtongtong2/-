"""每日个股推荐 — 结合基本面+支撑位+资金流向
用法: uv run python daily_pick.py
"""
import pymysql, numpy as np, json, os, requests, time
from datetime import datetime
from collections import defaultdict

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root","database":"stock_recommendation","charset":"utf8mb4"}

# 你的核心池
WATCH = {
    '601985':'中国核电','601288':'农业银行','600900':'长江电力',
    '600036':'招商银行','601088':'中国神华','600519':'贵州茅台',
    '601857':'中国石油','601398':'工商银行','000858':'五粮液'
}

def get_fundamentals():
    """获取ROE+负债率"""
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT ts_code, MAX(end_date) as d FROM financials
        WHERE roe IS NOT NULL AND end_date>='2026-01-01'
        GROUP BY ts_code
    """)
    latest = {r['ts_code']: r['d'] for r in cur.fetchall()}
    
    cur.execute("""
        SELECT ts_code, roe, debt_ratio, profit_yoy, rev_yoy 
        FROM financials WHERE (ts_code, end_date) IN (
            SELECT ts_code, MAX(end_date) FROM financials 
            WHERE end_date>='2026-01-01' GROUP BY ts_code
        )
    """)
    fin = {r['ts_code']:r for r in cur.fetchall()}
    conn.close()
    return fin

def get_technicals(code):
    """获取技术指标"""
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor()
    cur.execute("""
        SELECT trade_date, close, high, low, volume FROM daily_bars
        WHERE stock_code=%s AND trade_date>='2026-04-01'
        ORDER BY trade_date DESC
    """, (code,))
    data = [(str(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4] or 0)) for r in cur.fetchall()]
    conn.close()
    if len(data)<20: return None
    
    closes = np.array([d[1] for d in data])
    highs = np.array([d[2] for d in data])
    lows = np.array([d[3] for d in data])
    vols = np.array([d[4] for d in data])
    
    last = closes[0]
    ma20 = np.mean(closes[:20])
    support = np.min(lows[:20])
    resistance = np.max(highs[:20])
    
    # Bollinger position
    bb_lower = ma20 - 2*np.std(closes[:20])
    bb_upper = ma20 + 2*np.std(closes[:20])
    bb_pos = (last-bb_lower)/(bb_upper-bb_lower) if bb_upper>bb_lower else 0.5
    
    # Volume trend
    vol5 = np.mean(vols[:5])
    vol20 = np.mean(vols[5:20]) if len(vols)>=20 else vol5
    vol_ratio = vol5/vol20
    
    return {
        'price':last, 'ma20':ma20, 'support':support, 'resistance':resistance,
        'bb_lower':bb_lower, 'bb_upper':bb_upper, 'bb_pos':bb_pos,
        'vol_ratio':vol_ratio, 'chg5':(closes[0]/closes[4]-1)*100 if len(closes)>4 else 0,
        'chg20':(closes[0]/closes[-1]-1)*100 if len(closes)>20 else 0,
    }

# 主程序
fin = get_fundamentals()
results = []

for code, name in WATCH.items():
    tech = get_technicals(code)
    f = fin.get(code, {})
    
    score = 0
    reasons = []
    
    # 基本面
    roe = float(f.get('roe',0)) if f.get('roe') else 0
    debt = float(f.get('debt_ratio',50)) if f.get('debt_ratio') else 50
    profit = float(f.get('profit_yoy',0)) if f.get('profit_yoy') else 0
    
    if roe >= 15: score+=25; reasons.append(f'ROE{roe:.0f}%')
    elif roe >= 10: score+=15; reasons.append(f'ROE{roe:.0f}%')
    if debt < 40: score+=15; reasons.append(f'负债{debt:.0f}%')
    elif debt < 60: score+=10
    if profit > 20: score+=10; reasons.append(f'利润增{profit:.0f}%')
    
    # 技术面（买点在低位）
    if tech is None:
        results.append({'code':code,'name':name,'score':0,'price':0,'roe':roe,'debt':debt,'profit':profit,'buy':0,'target':0,'upside':0,'bb_pos':0,'reasons':['数据不足']})
        continue
    if tech['bb_pos'] < 0.3: score+=20; reasons.append('布林下轨')
    elif tech['bb_pos'] < 0.5: score+=10; reasons.append('偏低')
    if tech['vol_ratio']<0.7: score+=10; reasons.append('缩量')
    if tech['chg20']<-5: score+=10; reasons.append('超跌')
    
    buy_price = round(tech['bb_lower'],2)
    target = round(tech['bb_upper'],2)
    
    results.append({
        'code':code,'name':name,'score':score,
        'price':tech['price'],'roe':roe,'debt':debt,'profit':profit,
        'buy':buy_price,'target':target,
        'upside':(target/tech['price']-1)*100,
        'bb_pos':tech['bb_pos']*100,
        'reasons':reasons
    })

results.sort(key=lambda x:x['score'],reverse=True)

print(f"\n{'='*65}")
print(f"  周一推荐 — {datetime.now().strftime('%Y-%m-%d')}")
print(f"{'='*65}")
print(f"  {'排名':<4} {'代码':<8} {'名称':<8} {'评分':>4} {'现价':>7} {'买点':>7} {'目标':>7} {'空间':>6}")
print(f"  {'-'*60}")
for i,r in enumerate(results):
    icon = '⭐' if i<2 else '  '
    print(f"  {icon} #{i+1}  {r['code']:<8} {r['name']:<8} {r['score']:>4}分 "
          f"{r['price']:>6.2f} {r['buy']:>6.2f} {r['target']:>6.2f} {r['upside']:+5.1f}%")
    if r['reasons']:
        print(f"       {' '.join(r['reasons'])}")

# 推荐
print(f"\n  ✅ 明天买: {results[0]['code']} {results[0]['name']}")
print(f"     挂单: {results[0]['buy']}")
print(f"     止损: {results[0]['buy']*0.97:.2f} (-3%)")
print(f"     目标: {results[0]['target']} (+{results[0]['upside']:.0f}%)")
