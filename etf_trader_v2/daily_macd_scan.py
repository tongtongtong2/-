"""每日MACD全市场扫描 — 纯MACD金叉策略

每天3:30跑一遍，输出：
1. 已金叉的（别追）
2. 快金叉的（差<0.01，明天重点盯）
3. 还要等的

用法: python daily_macd_scan.py
"""
import json, time, numpy as np
import urllib.request

POOL = [
    # ETF
    ("510500","sh","中证500"),("159996","sz","家电"),("515790","sh","光伏华泰"),
    ("588000","sh","科创50"),("510300","sh","沪深300"),("515700","sh","新能源车"),
    ("159755","sz","电池"),("510050","sh","上证50"),("159920","sz","恒生ETF"),
    ("159915","sz","创业板"),("159949","sz","创业板50"),("516880","sh","光伏银华"),
    ("515880","sh","通信"),("159559","sz","机器人景顺"),("510900","sh","H股ETF"),
    ("159611","sz","电力ETF"),("561560","sh","电力华夏"),
    # 个股
    ("601088","sh","中国神华"),("002747","sz","埃斯顿"),
    ("601857","sh","中国石油"),("600519","sh","贵州茅台"),
    ("003816","sz","中国广核"),("601288","sh","农业银行"),
]

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'}

def fetch(code, market):
    url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={market}{code}&scale=240&ma=no&datalen=80'
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode('gbk'))
    return np.array([float(d['close']) for d in data])

def calc_macd(closes):
    n = len(closes)
    e12 = np.zeros(n); e26 = np.zeros(n)
    e12[0] = closes[0]; e26[0] = closes[0]
    for i in range(1, n):
        e12[i] = closes[i] * 2/13 + e12[i-1] * 11/13
        e26[i] = closes[i] * 2/27 + e26[i-1] * 25/27
    d = e12 - e26
    dea = np.zeros(n)
    for i in range(1, n):
        dea[i] = d[i] * 2/10 + dea[i-1] * 8/10
    hist = 2 * (d - dea)
    return d, dea, hist

results = []
for code, market, name in POOL:
    closes = fetch(code, market)
    d, dea, hist = calc_macd(closes)
    n = len(closes)

    diff = d[-1] - dea[-1]
    chg5 = (closes[-1] / closes[-6] - 1) * 100 if n >= 6 else 0
    chg20 = (closes[-1] / closes[-21] - 1) * 100 if n >= 21 else 0

    bb = closes[-20:]
    ma20 = np.mean(bb)
    std20 = np.std(bb)
    lower = ma20 - 2 * std20
    upper = ma20 + 2 * std20
    bb_pct = (closes[-1] - lower) / (upper - lower) * 100 if upper > lower else 50

    results.append({
        'code': code, 'name': name, 'price': closes[-1],
        'dif': d[-1], 'dea': dea[-1], 'hist': hist[-1],
        'diff': diff, 'chg5': chg5, 'chg20': chg20,
        'bb_pct': bb_pct,
        'state': '金叉' if diff > 0 else '死叉'
    })
    time.sleep(0.12)

results.sort(key=lambda r: (0 if r['diff'] > 0 else 1, -abs(r['diff']) if r['diff'] > 0 else abs(r['diff'])))

print("=" * 90)
print("  每日MACD全市场扫描")
print("=" * 90)

print(f"\n  🟢 已金叉（别追，等下次回调）:")
print(f"  {'代码':<10} {'名称':<10} {'现价':>7} {'DIF':>8} {'DEA':>8} {'差':>8} {'5日':>6} {'布林':>5}")
for r in results:
    if r['diff'] > 0:
        print(f"  {r['code']:<10} {r['name']:<10} {r['price']:>7.3f} {r['dif']:+8.4f} {r['dea']:+8.4f} {r['diff']:+8.4f} {r['chg5']:+5.1f}% {r['bb_pct']:>4.0f}%")

print(f"\n  🔥 差<0.01 即将翻红（明天2:50重点盯）:")
print(f"  {'代码':<10} {'名称':<10} {'现价':>7} {'DIF':>8} {'DEA':>8} {'差':>8} {'5日':>6} {'布林':>5}")
for r in results:
    if r['diff'] < 0 and abs(r['diff']) < 0.01:
        print(f"  {r['code']:<10} {r['name']:<10} {r['price']:>7.3f} {r['dif']:+8.4f} {r['dea']:+8.4f} {r['diff']:+8.4f} {r['chg5']:+5.1f}% {r['bb_pct']:>4.0f}%")

print(f"\n  ⏳ 还要等:")
print(f"  {'代码':<10} {'名称':<10} {'现价':>7} {'DIF':>8} {'DEA':>8} {'差':>8} {'5日':>6}")
for r in results:
    if r['diff'] < 0 and abs(r['diff']) >= 0.01:
        print(f"  {r['code']:<10} {r['name']:<10} {r['price']:>7.3f} {r['dif']:+8.4f} {r['dea']:+8.4f} {r['diff']:+8.4f} {r['chg5']:+5.1f}%")

# 策略提示
golden = [r for r in results if r['diff'] > 0]
near = [r for r in results if r['diff'] < 0 and abs(r['diff']) < 0.01]
print(f"\n  策略: 纯MACD金叉 | 30天持有 | -8%止损")
print(f"  金叉中: {len(golden)}只 | 即将: {len(near)}只")
if near:
    print(f"  明天2:50 → {' / '.join(r['name'] for r in near[:4])} 谁翻红买谁")
else:
    print(f"  明天2:50 → 全死叉，现金为王")
