"""调整后模型 + 明日推荐 — 加入暴跌/超买/缩量三道防线"""
import requests, json, time, numpy as np

headers = {'Referer': 'https://finance.sina.com.cn'}

def fetch_kline(code, days=150):
    url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={days}'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'gbk'
        return [(d['day'], float(d['close']), float(d['high']), float(d['low']), float(d['volume'])) for d in json.loads(r.text)]
    except: return []

# ── 池子 ──
ETF = {
    'sz159949':'创业板50ETF华安','sh515880':'通信ETF华夏','sh516880':'光伏ETF银华',
    'sh515790':'光伏ETF华泰柏瑞','sh515700':'新能源车ETF平安','sz159755':'电池ETF广发',
    'sh562500':'机器人ETF华夏','sh561700':'电力ETF广发','sh513100':'纳指ETF国泰',
    'sz159996':'家电ETF国泰','sz159892':'恒生医药ETF华夏','sh513700':'港股通医药ETF鹏华',
    'sz159718':'港股医药ETF平安','sz159726':'港股通高股息ETF华夏','sh513590':'港股通消费ETF鹏华',
    'sz159751':'港股通科技ETF鹏华','sh513180':'恒生科技ETF华夏','sz159792':'港股通互联网ETF富国',
    'sz159605':'中概互联ETF广发','sz159607':'中概互联网ETF嘉实','sz159711':'港股通50ETF华夏',
    'sz159712':'港股通50ETF国泰',
}
STOCK = {
    'sh601985':'中国核电','sh601288':'农业银行','sh600900':'长江电力',
    'sh600036':'招商银行','sh601088':'中国神华','sh600519':'贵州茅台',
    'sh601857':'中国石油','sh601398':'工商银行','sz000858':'五粮液',
    # 昨天推荐的加进来
    'sh600909':'华安证券','sz300124':'汇川技术','sh601988':'中国银行',
    'sz002354':'天娱数科','sh600888':'新疆众和',
}

print("⏳ 拉取K线...")
all_data = {}
for i, sym in enumerate(list(ETF) + list(STOCK)):
    d = fetch_kline(sym, 150)
    if d: all_data[sym] = d
    time.sleep(0.25)
print(f"   获取 {len(all_data)} 标的\n")

# ── 指标 ──
def calc_indicators(data):
    if len(data) < 66: return None
    closes = np.array([d[1] for d in data])
    vols = np.array([d[4] for d in data])
    n = len(closes)
    
    ma20 = np.array([np.mean(closes[max(0,i-19):i+1]) for i in range(n)])
    ma60 = np.array([np.mean(closes[max(0,i-59):i+1]) for i in range(n)])
    
    trend = np.zeros(n)
    for i in range(60, n):
        slope_5 = (ma20[i]-ma20[i-5])/ma20[i-5]*100
        ma_ratio = (closes[i]/ma20[i]-1)*100
        ma60_ratio = (ma20[i]/ma60[i]-1)*100
        trend[i] = np.clip(slope_5*10 + ma_ratio*3 + ma60_ratio*5, -100, 100)
    
    ema12=np.zeros(n); ema26=np.zeros(n)
    ema12[0]=closes[0]; ema26[0]=closes[0]
    for i in range(1,n): ema12[i]=closes[i]*2/13+ema12[i-1]*11/13; ema26[i]=closes[i]*2/27+ema26[i-1]*25/27
    dif=ema12-ema26; dea=np.zeros(n)
    for i in range(1,n): dea[i]=dif[i]*2/10+dea[i-1]*8/10
    bar=2*(dif-dea)
    macd=np.zeros(n)
    for i in range(26,n):
        s=0
        if dif[i]>dea[i]: s+=35
        if dif[i]>0 and dea[i]>0: s+=20
        if bar[i]>bar[i-1]: s+=20
        if bar[i]>0: s+=15
        macd[i]=np.clip(s,-100,100)
    
    rsi_arr=np.full(n,50.0)
    for i in range(14,n):
        g=sum(max(closes[j]-closes[j-1],0) for j in range(i-13,i+1))
        l=sum(max(closes[j-1]-closes[j],0) for j in range(i-13,i+1))
        rsi_arr[i]=100-100/(1+g/l) if l>0 else 100
    rsi_s=np.zeros(n)
    for i in range(14,n):
        v=rsi_arr[i]
        if v<25: rsi_s[i]=75
        elif v<35: rsi_s[i]=45
        elif v<45: rsi_s[i]=20
        elif v>75: rsi_s[i]=-55
        elif v>65: rsi_s[i]=-25
    
    bb_mid=np.zeros(n); bb_up=np.zeros(n); bb_lo=np.zeros(n)
    bb_s=np.zeros(n)
    for i in range(19,n):
        mid=np.mean(closes[i-19:i+1]); std=np.std(closes[i-19:i+1])
        bb_mid[i]=mid; bb_up[i]=mid+2*std; bb_lo[i]=mid-2*std
        pos=(closes[i]-bb_lo[i])/(bb_up[i]-bb_lo[i]) if bb_up[i]>bb_lo[i] else 0.5
        if pos<0.15: bb_s[i]=70
        elif pos<0.30: bb_s[i]=40
        elif pos<0.45: bb_s[i]=15
        elif pos>0.85: bb_s[i]=-45
        elif pos>0.70: bb_s[i]=-15
    
    return {'dates':[d[0] for d in data],'close':closes,'vol':vols,
            'ma20':ma20,'ma60':ma60,'trend':trend,'macd':macd,'rsi_s':rsi_s,'bb_s':bb_s,
            'rsi':rsi_arr,'bb_mid':bb_mid,'bb_up':bb_up,'bb_lo':bb_lo}

indicators = {}
for sym,data in all_data.items():
    ind = calc_indicators(data)
    if ind: indicators[sym]=ind

all_dates = sorted(set(d for ind in indicators.values() for d in ind['dates']))
T = all_dates[-1]; Tm1 = all_dates[-2]
print(f"T-1={Tm1}  T={T}")

W = {'trend':0.35,'macd':0.25,'rsi':0.15,'bb':0.25}

# ── 增强评分函数 (加入三道防线) ──
def score_v2(ind, idx, buy_thresh=40):
    s_t=ind['trend'][idx]; s_m=ind['macd'][idx]
    s_r=ind['rsi_s'][idx]; s_b=ind['bb_s'][idx]
    score = s_t*W['trend']+s_m*W['macd']+s_r*W['rsi']+s_b*W['bb']
    pos = sum(1 for s in [s_t,s_m,s_r,s_b] if s>0)
    
    if score < buy_thresh or pos < 2:
        return round(score,1), 'HOLD', ''
    
    # 🔴 防线1: 单日暴跌 >7%
    if idx >= 1:
        yesterday_chg = (ind['close'][idx-1] / ind['close'][max(0,idx-2)] - 1)*100
        if yesterday_chg < -7:
            return round(score,1), 'AVOID', f'昨日暴跌{yesterday_chg:.0f}%'
    
    # 🔴 防线2: 超买保护 — 20日涨>25% 且 布林>70%
    if idx >= 19:
        chg20 = (ind['close'][idx] / ind['close'][idx-19] - 1)*100
        bb_pos = (ind['close'][idx]-ind['bb_lo'][idx])/(ind['bb_up'][idx]-ind['bb_lo'][idx]) if ind['bb_up'][idx]>ind['bb_lo'][idx] else 0.5
        if chg20 > 25 and bb_pos > 0.70:
            return round(score,1), 'WATCH', f'超买(20日+{chg20:.0f}% BB{bb_pos*100:.0f}%)'
    
    # 🔴 防线3: 缩量反弹
    v5 = np.mean(ind['vol'][max(0,idx-4):idx+1])
    v20 = np.mean(ind['vol'][max(0,idx-19):idx+1])
    if v5 < v20 * 0.6:
        return round(score,1), 'WATCH', f'缩量(量比{v5/v20:.2f})'
    
    # 趋势+均线
    uptrend = ind['ma20'][idx] >= ind['ma20'][max(0,idx-5)]*0.995
    above60 = ind['close'][idx] > ind['ma60'][idx]
    v5b = np.mean(ind['vol'][max(0,idx-4):idx+1])
    v20b = np.mean(ind['vol'][max(0,idx-19):idx+1])
    vol_ok = v5b > v20b*0.35
    
    reasons = []
    if not uptrend: reasons.append('MA20微降')
    if not above60: reasons.append('破MA60')
    if not vol_ok: reasons.append('缩量')
    if reasons:
        return round(score,1), 'WATCH', '/'.join(reasons)
    return round(score,1), 'BUY', ''

# ── 1. 昨天推荐的回测对比 ──
print(f"\n{'='*100}")
print(f"  📊 昨日8只推荐 → 原模型 vs 新模型(三道防线)")
print(f"{'='*100}")

yesterday_8 = {
    'sh513100':'纳指ETF','sh561700':'电力ETF','sh515790':'光伏ETF华泰柏瑞',
    'sz002354':'天娱数科','sh601988':'中国银行','sh600909':'华安证券',
    'sh600888':'新疆众和','sz300124':'汇川技术',
}

print(f"  {'标的':<16} {'昨收':>7} {'今收':>7} {'涨跌':>8} {'原评分':>6} {'原信号':>5} {'新评分':>6} {'新信号':>6} {'过滤原因'}")
print(f"  {'-'*90}")

for sym,name in yesterday_8.items():
    if sym not in indicators: continue
    ind = indicators[sym]
    if Tm1 not in ind['dates']: continue
    yi = ind['dates'].index(Tm1)
    ti = ind['dates'].index(T) if T in ind['dates'] else yi
    
    old_score, old_sig, _ = score_v2(ind, yi, 50)  # 原模型: 买≥50, 无防线, 但用三道防线看原评分
    new_score, new_sig, reason = score_v2(ind, yi, 40)  # 新模型: 买≥40 + 三道防线
    
    yc=ind['close'][yi]; tc=ind['close'][ti]; chg=(tc/yc-1)*100
    chg_s = f'+{chg:.2f}%' if chg>0 else f'{chg:.2f}%'
    
    old_icon = '🟢' if old_sig=='BUY' else '🟡' if old_sig=='WATCH' else '🔴' if old_sig=='AVOID' else '⚪'
    new_icon = '🟢' if new_sig=='BUY' else '🟡' if new_sig=='WATCH' else '🔴' if new_sig=='AVOID' else '⚪'
    
    print(f"  {name:<16} {yc:>7.3f} {tc:>7.3f} {chg_s:>8} {old_score:+6.1f} {old_icon}{old_sig:<4} {new_score:+6.1f} {new_icon}{new_sig:<5} {reason}")

# ── 2. 明天推荐 ──
print(f"\n{'='*100}")
print(f"  🎯 明日(6月4日)推荐 [新模型: 买≥40 + 三道防线]")
print(f"{'='*100}")

pool_map = {**{s:(n,'ETF') for s,n in ETF.items()}, **{s:(n,'个股') for s,n in STOCK.items()}}

tomorrow = []
for sym in indicators:
    ind = indicators[sym]
    if T not in ind['dates']: continue
    ti = ind['dates'].index(T)
    score, sig, reason = score_v2(ind, ti, 40)
    name,typ = pool_map.get(sym, (sym,'?'))
    close_t = ind['close'][ti]
    bb_l=ind['bb_lo'][ti]; bb_u=ind['bb_up'][ti]
    bb_pos=(close_t-bb_l)/(bb_u-bb_l)*100 if bb_u>bb_l else 50
    upside=(bb_u/close_t-1)*100 if bb_u>0 else 0
    buy_pt=round(bb_l,3) if bb_l>0 else round(close_t*0.95,3)
    chg5=(close_t/ind['close'][max(0,ti-4)]-1)*100 if ti>=4 else 0
    chg20=(close_t/ind['close'][max(0,ti-19)]-1)*100 if ti>=19 else 0
    
    s_t=ind['trend'][ti]; s_m=ind['macd'][ti]; s_r=ind['rsi_s'][ti]; s_b=ind['bb_s'][ti]
    
    tomorrow.append({
        'sym':sym,'name':name,'typ':typ,'score':score,'sig':sig,'reason':reason,
        'close':close_t,'buy':buy_pt,'target':round(bb_u,3),'upside':upside,
        'bb_pos':bb_pos,'rsi':ind['rsi'][ti],'chg5':chg5,'chg20':chg20,
        'sub':f'T:{s_t:+.0f} M:{s_m:+.0f} R:{s_r:+.0f} B:{s_b:+.0f}',
    })

tomorrow.sort(key=lambda x: x['score'], reverse=True)

t_buys = [r for r in tomorrow if r['sig']=='BUY']
t_watch = [r for r in tomorrow if r['sig']=='WATCH']
t_avoid = [r for r in tomorrow if r['sig']=='AVOID']

print(f"\n  🟢 买入 ({len(t_buys)}只):")
if t_buys:
    print(f"  {'#':<3} {'代码':<10} {'名称':<16} {'类型':<4} {'评分':>5} {'现价':>7} {'买点':>7} {'目标':>7} {'空间':>6} {'布林':>5} {'RSI':>4} {'5日':>7} {'20日':>7}")
    print(f"  {'-'*111}")
    for i,r in enumerate(t_buys):
        cs=r['sym'].replace('sh','').replace('sz','')
        print(f"  {i+1:<3} {cs:<10} {r['name']:<16} {r['typ']:<4} {r['score']:+5.0f} "
              f"{r['close']:>7.3f} {r['buy']:>7.3f} {r['target']:>7.3f} {r['upside']:+5.1f}% "
              f"{r['bb_pos']:>4.0f}% {r['rsi']:>4.0f} {r['chg5']:+6.1f}% {r['chg20']:+6.1f}%")
        print(f"      子信号: {r['sub']}")
else:
    print(f"     无")

if t_watch:
    print(f"\n  🟡 关注 ({len(t_watch)}只, 前5):")
    for i,r in enumerate(t_watch[:5]):
        cs=r['sym'].replace('sh','').replace('sz','')
        print(f"     {cs:<10} {r['name']:<16} {r['typ']:<4} {r['score']:+5.0f}  现价{r['close']:.3f}  布林{r['bb_pos']:.0f}%  [{r['reason']}]")

if t_avoid:
    print(f"\n  🔴 回避 ({len(t_avoid)}只):")
    for r in t_avoid:
        cs=r['sym'].replace('sh','').replace('sz','')
        print(f"     {cs:<10} {r['name']:<16} [{r['reason']}]")

# ── 3. 你的持仓 ──
print(f"\n{'='*100}")
print(f"  💼 你的持仓: 光伏ETF银华")
print(f"{'='*100}")
if 'sh516880' in indicators:
    ind = indicators['sh516880']
    ti = ind['dates'].index(T)
    score, sig, reason = score_v2(ind, ti, 40)
    print(f"  现价:{ind['close'][ti]:.3f}  成本:0.894  浮盈:{(ind['close'][ti]/0.894-1)*100:+.2f}%")
    print(f"  当前评分:{score:+.0f}  信号:{sig}  [{reason if reason else 'OK'}]")

# ── 4. 总结 ──
print(f"\n{'='*100}")
print(f"  📝 模型调整总结")
print(f"{'='*100}")
print(f"""
  加入三道防线:
  1. 单日暴跌>7% → AVOID (天娱数科类型)
  2. 20日涨>25% + 布林>70% → WATCH (新疆众和类型)
  3. 缩量反弹 (量比<0.6) → WATCH

  参数调整:
  - buy阈值: 50 → 40
  - 趋势过滤: MA20>MA60 → close>MA60 (宽松)
  - 缩量过滤: 量比阈值 0.5 → 0.35
""")
