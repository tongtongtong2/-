"""
选股模型回测 — 基于 market_data.db 日线数据
模拟每天选股 → 追踪 N 天后收益 → 统计胜率/盈亏比
"""
import sys, os
sys.path.insert(1, r"F:\datax\stock-recommendation-platform\.venv\Lib\site-packages")
import sqlite3, json, sys, os
from datetime import date, timedelta
from collections import defaultdict
import numpy as np
import pandas as pd

# ── Config ──
DB = r"F:\datax\stock-recommendation-platform\backtest\data\market_data.db"
LOOKBACK_DAYS = 55        # 选股需要的日线天数
BACKTEST_DAYS = 20        # 回测最近 N 个交易日
FORWARD_PERIODS = [1, 3, 5, 10]  # 追踪后续 N 天收益
MIN_BARS = 55
MAX_RET_5 = 0.10
MAX_RET_20 = 0.30
MAX_VOL_STD = 0.04
MIN_DIST_HIGH = 0.03
TOP_N = 10

# ── Load data ──
conn = sqlite3.connect(DB)

# Get stock info (for ST filtering)
st_info = pd.read_sql("SELECT stock_code, stock_name FROM stock_info_new", conn)
st_codes = set(st_info[st_info['stock_name'].str.contains('ST|退', na=False)]['stock_code'])
print(f"ST stocks excluded: {len(st_codes)}")

# Get all daily bars
df = pd.read_sql("SELECT * FROM daily_bars ORDER BY stock_code, trade_date", conn)
df['stock_code'] = df['stock_code'].astype(str).str.zfill(6)
df['trade_date'] = pd.to_datetime(df['trade_date'])
df['close'] = df['close'].astype(float)
df['open'] = df['open'].astype(float)
df['high'] = df['high'].astype(float)
df['low'] = df['low'].astype(float)
df['volume'] = df['volume'].astype(float)

# Get trading dates
all_dates = sorted(df['trade_date'].unique())
backtest_dates = all_dates[-BACKTEST_DAYS-21:-1]  # last 20, leave room for forward
print(f"Backtest period: {backtest_dates[0].date()} to {backtest_dates[-1].date()} ({len(backtest_dates)} days)")

# Load index data separately
idx_df = pd.read_sql("SELECT * FROM index_daily ORDER BY trade_date", conn)
idx_df['trade_date'] = pd.to_datetime(idx_df['trade_date'], format='mixed')
idx_df['close'] = idx_df['close'].astype(float)

conn.close()

# ── Indicator computation (same as run_select.py) ──
def compute_indicators(daily_df):
    if daily_df is None or daily_df.empty or 'close' not in daily_df.columns:
        return None
    d = daily_df.sort_values('trade_date').reset_index(drop=True)
    if len(d) < MIN_BARS:
        return None
    closes = d['close'].values
    vols = d['volume'].values if 'volume' in d.columns else None
    if vols is None or len(vols) < MIN_BARS:
        return None
    
    last = float(closes[-1])
    ma5 = float(np.mean(closes[-5:]))
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))
    
    ret_5 = last / closes[-6] - 1 if len(closes) >= 6 else 0
    ret_20 = last / closes[-21] - 1 if len(closes) >= 21 else 0
    ret_60 = last / closes[-61] - 1 if len(closes) >= 61 else 0
    
    daily_ret_20 = np.diff(closes[-21:]) / closes[-21:-1]
    vol_std = float(np.std(daily_ret_20))
    peak = np.maximum.accumulate(closes[-20:])
    drawdown = closes[-20:] / peak - 1
    max_dd = float(np.min(drawdown))
    
    avg5 = float(np.mean(vols[-5:]))
    avg20 = float(np.mean(vols[-20:]))
    vol_ratio = avg5 / avg20 if avg20 > 0 else 0
    
    high60 = float(np.max(closes[-60:]))
    dist_high60 = (high60 - last) / high60 if high60 > 0 else 0
    
    return {
        'last': last, 'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'ret_5': ret_5, 'ret_20': ret_20, 'ret_60': ret_60,
        'vol_std': vol_std, 'max_dd': max_dd,
        'vol_ratio_5_20': vol_ratio, 'dist_high60': dist_high60,
    }

def passes_hard_filter(ind):
    if not (ind['ma5'] > ind['ma10'] > ind['ma20'] > ind['ma60']):
        return False
    if ind['last'] <= ind['ma60']:
        return False
    if ind['ret_5'] >= MAX_RET_5:
        return False
    if ind['ret_20'] >= MAX_RET_20:
        return False
    if ind['vol_std'] >= MAX_VOL_STD:
        return False
    if ind['dist_high60'] < MIN_DIST_HIGH:
        return False
    return True

# ── Scoring (simplified) ──
def score_stocks(rows):
    f = pd.DataFrame(rows)
    if f.empty:
        return f
    
    def zrank(s):
        return s.rank(pct=True) * 100
    
    def bell_score(v, lo, hi):
        half = (hi-lo)/2; center = (lo+hi)/2
        dist = abs(v - center)
        over = (dist - half).clip(lower=0)
        return (100 * (1 - over/half)).clip(0, 100)
    
    f['score_ret60'] = zrank(f['ret_60'])
    f['bias_ma20'] = f['last'] / f['ma20'] - 1
    f['score_bias'] = zrank(f['bias_ma20'])
    f['trend_strength'] = f['score_ret60'] * 0.16 + f['score_bias'] * 0.09
    
    f['score_smooth_std'] = zrank(-f['vol_std'])
    f['score_smooth_dd'] = zrank(f['max_dd'])
    f['trend_smooth'] = f['score_smooth_std'] * 0.18 + f['score_smooth_dd'] * 0.12
    
    f['score_vol'] = bell_score(f['vol_ratio_5_20'], 1.0, 2.0)
    f['volume_factor'] = f['score_vol'] * 0.15
    
    f['score_pos'] = bell_score(f['dist_high60'], 0.05, 0.20)
    f['position'] = f['score_pos'] * 0.12
    
    f['score_liq'] = zrank(f['avg_turnover_20'].fillna(0))
    f['liquidity'] = f['score_liq'] * 0.08
    
    f['dd_penalty'] = f['max_dd'].apply(lambda x: max(0, abs(x)-0.15)*200).clip(upper=15)
    
    f['total_score'] = (
        f['trend_strength'] * 0.8929 + f['trend_smooth'] * 1.00 +
        f['volume_factor'] * 1.00 + f['position'] * 1.00 +
        f['liquidity'] * 0.75 - f['dd_penalty']
    )
    
    return f.sort_values('total_score', ascending=False).head(TOP_N)


# ── Run Backtest ──
print("\nRunning backtest...")
all_picks = []  # list of {date, stock_code, score, forward_returns}

skipped_market = 0
market_passed = 0

for bi, bt_date in enumerate(backtest_dates):
    bt_str = bt_date.strftime('%Y-%m-%d')
    
    # Get data for this date: each stock needs bt_date and preceding 60 days
    # First, find stocks that traded on bt_date
    day_data = df[df['trade_date'] == bt_date].copy()
    day_data = day_data[~day_data['stock_code'].isin(st_codes)]  # exclude ST
    day_data = day_data[day_data['close'] > 0]
    day_data = day_data[day_data['volume'] > 0]
    
    # Rank by volume, take top 300
    day_data = day_data.sort_values('volume', ascending=False).head(200)
    candidates = day_data['stock_code'].unique()
    
    if len(candidates) == 0:
        continue
    
    # ── 市场环境过滤：沪深300 > MA60 才选股 ──
    index_data = idx_df[idx_df['trade_date'] <= bt_date]
    index_data = index_data.sort_values('trade_date').tail(120)
    if len(index_data) >= 60:
        sh300_close = float(index_data['close'].values[-1])
        ma60_idx = float(np.mean(index_data['close'].values[-60:]))
        if sh300_close <= ma60_idx:
            skipped_market += 1
            continue
    market_passed += 1
    
    # Get all history for candidates (single pass)
    from datetime import timedelta
    cutoff = bt_date - timedelta(days=180)  # ~120 trading days, enough for 70 bars
    hist_mask = (df['trade_date'] >= cutoff) & (df['trade_date'] <= bt_date)
    all_hist = df[hist_mask].copy()
    all_hist = all_hist[all_hist['stock_code'].isin(candidates)]
    
    if bi == 0:
        print(f"  Debug day {bt_str}: candidates={len(candidates)}, hist_rows={len(all_hist)}")
    
    rows = []
    skip_no_data = 0
    skip_no_ind = 0
    skip_filter = 0
    for code in candidates:
        stock_hist = all_hist[all_hist['stock_code'] == code]
        if len(stock_hist) < MIN_BARS:
            skip_no_data += 1
            continue
        stock_hist = stock_hist.sort_values('trade_date').tail(LOOKBACK_DAYS + 1)
        ind = compute_indicators(stock_hist)
        if ind is None:
            skip_no_ind += 1
            continue
        if not passes_hard_filter(ind):
            skip_filter += 1
            continue
        row = {'stock_code': code, **ind,
               'avg_turnover_20': np.mean(stock_hist['volume'].tail(20).values * stock_hist['close'].tail(20).values)}
        rows.append(row)
    
    if bi == 0:
        print(f"  Passed: {len(rows)}, NoData: {skip_no_data}, NoInd: {skip_no_ind}, Filtered: {skip_filter}")
    
    if not rows:
        continue
    
    top = score_stocks(rows)
    
    # Track forward returns
    for _, pick in top.iterrows():
        code = pick['stock_code']
        # Get future prices
        future = df[(df['stock_code'] == code) & (df['trade_date'] > bt_date)]
        future = future.sort_values('trade_date')
        
        fwd = {'date': bt_str, 'stock_code': code, 'score': round(pick['total_score'], 1)}
        for p in FORWARD_PERIODS:
            if len(future) >= p:
                fwd[f'ret_{p}d'] = round((future['close'].values[p-1] / pick['last'] - 1) * 100, 2)
            else:
                fwd[f'ret_{p}d'] = None
        all_picks.append(fwd)
    
    if (bi+1) % 5 == 0:
        print(f"  {bi+1}/{len(backtest_dates)} done, {len(all_picks)} picks so far")

print(f"\nTotal picks: {len(all_picks)}")

# ── Statistics ──
print(f"\n{'='*60}")
print("  回测结果")
print(f"{'='*60}")

for p in FORWARD_PERIODS:
    col = f'ret_{p}d'
    valid = [x[col] for x in all_picks if x[col] is not None]
    if not valid:
        print(f"\n{p}日后: 无有效数据")
        continue
    
    wins = sum(1 for r in valid if r > 0)
    total = len(valid)
    avg = np.mean(valid)
    med = np.median(valid)
    best = max(valid)
    worst = min(valid)
    std = np.std(valid)
    
    print(f"\n{p}日后 ({total}笔):")
    print(f"  胜率: {wins}/{total} = {wins/total*100:.1f}%")
    print(f"  平均收益: {avg:+.2f}%  中位数: {med:+.2f}%")
    print(f"  最大盈利: {best:+.2f}%  最大亏损: {worst:+.2f}%")
    print(f"  标准差: {std:.2f}%")

# By date statistics
print(f"\n{'='*60}")
print("  逐日表现")
print(f"{'='*60}")
by_date = defaultdict(list)
for pick in all_picks:
    d = pick['date']
    ret5 = pick.get('ret_5d')
    if ret5 is not None:
        by_date[d].append(ret5)

for d in sorted(by_date.keys()):
    rets = by_date[d]
    avg = np.mean(rets)
    wr = sum(1 for r in rets if r > 0) / len(rets) * 100
    bar = '█' * max(1, int(abs(avg) * 2)) if abs(avg) > 0.5 else '·'
    color = '🟢' if avg > 0 else '🔴'
    print(f"  {d}: {color} {avg:+.2f}% (wr={wr:.0f}%, n={len(rets)}) {bar}")

# Market filter stats
print(f"\n市场过滤: 跳过 {skipped_market} 天(沪深300<MA60), 通过 {market_passed} 天")

# Overall summary
print(f"\n{'='*60}")
ret5s = [x['ret_5d'] for x in all_picks if x['ret_5d'] is not None]
if ret5s:
    total_pnl = sum(ret5s)
    wr_all = sum(1 for r in ret5s if r > 0) / len(ret5s) * 100
    print(f"  5日胜率: {wr_all:.1f}%  总收益: {total_pnl:+.1f}%  平均: {np.mean(ret5s):+.2f}%/{len(ret5s)}笔")
