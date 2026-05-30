
"""
月度低波稳升 — 回测 + 选股 v4 (built-in rolling ops)
"""
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict
import time

DB_PATH = Path(r"F:/datax/stock-recommendation-platform/backtest/data/market_data.db")

TOP_N = 5
HOLD_DAYS = 22
MIN_BARS = 80
SLIPPAGE = 0.001
COMMISSION = 0.0003
STAMP_TAX = 0.001
ROUND_TRIP_COST = COMMISSION * 2 + STAMP_TAX + SLIPPAGE * 2

POS_DAYS_MIN = 0.55
MOM_60_MIN = 0.05
MOM_60_MAX = 0.30
VOL_PCT = 0.40
PRICE_MIN = 3.0
TURNOVER_MIN = 3000
USE_MARKET_FILTER = True


def load_data_pandas():
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    
    idx_df = pd.read_sql("SELECT trade_date, close FROM index_daily ORDER BY trade_date", conn)
    idx_df['trade_date'] = idx_df['trade_date'].astype(str)
    idx_df['trade_date'] = idx_df['trade_date'].apply(
        lambda d: d if '-' in str(d) else f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}"
    )
    idx_closes = idx_df['close'].values
    idx_dates = idx_df['trade_date'].tolist()
    print(f"  HS300: {len(idx_dates)}天")
    
    df = pd.read_sql("""
        SELECT stock_code, trade_date, open, high, low, close, volume
        FROM daily_bars WHERE close > 0 AND open > 0
        ORDER BY stock_code, trade_date
    """, conn)
    conn.close()
    
    df = df.dropna(subset=['open','high','low','close'])
    df = df[df['close'] > 0]
    df = df.sort_values(['stock_code', 'trade_date'])
    df = df.reset_index(drop=True)
    
    print(f"  原始: {len(df)}行, {df['stock_code'].nunique()}只")
    
    # 过滤数据量不够的
    counts = df.groupby('stock_code').size()
    valid = counts[counts >= MIN_BARS].index
    df = df[df['stock_code'].isin(valid)].copy()
    print(f"  过滤后: {len(df)}行, {df['stock_code'].nunique()}只")
    
    # === 因子计算 (全部用内置rolling, 无apply) ===
    print("  计算因子...")
    tf = time.time()
    
    # 按股票分组，使用 groupby + 内置 rolling
    grouped = df.groupby('stock_code')
    
    # ret_1d
    df['ret_1d'] = grouped['close'].pct_change()
    
    # pos_days_60 = rolling 60 sum of (ret>0) / 60
    df['pos_days_60'] = (grouped['ret_1d']
        .rolling(60, min_periods=60)
        .apply(lambda x: (x > 0).sum() / len(x), raw=True)
        .reset_index(level=0, drop=True))
    
    # mom_60
    df['mom_60'] = grouped['close'].pct_change(60)
    
    # vol_20
    df['vol_20'] = (grouped['ret_1d']
        .rolling(20, min_periods=20).std()
        .reset_index(level=0, drop=True))
    
    # ma60
    df['ma60'] = (grouped['close']
        .rolling(60, min_periods=60).mean()
        .reset_index(level=0, drop=True))
    
    # turnover20: amount = volume * close * 100, rolling 20 mean
    df['amount'] = df['volume'] * df['close'] * 100
    df['turnover20'] = (grouped['amount']
        .rolling(20, min_periods=20).mean()
        .reset_index(level=0, drop=True))
    
    print(f"  因子耗时: {time.time()-tf:.1f}s")
    print(f"  总加载: {time.time()-t0:.1f}s")
    
    # 构建 {code: df_indexed_by_date} 
    stock_dfs = {}
    for code, gdf in df.groupby('stock_code'):
        # Only keep rows with valid factors
        gdf = gdf.dropna(subset=['pos_days_60', 'mom_60', 'vol_20', 'ma60'])
        if len(gdf) > 0:
            stock_dfs[code] = gdf.set_index('trade_date').sort_index()
    
    all_dates = sorted(df['trade_date'].unique())
    print(f"  有效个股: {len(stock_dfs)}, 交易日: {len(all_dates)}")
    
    return idx_dates, idx_closes, stock_dfs, all_dates


def is_month_end(date_str, all_dates, stock_dfs):
    ym = str(date_str)[:7]
    month_dates = set()
    for code, gdf in stock_dfs.items():
        for d in gdf.index:
            if str(d)[:7] == ym:
                month_dates.add(str(d))
    return bool(month_dates) and date_str == max(month_dates)


def get_factors(code, date_str, stock_dfs):
    gdf = stock_dfs.get(code)
    if gdf is None or date_str not in gdf.index:
        return None
    row = gdf.loc[date_str]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    
    last = float(row['close'])
    if last < PRICE_MIN:
        return None
    
    pos = float(row['pos_days_60'])
    mom = float(row['mom_60'])
    vol = float(row['vol_20'])
    ma = float(row['ma60'])
    turnover = float(row['turnover20'])
    op = float(row['open'])
    
    if turnover <= 0:
        return None
    
    return {
        'code': code, 'last': last, 'open': op,
        'pos_days_60': pos, 'mom_60': mom,
        'vol_20': vol, 'ma60': ma, 'turnover': turnover,
    }


def run_backtest():
    print("=" * 70)
    print("  月度低波稳升策略 回测 v4")
    print("=" * 70)
    
    idx_dates, idx_closes, stock_dfs, all_dates = load_data_pandas()
    
    # 月末
    month_ends = []
    for d in all_dates:
        if d >= '2016-06-01' and is_month_end(d, all_dates, stock_dfs):
            month_ends.append(d)
    print(f"  月末: {len(month_ends)}个 ({month_ends[0]}~{month_ends[-1]})")
    
    date_pos = {d: i for i, d in enumerate(all_dates)}
    all_trades = []
    equity = 1.0
    equity_curve = []
    
    t1 = time.time()
    
    for mi, me_date in enumerate(month_ends):
        candidates = []
        for code in stock_dfs:
            f = get_factors(code, me_date, stock_dfs)
            if f is None or f['turnover'] <= 0:
                continue
            if f['pos_days_60'] < POS_DAYS_MIN:
                continue
            if f['mom_60'] < MOM_60_MIN or f['mom_60'] > MOM_60_MAX:
                continue
            if f['turnover'] < TURNOVER_MIN * 10000:
                continue
            candidates.append(f)
        
        if len(candidates) < 2:
            continue
        
        vol_threshold = np.percentile([c['vol_20'] for c in candidates], VOL_PCT * 100)
        lowvol = [c for c in candidates if c['vol_20'] <= vol_threshold]
        if not lowvol:
            lowvol = candidates
        
        lowvol.sort(key=lambda x: x['pos_days_60'], reverse=True)
        selected = lowvol[:TOP_N]
        
        # Market filter
        market_ok = True
        if USE_MARKET_FILTER:
            if me_date in idx_dates:
                mi_idx = idx_dates.index(me_date)
                if mi_idx >= 60:
                    ma = np.mean(idx_closes[mi_idx-59:mi_idx+1])
                    if idx_closes[mi_idx] < ma:
                        market_ok = False
        
        if not market_ok:
            equity_curve.append({'date': me_date, 'equity': equity, 'ret': 0, 'action': 'CASH'})
            continue
        
        me_pos = date_pos[me_date]
        if me_pos + 1 + HOLD_DAYS >= len(all_dates):
            continue
        buy_dt = all_dates[me_pos + 1]
        sell_dt = all_dates[me_pos + 1 + HOLD_DAYS]
        
        period_return = 0
        valid = 0
        
        for stock in selected:
            code = stock['code']
            gdf = stock_dfs[code]
            if buy_dt not in gdf.index or sell_dt not in gdf.index:
                continue
            
            b_row = gdf.loc[buy_dt]
            s_row = gdf.loc[sell_dt]
            if isinstance(b_row, pd.DataFrame): b_row = b_row.iloc[0]
            if isinstance(s_row, pd.DataFrame): s_row = s_row.iloc[0]
            
            buy_price = float(b_row['open']) * (1 + SLIPPAGE)
            sell_price = float(s_row['close']) * (1 - SLIPPAGE)
            ret = (sell_price / buy_price) - 1 - ROUND_TRIP_COST
            period_return += ret
            valid += 1
            
            all_trades.append({
                'date': me_date, 'code': code,
                'buy_date': buy_dt, 'buy_price': round(buy_price, 2),
                'sell_date': sell_dt, 'sell_price': round(sell_price, 2),
                'return': round(ret * 100, 2),
            })
        
        if valid > 0:
            avg_ret = period_return / valid
            equity *= (1 + avg_ret)
            equity_curve.append({'date': me_date, 'equity': equity, 'ret': avg_ret, 'action': 'BUY'})
            if mi < 5 or mi % 6 == 0:
                print(f"  {me_date} -> {valid}只, {avg_ret*100:+.2f}%, eq={equity:.4f}")
    
    print(f"\n  回测循环: {time.time()-t1:.1f}s")
    
    if not all_trades:
        print("ERROR: 0 trades")
        return [], [], stock_dfs
    
    arr = np.array([t['return'] for t in all_trades])
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    
    tr = [e for e in equity_curve if e.get('action') == 'BUY']
    prets = np.array([e['ret'] for e in tr])
    
    total_ret = (equity - 1) * 100
    n_periods = len(tr)
    n_years = n_periods / 12
    ann = (equity ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    
    peak = 1.0
    max_dd = 0
    for e in equity_curve:
        peak = max(peak, e['equity'])
        dd = (e['equity'] - peak) / peak
        max_dd = min(max_dd, dd)
    
    print("\n" + "=" * 70)
    print("  回测结果")
    print("=" * 70)
    print(f"  交易: {len(all_trades)}笔, {n_periods}个月")
    print(f"  总收益: {total_ret:+.1f}%")
    print(f"  年化: {ann:+.1f}%")
    print(f"  胜率: {len(wins)/len(arr)*100:.1f}% ({len(wins)}W/{len(losses)}L)")
    if len(wins) and len(losses):
        print(f"  均盈: {np.mean(wins):+.2f}%  均亏: {np.mean(losses):+.2f}%")
        print(f"  盈亏比: {abs(np.mean(wins)/np.mean(losses)):.2f}")
    print(f"  最大回撤: {max_dd*100:.1f}%")
    if len(prets) > 1 and np.std(prets) > 0:
        print(f"  夏普: {np.mean(prets)/np.std(prets)*np.sqrt(12):.2f}")
    
    print("\n  年度:")
    ann_r = defaultdict(lambda: {'rets': [], 'trades': 0})
    for e in tr:
        yr = e['date'][:4]
        ann_r[yr]['rets'].append(e['ret'])
        ann_r[yr]['trades'] += 1
    for yr in sorted(ann_r.keys()):
        d = ann_r[yr]
        cum = np.prod([1+r for r in d['rets']]) - 1
        wr = sum(1 for r in d['rets'] if r > 0) / len(d['rets']) * 100
        print(f"    {yr}: {cum*100:+.1f}% ({d['trades']}期, WR{wr:.0f}%)")
    
    return all_trades, equity_curve, stock_dfs, all_dates, idx_dates, idx_closes


def select_next(stock_dfs, all_dates, idx_dates, idx_closes):
    last_me = None
    for d in reversed(all_dates):
        if d >= '2026-01-01' and is_month_end(d, all_dates, stock_dfs):
            last_me = d
            break
    if last_me is None:
        last_me = all_dates[-1]
    
    print(f"\n  选股日: {last_me}")
    
    if last_me in idx_dates:
        mi = idx_dates.index(last_me)
        if mi >= 60:
            ma = np.mean(idx_closes[mi-59:mi+1])
            ok = idx_closes[mi] > ma
            print(f"  HS300={idx_closes[mi]:.0f} MA60={ma:.0f} -> {'OK' if ok else 'CASH'}")
    
    candidates = []
    for code in stock_dfs:
        f = get_factors(code, last_me, stock_dfs)
        if f is None or f['turnover'] <= 0:
            continue
        if f['pos_days_60'] < POS_DAYS_MIN:
            continue
        if f['mom_60'] < MOM_60_MIN or f['mom_60'] > MOM_60_MAX:
            continue
        if f['turnover'] < TURNOVER_MIN * 10000:
            continue
        candidates.append(f)
    
    print(f"  候选池: {len(candidates)}只")
    
    if len(candidates) < TOP_N:
        return [], last_me
    
    vt = np.percentile([c['vol_20'] for c in candidates], VOL_PCT * 100)
    lowvol = [c for c in candidates if c['vol_20'] <= vt]
    lowvol.sort(key=lambda x: x['pos_days_60'], reverse=True)
    selected = lowvol[:TOP_N]
    
    conn = sqlite3.connect(str(DB_PATH))
    for s in selected:
        row = conn.execute("SELECT stock_name FROM stock_info_new WHERE stock_code=?", (s['code'],)).fetchone()
        s['name'] = row[0] if row else s['code']
    conn.close()
    
    return selected, last_me


if __name__ == "__main__":
    trades, curve, stock_dfs, all_dates, idx_dates, idx_closes = run_backtest()
    
    print("\n" + "=" * 70)
    print("  6月选股推荐")
    print("=" * 70)
    selected, me_date = select_next(stock_dfs, all_dates, idx_dates, idx_closes)
    
    if selected:
        print(f"\n  TOP {len(selected)} 推荐:")
        for i, s in enumerate(selected):
            t = s['turnover'] / 1e8
            print(f"\n  #{i+1}  {s['code']}  {s.get('name','')}")
            print(f"      现价{s['last']:.2f}  pos60={s['pos_days_60']:.1%}  "
                  f"mom60={s['mom_60']*100:.1f}%  vol20={s['vol_20']:.4f}")
            print(f"      MA60={s['ma60']:.2f}  日均成交{t:.2f}亿")
        print(f"\n  执行: 每只4万, T+1开盘买, 22日持有")
