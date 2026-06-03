"""全市场扫描 v2: 加趋势确认过滤(近5日不崩 + 有止跌迹象)"""
import requests, json, time, numpy as np, re

headers = {'Referer': 'https://finance.sina.com.cn'}

def gen_all_codes():
    codes = []
    for prefix in ['600','601','603','605']:
        for i in range(0, 1000): codes.append(f'sh{prefix}{i:03d}')
    for i in range(0, 1000): codes.append(f'sz000{i:03d}')
    for i in range(0, 1000): codes.append(f'sz001{i:03d}')
    for i in range(0, 1000): codes.append(f'sz002{i:03d}')
    for i in range(0, 1000): codes.append(f'sz003{i:03d}')
    for i in range(0, 1000): codes.append(f'sz300{i:03d}')
    for i in range(0, 1000): codes.append(f'sz301{i:03d}')
    return codes

def batch_quote(codes):
    results = {}
    batch_size = 800
    for start in range(0, len(codes), batch_size):
        batch = codes[start:start+batch_size]
        url = f'https://hq.sinajs.cn/list={",".join(batch)}'
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.encoding = 'gbk'
            for line in r.text.strip().split('\n'):
                if '=' not in line: continue
                m = re.match(r'var hq_str_(\w+)="(.+)"', line.strip())
                if not m: continue
                code = m.group(1)
                parts = m.group(2).split(',')
                if len(parts) < 10: continue
                try:
                    name = parts[0]
                    price = float(parts[3])
                    prev_close = float(parts[2])
                    high = float(parts[4])
                    low = float(parts[5])
                    volume = float(parts[8])
                    amount = float(parts[9])
                except: continue
                if price <= 0 or name == '': continue
                chg = (price/prev_close - 1)*100
                results[code] = {
                    'name': name, 'price': price, 'prev_close': prev_close,
                    'chg_pct': chg, 'high': high, 'low': low,
                    'volume': volume, 'amount': amount,
                }
        except Exception as e:
            print(f'  batch error: {e}')
        time.sleep(0.4)
    return results

def quick_filter(quotes):
    candidates = {}
    for code, q in quotes.items():
        name = q['name']
        if 'ST' in name or '退' in name or name.startswith('N') or name.startswith('C'):
            continue
        if q['price'] < 3 or q['price'] > 200: continue
        if q['amount'] < 50000000: continue
        if q['volume'] <= 0: continue
        candidates[code] = q
    return candidates

def fetch_kline(code, days=120):
    url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={days}'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'gbk'
        return [(d['day'], float(d['close']), float(d['high']), float(d['low']), float(d['volume'])) for d in json.loads(r.text)]
    except: return []

def calc_and_score_v2(data, buy_thresh=35):
    """v2: 加趋势确认 — 近5日不崩 + 有止跌迹象"""
    if not data or len(data) < 66: return None
    closes = np.array([d[1] for d in data])
    vols = np.array([d[4] for d in data])
    n = len(closes)
    idx = n-1
    
    # ═══ 趋势确认(防线0) ═══
    chg5 = (closes[idx]/closes[idx-4]-1)*100 if idx>=4 else 0
    chg3 = (closes[idx]/closes[idx-2]-1)*100 if idx>=2 else 0
    chg10 = (closes[idx]/closes[idx-9]-1)*100 if idx>=9 else 0
    
    # 近5日跌超8% → 飞刀，不接
    if chg5 < -8:
        return None
    # 近3日还在加速跌(连续3天跌且今天也跌) → 没止跌
    if idx>=3:
        d3 = all(closes[idx-i] < closes[idx-i-1] for i in range(3))
        if d3 and chg3 < -3:
            return None
    
    ma20 = np.array([np.mean(closes[max(0,i-19):i+1]) for i in range(n)])
    ma60 = np.array([np.mean(closes[max(0,i-59):i+1]) for i in range(n)])
    
    # trend
    s5 = (ma20[idx]-ma20[idx-5])/ma20[idx-5]*100 if idx>=5 else 0
    mr = (closes[idx]/ma20[idx]-1)*100
    m60 = (ma20[idx]/ma60[idx]-1)*100
    s_t = np.clip(s5*10+mr*3+m60*5, -100, 100)
    
    # macd
    ema12=np.zeros(n);ema26=np.zeros(n)
    ema12[0]=closes[0];ema26[0]=closes[0]
    for i in range(1,n): ema12[i]=closes[i]*2/13+ema12[i-1]*11/13; ema26[i]=closes[i]*2/27+ema26[i-1]*25/27
    dif=ema12-ema26; dea=np.zeros(n)
    for i in range(1,n): dea[i]=dif[i]*2/10+dea[i-1]*8/10
    bar=2*(dif-dea)
    ms=0
    if dif[idx]>dea[idx]: ms+=35
    if dif[idx]>0 and dea[idx]>0: ms+=20
    if bar[idx]>bar[idx-1]: ms+=20
    if bar[idx]>0: ms+=15
    s_m = np.clip(ms,-100,100)
    
    # rsi
    g=sum(max(closes[j]-closes[j-1],0) for j in range(idx-13,idx+1))
    l=sum(max(closes[j-1]-closes[j],0) for j in range(idx-13,idx+1))
    rsi_val = 100-100/(1+g/l) if l>0 else 100
    if rsi_val<25: s_r=75
    elif rsi_val<35: s_r=45
    elif rsi_val<45: s_r=20
    elif rsi_val>75: s_r=-55
    elif rsi_val>65: s_r=-25
    else: s_r=0
    
    # bb
    mid=np.mean(closes[idx-19:idx+1]);std=np.std(closes[idx-19:idx+1])
    bb_lo=mid-2*std;bb_hi=mid+2*std
    pos=(closes[idx]-bb_lo)/(bb_hi-bb_lo) if bb_hi>bb_lo else 0.5
    if pos<0.15: s_b=70
    elif pos<0.30: s_b=40
    elif pos<0.45: s_b=15
    elif pos>0.85: s_b=-45
    elif pos>0.70: s_b=-15
    else: s_b=0
    
    W={'trend':0.35,'macd':0.25,'rsi':0.15,'bb':0.25}
    score = s_t*W['trend']+s_m*W['macd']+s_r*W['rsi']+s_b*W['bb']
    pos_cnt = sum(1 for s in [s_t,s_m,s_r,s_b] if s>0)
    
    if score < buy_thresh or pos_cnt < 2: return None
    
    # 三道防线
    if idx>=2:
        ychg=(closes[idx-1]/closes[idx-2]-1)*100
        if ychg<-7: return None
    if idx>=19:
        chg20=(closes[idx]/closes[idx-19]-1)*100
        if chg20>25 and pos>0.70: return None
    v5=np.mean(vols[idx-4:idx+1])
    v20=np.mean(vols[idx-19:idx+1])
    if v5<v20*0.6: return None
    uptrend=ma20[idx]>=ma20[idx-5]*0.995
    above60=closes[idx]>ma60[idx]
    vol_ok=v5>v20*0.35
    if not (uptrend and above60 and vol_ok): return None
    
    return {
        'score': round(score,1), 'price': closes[idx],
        'bb_pos': pos*100, 'rsi': rsi_val,
        'bb_lo': bb_lo, 'bb_hi': bb_hi,
        'ma20': ma20[idx], 'ma60': ma60[idx],
        'chg5': chg5, 'chg20': (closes[idx]/closes[idx-19]-1)*100 if idx>=19 else 0,
        'chg_today': (closes[idx]/closes[idx-1]-1)*100 if idx>=1 else 0,
        'sub': f'T:{s_t:+.0f} M:{s_m:+.0f} R:{s_r:+.0f} B:{s_b:+.0f}',
    }

# ── 执行 ──
print("="*80)
print("  全市场扫描 v2: +趋势确认过滤(近5日不崩+不止跌不接)")
print("="*80)

all_codes = gen_all_codes()
print(f"\n⏳ 代码 {len(all_codes)} 个")

print("⏳ 批量拉实时行情...")
quotes = batch_quote(all_codes)
print(f"   有效: {len(quotes)} 只")

candidates = quick_filter(quotes)
print(f"⏳ 粗筛: {len(candidates)} 只")

# 按成交额取TOP400
cand_list = sorted(candidates.items(), key=lambda x: x[1]['amount'], reverse=True)
top_candidates = cand_list[:400]

print(f"⏳ 精算TOP400 (约需 80s)...")
results = []
for i, (code, q) in enumerate(top_candidates):
    data = fetch_kline(code, 120)
    if data:
        s = calc_and_score_v2(data, 35)
        if s:
            results.append({'code': code, 'name': q['name'], **s})
    if (i+1) % 50 == 0:
        print(f"   {i+1}/{len(top_candidates)}  命中: {len(results)}")
    time.sleep(0.15)

results.sort(key=lambda x: x['score'], reverse=True)

# ── 输出 ──
print(f"\n{'='*80}")
print(f"  🎯 明日(6/4) 全市场推荐 TOP25 [v2: 趋势确认]")
print(f"  (扫描{len(quotes)}→粗筛{len(candidates)}→精算{len(top_candidates)}→命中{len(results)})")
print(f"{'='*80}")
print(f"  {'#':<3} {'代码':<10} {'名称':<12} {'评分':>5} {'现价':>7} {'买点':>7} {'目标':>7} {'空间':>6} {'布林':>5} {'RSI':>4} {'今':>6} {'5日':>6} {'20日':>6}")
print(f"  {'-'*108}")
for i, r in enumerate(results[:25]):
    cs = r['code'].replace('sh','').replace('sz','')
    upside = (r['bb_hi']/r['price']-1)*100
    print(f"  {i+1:<3} {cs:<10} {r['name']:<12} {r['score']:+5.0f} "
          f"{r['price']:>7.2f} {r['bb_lo']:>7.2f} {r['bb_hi']:>7.2f} {upside:+5.1f}% "
          f"{r['bb_pos']:>4.0f}% {r['rsi']:>4.0f} {r['chg_today']:+5.1f}% {r['chg5']:+5.1f}% {r['chg20']:+5.1f}%")

# ── 埃斯顿和华安证券在不在? ──
print(f"\n  🔍 特别关注:")
for sym, nm in [('sz002747','埃斯顿'),('sh600909','华安证券'),('sh562500','机器人ETF')]:
    found = [r for r in results if r['code']==sym]
    if found:
        r=found[0]
        print(f"     ✅ {nm}: 第{results.index(r)+1}名  评分{r['score']:+.0f}  BB{r['bb_pos']:.0f}%")
    else:
        print(f"     ❌ {nm}: 未入选(过滤或评分不足)")

print(f"\n  命中率: {len(results)}/{len(top_candidates)} = {len(results)/len(top_candidates)*100:.1f}%")
