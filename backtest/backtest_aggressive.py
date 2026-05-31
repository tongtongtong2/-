
"""进攻型月度策略回测 - numpy优化版（只算月末日期）"""
import sqlite3, numpy as np, time
from pathlib import Path
from collections import defaultdict

DB = Path(r"F:/datax/stock-recommendation-platform/backtest/data/market_data.db")

TOP_N = 5
HOLD_DAYS = 22
MIN_BARS = 60
SLIP = 0.001
COMM = 0.0003
TAX = 0.001
COST = COMM * 2 + TAX + SLIP * 2

POS_MIN = 0.55
MOM_MIN = 0.05
MOM_MAX = 0.30
PRICE_MIN = 3.0
TURN_MIN = 3000 * 10000
TURN_MAX = 50000 * 10000
MAX_RET_5D = 0.08
MIN_DIST_HIGH = 0.03
MAX_DAY_CHG = 0.05
# 不加低波筛选

t0 = time.time()

# 加载
conn = sqlite3.connect(str(DB))

# 指数
cur = conn.execute("SELECT trade_date, close FROM index_daily ORDER BY trade_date")
idx_raw = cur.fetchall()
def nd(d):
    return d if '-' in str(d) else f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}"
idx_dates = [nd(r[0]) for r in idx_raw]
idx_c = np.array([r[1] for r in idx_raw], dtype=float)

# 个股
cur = conn.execute("""SELECT stock_code, trade_date, open, high, low, close, volume
    FROM daily_bars WHERE close>0 AND open>0 ORDER BY stock_code, trade_date""")
raw = defaultdict(list)
for code, dt, op, hi, lo, cl, vol in cur:
    raw[code].append((dt, float(op), float(hi), float(lo), float(cl), float(vol or 0)))
conn.close()

# 转numpy & 过滤
stocks = {}
all_dates_set = set()
for code, bars in raw.items():
    if len(bars) < MIN_BARS:
        continue
    dates = [b[0] for b in bars]
    all_dates_set.update(dates)
    stocks[code] = {
        'dates': dates,
        'date_idx': {d:i for i,d in enumerate(dates)},
        'o': np.array([b[1] for b in bars]),
        'h': np.array([b[2] for b in bars]),
        'l': np.array([b[3] for b in bars]),
        'c': np.array([b[4] for b in bars]),
        'v': np.array([b[5] for b in bars]),
    }

all_dates = sorted(all_dates_set)
date_pos = {d:i for i,d in enumerate(all_dates)}
print(f"加载: {len(stocks)}只, {len(all_dates)}天, {time.time()-t0:.1f}s")

# 找月末
month_ends = []
for d in all_dates:
    if d < '2016-06-01':
        continue
    ym = d[:7]
    md = [x for x in all_dates if x[:7]==ym]
    if md and d == max(md):
        month_ends.append(d)
print(f"月末: {len(month_ends)}个 ({month_ends[0]}~{month_ends[-1]})")

def compute_factors(code, date_str):
    """计算单只股票在指定日期的因子（只用<=该日的数据）"""
    s = stocks.get(code)
    if s is None or date_str not in s['date_idx']:
        return None
    idx = s['date_idx'][date_str]
    if idx < 60:
        return None
    
    c = s['c'][:idx+1]
    o = s['o'][:idx+1]
    v = s['v'][:idx+1]
    n = len(c)
    
    if c[-1] < PRICE_MIN:
        return None
    
    # 收益率
    rets = np.diff(c) / c[:-1]
    
    # pos_days_60
    pos60 = (rets[-60:] > 0).mean() if len(rets) >= 60 else (rets>0).mean()
    
    # mom_60
    mom = (c[-1] - c[max(0,n-61)]) / c[max(0,n-61)]
    
    # vol_20
    vol = float(np.std(rets[-20:])) if len(rets) >= 20 else float(np.std(rets))
    
    # MA60
    ma = float(np.mean(c[-60:]))
    
    # turnover20 (volume是手 × 100 × 均价)
    if len(v) >= 20:
        turn = float(np.mean(v[-20:]) * np.mean(c[-20:]) * 100)
    else:
        turn = 0
    
    if turn <= 0:
        return None
    
    # 5日涨幅
    ret5 = (c[-1] - c[min(n-6,0)]) / c[max(0,n-6)] if n >= 6 else 0
    
    # 距高点
    h60 = float(np.max(c[-60:]))
    dist_high = (h60 - c[-1]) / h60 if h60 > 0 else 0
    
    # 当日涨跌
    day_chg = (c[-1] - o[-1]) / o[-1] if o[-1] > 0 else 0
    
    return {
        'code': code, 'last': float(c[-1]), 'open': float(o[-1]),
        'pos60': pos60, 'mom60': mom, 'vol20': vol, 'ma60': ma,
        'turnover': turn, 'ret5d': ret5, 'dist_high': dist_high, 'day_chg': day_chg
    }

def passes_filters(f):
    """硬过滤（不加vol）"""
    if f['turnover'] < TURN_MIN or f['turnover'] > TURN_MAX:
        return False
    if f['pos60'] < POS_MIN:
        return False
    if f['mom60'] < MOM_MIN or f['mom60'] > MOM_MAX:
        return False
    if abs(f['ret5d']) > MAX_RET_5D:
        return False
    if f['dist_high'] < MIN_DIST_HIGH:
        return False
    if abs(f['day_chg']) > MAX_DAY_CHG:
        return False
    return True

# 回测
equity = 1.0
all_trades = []
equity_curve = []
cash_periods = 0

t1 = time.time()

for mi, me_date in enumerate(month_ends):
    # 选股
    candidates = []
    for code in stocks:
        f = compute_factors(code, me_date)
        if f and passes_filters(f):
            candidates.append(f)
    
    if len(candidates) < TOP_N:
        continue
    
    # 按 pos60 排名
    candidates.sort(key=lambda x: x['pos60'], reverse=True)
    selected = candidates[:TOP_N]
    
    # 市场过滤
    mk_ok = True
    if me_date in idx_dates:
        m_idx = idx_dates.index(me_date)
        if m_idx >= 60:
            ma = float(np.mean(idx_c[m_idx-59:m_idx+1]))
            if idx_c[m_idx] < ma:
                mk_ok = False
    
    if not mk_ok:
        cash_periods += 1
        equity_curve.append({'date': me_date, 'equity': equity, 'action': 'CASH'})
        continue
    
    # 找T+1和T+22
    mp = date_pos.get(me_date, -1)
    if mp < 0 or mp + 1 + HOLD_DAYS >= len(all_dates):
        continue
    buy_dt = all_dates[mp+1]
    sell_dt = all_dates[mp+1+HOLD_DAYS]
    
    period_ret = 0
    valid = 0
    
    for st in selected:
        code = st['code']
        s = stocks[code]
        if buy_dt not in s['date_idx'] or sell_dt not in s['date_idx']:
            continue
        
        bi = s['date_idx'][buy_dt]
        si = s['date_idx'][sell_dt]
        
        buy_p = s['o'][bi] * (1 + SLIP)
        sell_p = s['c'][si] * (1 - SLIP)
        ret = (sell_p / buy_p) - 1 - COST
        
        period_ret += ret
        valid += 1
        all_trades.append({
            'date': me_date, 'code': code,
            'buy_date': buy_dt, 'sell_date': sell_dt,
            'return': round(ret * 100, 2),
        })
    
    if valid > 0:
        avg_ret = period_ret / valid
        equity *= (1 + avg_ret)
        equity_curve.append({'date': me_date, 'equity': equity, 'ret': avg_ret, 'action': 'BUY'})
        if mi < 5 or mi % 12 == 0:
            print(f"  {me_date} -> {valid}只, {avg_ret*100:+.2f}%, eq={equity:.4f}")

print(f"\n回测循环: {time.time()-t1:.1f}s, 共{len(all_trades)}笔交易")

# 统计
if not all_trades:
    print("NO TRADES!")
    exit()

arr = np.array([t['return'] for t in all_trades])
wins = arr[arr > 0]
losses = arr[arr < 0]
tr = [e for e in equity_curve if e.get('action') == 'BUY']
prets = np.array([e['ret'] for e in tr])

total_ret = (equity - 1) * 100
n_periods = len(tr)
n_years = n_periods / 12
ann = (equity ** (1/n_years) - 1) * 100 if n_years > 0 and equity > 0 else 0

peak = 1.0
max_dd = 0
for e in equity_curve:
    peak = max(peak, e['equity'])
    dd = (e['equity'] - peak) / peak
    max_dd = min(max_dd, dd)

# 回撤序列
dd_series = []
peak_v = 1.0
for e in equity_curve:
    peak_v = max(peak_v, e['equity'])
    dd_series.append((e['equity']-peak_v)/peak_v*100)

print("\n" + "="*70)
print("  进攻型策略回测结果 (不加低波筛选)")
print("="*70)
print(f"  期间: {month_ends[0]} ~ {month_ends[-1]}")
print(f"  交易: {len(all_trades)}笔, {n_periods}个月 (其中空仓{cash_periods}个月)")
print(f"  总收益: {total_ret:+.1f}%")
print(f"  年化: {ann:+.1f}%")
print(f"  胜率: {len(wins)/len(arr)*100:.1f}% ({len(wins)}W/{len(losses)}L)")
if len(wins) and len(losses):
    print(f"  均盈: {np.mean(wins):+.2f}%  均亏: {np.mean(losses):+.2f}%")
    print(f"  盈亏比: {abs(np.mean(wins)/np.mean(losses)):.2f}")
print(f"  最大回撤: {max_dd*100:.1f}%" )
print(f"  最大回撤时期: {min(dd_series):.1f}%")
if len(prets) > 1 and np.std(prets) > 0:
    sr = np.mean(prets)/np.std(prets)*np.sqrt(12)
    print(f"  夏普比率: {sr:.2f}")

# 年度
print("\n  年度收益:")
annual = defaultdict(lambda: {'rets':[], 'n':0})
for e in tr:
    yr = e['date'][:4]
    annual[yr]['rets'].append(e['ret'])
    annual[yr]['n'] += 1
for yr in sorted(annual.keys()):
    d = annual[yr]
    cum = np.prod([1+r for r in d['rets']]) - 1
    wr = sum(1 for r in d['rets'] if r>0)/len(d['rets'])*100
    print(f"    {yr}: {cum*100:+.1f}% ({d['n']}期, WR{wr:.0f}%)")

print(f"\n总耗时: {time.time()-t0:.1f}s")
