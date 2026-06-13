#!/usr/bin/env python3
"""
全市场ETF评分扫描 — 多因子MACD模型
每天收盘后运行，输出评分≥4.0的买入候选

因子:
  F1: MACD金叉 (必要条件)
  F2: 趋势 (价格>MA200, MA50>MA200)
  F3: 量能放大 (量比>1.0)
  F4: 非V型反转
  F5: MACD柱强度
  F6: 低波动 (ATR%)

规则:
  评分≥4.0 → 买入候选
  T+1开盘>昨收×1.02 → 跳过
  -8%止损 / 30天持有 / 15天冷却 / 单票≤30%

数据: MySQL(历史) + 腾讯API(补最近)
"""

import pymysql
import urllib.request
import json
import sys
from datetime import datetime

# ===== CONFIG =====
MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root", "database": "etf_trader"}
SCORE_THRESHOLD = 4.0
GAP_LIMIT = 2.0  # T+1跳空>2%不买
TRADING_DAYS_HISTORY = 200  # 至少需要200天历史

# ===== INDICATORS =====

def sma(series, period):
    result = []; acc = 0
    for i in range(len(series)):
        acc += series[i]
        if i >= period: acc -= series[i-period]; result.append(acc/period)
        else: result.append(acc/(i+1))
    return result

def ema(series, period):
    k = 2/(period+1)
    result = [series[0]]
    for v in series[1:]: result.append(v*k + result[-1]*(1-k))
    return result

def fetch_tencent(code):
    """拉取腾讯财经最近16天日线"""
    prefix = 'sz' if code.startswith('1') else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,16,qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        d = data.get('data', {})
        if isinstance(d, dict):
            key = f'{prefix}{code}'
            # 个股用qfqday, ETF用day
            kl = d.get(key, {}).get('day') or d.get(key, {}).get('qfqday', [])
            return kl
    except Exception as e:
        pass
    return []

def compute_score(i, closes, opens, highs, lows, volumes, dif, dea, bar, ma50, ma200, ma20_vol, atr_pct):
    """计算6因子评分"""
    score = 1.0  # F1: MACD金叉(调用前已确认)
    
    # F2: 趋势
    if closes[i] > ma200[i]:
        score += 1.0 if ma50[i] > ma200[i] else 0.5
    
    # F3: 量能
    vr = volumes[i] / ma20_vol[i] if ma20_vol[i] > 0 else 0
    if vr >= 1.5: score += 1.0
    elif vr >= 1.0: score += 0.5
    
    # F4: 非V反
    lookback = min(i, 120)
    w = closes[i-lookback:i+1]
    pk = max(w); tr = min(w)
    dd = (pk-tr)/pk*100; ti = w.index(tr)
    rec = (closes[i]-tr)/tr*100 if tr>0 else 0
    is_v = (dd >= 20 and len(w)-ti <= 60 and rec > 10)
    if not is_v: score += 1.0
    
    # F5: 柱强度
    bs = abs(bar[i]) / closes[i] * 100
    if bs > 2: score += 1.0
    elif bs > 1: score += 0.5
    
    # F6: 低波动
    atr = atr_pct[i]
    if atr < 2: score += 1.0
    elif atr < 3: score += 0.5
    
    return round(score, 1)


def scan_all():
    """主扫描函数"""
    print(f"=== 全市场ETF评分扫描 === {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # 1. 获取ETF列表
    conn = pymysql.connect(**MYSQL_CFG, charset='utf8mb4')
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT code FROM quote ORDER BY code")
    all_codes = [r[0] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    
    print(f"ETF总数: {len(all_codes)}")
    
    # 2. 拉取腾讯最新数据
    print("拉取最新行情...")
    tencent_data = {}
    for code in all_codes:
        kl = fetch_tencent(code)
        if kl:
            tencent_data[code] = kl
    
    print(f"获取到: {len(tencent_data)}只")
    
    # 3. 逐只扫描
    buy_candidates = []
    near_candidates = []
    
    for code in all_codes:
        if code not in tencent_data:
            continue
        
        # MySQL历史数据
        conn = pymysql.connect(**MYSQL_CFG, charset='utf8mb4')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date, open, high, low, close, volume FROM quote WHERE code=%s ORDER BY date",
            (code,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if len(rows) < TRADING_DAYS_HISTORY:
            continue
        
        dates = [str(r[0]) for r in rows]
        opens = [float(r[1] or 0) for r in rows]
        highs = [float(r[2] or 0) for r in rows]
        lows = [float(r[3] or 0) for r in rows]
        closes = [float(r[4] or 0) for r in rows]
        volumes = [float(r[5] or 0) for r in rows]
        
        # 合并腾讯新数据
        for k in tencent_data[code]:
            if k[0] > dates[-1]:
                dates.append(k[0])
                opens.append(float(k[1]))
                closes.append(float(k[2]))
                highs.append(float(k[3]))
                lows.append(float(k[4]))
                volumes.append(float(k[5]))
        
        n = len(closes)
        
        # MACD
        e12 = ema(closes, 12); e26 = ema(closes, 26)
        dif = [e12[j]-e26[j] for j in range(n)]
        dea = ema(dif, 9)
        bar = [2*(dif[j]-dea[j]) for j in range(n)]
        
        # 均线 & ATR
        ma50 = sma(closes, 50); ma200 = sma(closes, 200)
        ma20_vol = sma(volumes, 20)
        
        tr_list = []
        for j in range(n):
            tr = highs[j]-lows[j] if j==0 else max(
                highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
            tr_list.append(tr)
        atr_vals = sma(tr_list, 14)
        atr_pct = [atr_vals[j]/closes[j]*100 if closes[j]>0 else 99 for j in range(n)]
        
        i = n - 1
        
        # 金叉判断
        is_golden_now = dif[i] > dea[i] and bar[i] > 0
        was_golden = dif[i-1] > dea[i-1] and bar[i-1] > 0
        new_golden = is_golden_now and not was_golden
        
        # 近金叉记录
        dif_dea_gap = dif[i] - dea[i]
        if not new_golden and dif_dea_gap > -0.015:
            near_candidates.append({
                'code': code, 'close': closes[i],
                'dif': dif[i], 'dea': dea[i], 'gap': dif_dea_gap,
                'bar': bar[i],
            })
        
        if not new_golden:
            continue
        
        # 计算评分
        score = compute_score(i, closes, opens, highs, lows, volumes,
                            dif, dea, bar, ma50, ma200, ma20_vol, atr_pct)
        
        if score < SCORE_THRESHOLD:
            continue
        
        today_chg = (closes[i]/closes[i-1]-1)*100
        buy_candidates.append({
            'code': code, 'date': dates[i], 'close': closes[i],
            'score': score, 'chg': today_chg,
            'dif': dif[i], 'dea': dea[i], 'bar': bar[i],
            'ma50': ma50[i], 'ma200': ma200[i],
            'vr': volumes[i]/ma20_vol[i] if ma20_vol[i]>0 else 0,
            'atr': atr_pct[i],
            'gap_limit': closes[i] * (1 + GAP_LIMIT/100),
        })
    
    # 排序
    buy_candidates.sort(key=lambda x: -x['score'])
    near_candidates.sort(key=lambda x: x['gap'])
    
    # ===== 输出 =====
    print(f"\n{'='*70}")
    print(f"🟢 买入候选 — 评分≥{SCORE_THRESHOLD} ({len(buy_candidates)}只)")
    print(f"{'='*70}")
    
    if buy_candidates:
        print(f"\n{'代码':<8} {'日期':<12} {'收盘':>8} {'评分':>5} {'涨幅':>7} "
              f"{'DIF':>8} {'DEA':>8} {'量比':>5} {'ATR%':>5} {'跳空限':>8}")
        print("-" * 80)
        for c in buy_candidates:
            print(f"{c['code']:<8} {c['date']:<12} {c['close']:>8.4f} {c['score']:>4.1f} "
                  f"{c['chg']:>+6.2f}% {c['dif']:>+8.4f} {c['dea']:>+8.4f} "
                  f"{c['vr']:>5.1f} {c['atr']:>4.1f}% {c['gap_limit']:>8.4f}")
        
        print(f"\n  规则:")
        print(f"  1. 次日开盘 > 跳空限 → 不买")
        print(f"  2. 次日开盘 ≤ 跳空限 → T+1开盘价买入")
        print(f"  3. -8%止损, 30天持有到期")
    else:
        print("\n  ❌ 无符合条件的信号 — 空仓等")
    
    print(f"\n{'='*70}")
    print(f"🟡 快金叉 (DIF-DEA > -0.015) — {len(near_candidates)}只")
    print(f"{'='*70}")
    if near_candidates:
        print(f"\n{'代码':<8} {'收盘':>8} {'DIF':>8} {'DEA':>8} {'差距':>8}")
        print("-" * 45)
        for c in near_candidates[:20]:
            print(f"{c['code']:<8} {c['close']:>8.4f} {c['dif']:>+8.4f} "
                  f"{c['dea']:>+8.4f} {c['gap']:>+8.4f}")
    
    return buy_candidates, near_candidates


if __name__ == '__main__':
    scan_all()
