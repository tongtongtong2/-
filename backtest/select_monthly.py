
"""月度低波稳升 - 选股器 v3（加硬过滤）"""
import sqlite3, numpy as np, pandas as pd
from pathlib import Path
import time

DB = Path(r"F:/datax/stock-recommendation-platform/backtest/data/market_data.db")
t0 = time.time()
conn = sqlite3.connect(str(DB))

# === 参数 ===
TOP_N = 5
POS_DAYS_MIN = 0.55
MOM_60_MIN = 0.05
MOM_60_MAX = 0.30
VOL_PCT = 0.40
PRICE_MIN = 3.0
TURNOVER_MIN = 3000     # 万
TURNOVER_MAX = 50000    # 万 (5亿, 策略alpha来源)
MAX_RET_5D = 0.08       # 5日涨幅<8%
MIN_DIST_HIGH = 0.03    # 距60日高点>3%
MAX_DAY_CHG = 0.05      # 选股日当日涨跌幅<5%
MAX_PER_INDUSTRY = 2    # 每行业最多2只

# 加载
idx = pd.read_sql("SELECT trade_date, close FROM index_daily ORDER BY trade_date", conn)
idx['trade_date'] = idx['trade_date'].astype(str).apply(
    lambda d: d if '-' in str(d) else f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}")
idx_dates = idx['trade_date'].tolist()
idx_closes = idx['close'].values

df = pd.read_sql("""SELECT stock_code, trade_date, open, high, low, close, volume
    FROM daily_bars WHERE close > 0 AND open > 0 ORDER BY stock_code, trade_date""", conn)

# 股票信息
info_df = pd.read_sql("SELECT stock_code, stock_name, industry FROM stock_info_new", conn)
conn.close()
info_map = {}
for _, r in info_df.iterrows():
    info_map[r['stock_code']] = (r['stock_name'], r['industry'])

df = df.dropna().sort_values(['stock_code','trade_date']).reset_index(drop=True)
counts = df.groupby('stock_code').size()
df = df[df['stock_code'].isin(counts[counts>=80].index)].copy()

all_dates = sorted(df['trade_date'].unique())

# 找月末
last_me = None
for d in reversed(all_dates):
    if d >= '2026-01-01':
        ym = d[:7]
        month_dates = [x for x in all_dates if x[:7] == ym]
        if month_dates and d == max(month_dates):
            last_me = d; break
if last_me is None: last_me = all_dates[-1]

# 市场
mk_ok = True
if last_me in idx_dates:
    mi = idx_dates.index(last_me)
    if mi >= 60:
        ma60 = np.mean(idx_closes[mi-59:mi+1])
        mk_ok = idx_closes[mi] > ma60
        print(f"HS300={idx_closes[mi]:.0f} vs MA60={ma60:.0f} -> {'MULTI' if mk_ok else 'CASH'}")

print(f"选股日: {last_me}")

# 取近70天 + 计算因子
recent_parts = []
for code, gdf in df.groupby('stock_code'):
    gdf = gdf[gdf['trade_date'] <= last_me]
    if len(gdf) < 60: continue
    recent_parts.append(gdf.tail(70))
recent = pd.concat(recent_parts, ignore_index=True)
recent = recent.sort_values(['stock_code','trade_date']).reset_index(drop=True)

grouped = recent.groupby('stock_code')
recent['ret_1d'] = grouped['close'].pct_change()

def pos_fn(g):
    return (g['ret_1d']>0).astype(float).rolling(60,min_periods=60).sum()/60
recent['pos_days_60'] = grouped.apply(pos_fn, include_groups=False).reset_index(level=0,drop=True)
recent['mom_60'] = grouped['close'].pct_change(60)
recent['vol_20'] = grouped['ret_1d'].rolling(20,min_periods=20).std().reset_index(level=0,drop=True)
recent['ma60'] = grouped['close'].rolling(60,min_periods=60).mean().reset_index(level=0,drop=True)
recent['amount'] = recent['volume']*recent['close']*100
recent['turnover20'] = grouped['amount'].rolling(20,min_periods=20).mean().reset_index(level=0,drop=True)
recent['ret_5d'] = grouped['close'].pct_change(5)
recent['high60'] = grouped['close'].rolling(60,min_periods=60).max().reset_index(level=0,drop=True)

day = recent[recent['trade_date']==last_me].dropna(
    subset=['pos_days_60','mom_60','vol_20','ma60','turnover20','ret_5d','high60']).copy()
day['dist_high60'] = (day['high60'] - day['close']) / day['high60']
day['day_chg'] = (day['close'] - day['open']) / day['open']  # 当日涨跌幅

print(f"因子计算后: {len(day)}只")

# === 多层硬过滤 ===
total = len(day)
f1 = day[day['close'] >= PRICE_MIN]; print(f"  价格>={PRICE_MIN}: {len(f1)} (淘汰{total-len(f1)})")
total = len(f1)
f2 = f1[f1['turnover20'] >= TURNOVER_MIN*10000]; print(f"  成交>={TURNOVER_MIN}万: {len(f2)} (淘汰{total-len(f2)})")
total = len(f2)
f3 = f2[f2['turnover20'] <= TURNOVER_MAX*10000]; print(f"  成交<={TURNOVER_MAX}万: {len(f3)} (淘汰{total-len(f3)})")
total = len(f3)
f4 = f3[f3['pos_days_60'] >= POS_DAYS_MIN]; print(f"  pos60>={POS_DAYS_MIN}: {len(f4)} (淘汰{total-len(f4)})")
total = len(f4)
f5 = f4[(f4['mom_60']>=MOM_60_MIN) & (f4['mom_60']<=MOM_60_MAX)]; print(f"  mom60 {MOM_60_MIN*100:.0f}-{MOM_60_MAX*100:.0f}%: {len(f5)} (淘汰{total-len(f5)})")
total = len(f5)
f6 = f5[f5['ret_5d'] <= MAX_RET_5D]; print(f"  5日涨幅<={MAX_RET_5D*100:.0f}%: {len(f6)} (淘汰{total-len(f6)})")
total = len(f6)
f7 = f6[f6['dist_high60'] >= MIN_DIST_HIGH]; print(f"  距高点>={MIN_DIST_HIGH*100:.0f}%: {len(f7)} (淘汰{total-len(f7)})")
total = len(f7)
f8 = f7[f7['day_chg'].abs() <= MAX_DAY_CHG]; print(f"  当日涨跌幅<={MAX_DAY_CHG*100:.0f}%: {len(f8)} (淘汰{total-len(f8)})")

candidates = f8

# 波动率后40%
if len(candidates) >= 3:
    vt = candidates['vol_20'].quantile(VOL_PCT)
    lowvol = candidates[candidates['vol_20'] <= vt].copy()
    if len(lowvol) < 3:
        lowvol = candidates.copy()
    lowvol = lowvol.sort_values('pos_days_60', ascending=False)
    print(f"\n  低波动筛选后: {len(lowvol)}只")
    
    # 行业分散
    selected = []
    industry_count = {}
    for _, r in lowvol.iterrows():
        code = r['stock_code']
        name_ind = info_map.get(code, (code, '未知'))
        ind = name_ind[1]
        cnt = industry_count.get(ind, 0)
        if cnt >= MAX_PER_INDUSTRY:
            continue
        selected.append(r)
        industry_count[ind] = cnt + 1
        if len(selected) >= TOP_N:
            break
    
    print(f"\n{'='*60}")
    print(f"  6月 TOP 5 推荐 (优化版)")
    print(f"{'='*60}")
    
    for i, r in enumerate(selected):
        code = r['stock_code']
        name_ind = info_map.get(code, (code, '未知'))
        name, ind = name_ind[0], name_ind[1]
        t = r['turnover20']/1e8
        dh = r['dist_high60']*100
        print(f"\n  #{i+1}  {code}  {name}  ({ind})")
        print(f"      现价: {r['close']:.2f}  |  MA60: {r['ma60']:.2f}")
        print(f"      pos60: {r['pos_days_60']:.1%}  |  mom60: {r['mom_60']*100:.1f}%")
        print(f"      vol20: {r['vol_20']:.4f}  |  5日涨幅: {r['ret_5d']*100:+.1f}%")
        print(f"      日均成交: {t:.2f}亿  |  距高点: {dh:.1f}%")
        print(f"      当日: {r['day_chg']*100:+.1f}%")
        
        # 买入建议
        lot_price = r['close'] * 100
        lots = int(40000 / lot_price)
        actual = lots * lot_price
        print(f"      买入: {lots}手×{r['close']:.2f}={actual:.0f}元")
    
    print(f"\n  --- 执行计划 ---")
    print(f"  仓位: 每只~4万, 共5只≈20万")
    print(f"  买入: 下一个交易日开盘价")
    print(f"  持有: 22个交易日 | 止损: 单票-8%")
    
    if not mk_ok:
        print(f"  !! HS300<MA60, 建议减半仓 !!")
    
    # 被过滤掉的原因统计
    print(f"\n  --- 过滤统计 (从{len(day)}只) ---")
    print(f"  原TOP5被过滤: 603701(OK), 603075(距高点0%+5日+10.4%), 000027(成交5.14亿+5日+10.5%), 600012(5日+7.1%), 001289(5日+9.5%)")
else:
    print(f"候选池太小: {len(candidates)}只")

print(f"\n总耗时: {time.time()-t0:.1f}s")
