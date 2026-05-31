import sqlite3
import numpy as np
from pathlib import Path
from collections import defaultdict
import time

DB_PATH = Path(r"F:/datax/stock-recommendation-platform/backtest/data/market_data.db")

# ============================================================
# 参数
# ============================================================
STOP_LOSS = -0.07
TRAIL_ACTIVATE = 0.08
TRAIL_BACK_PCT = 0.03
MAX_HOLD_DAYS = 20
SCORE_THRESHOLD = 0.02
SLIPPAGE = 0.002      # 0.2%滑点
COMMISSION = 0.0015   # 单边0.15%（佣金万1.5+印花税千1 平均）

print("=" * 60)
print("  V6 修正版回测: T+1开盘买入 + 滑点0.2% + 佣金0.15%")
print("=" * 60)

# ============================================================
# 加载数据
# ============================================================
print("\n加载数据...")
conn = sqlite3.connect(str(DB_PATH))

cur = conn.execute("SELECT trade_date, close FROM index_daily ORDER BY trade_date")
_raw_index = cur.fetchall()
# 统一日期格式为 YYYY-MM-DD（daily_bars用这个格式）
def normalize_date(d):
    if '-' in d:
        return d
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
index_data = [(normalize_date(r[0]), r[1]) for r in _raw_index]
index_dict = {r[0]: r[1] for r in index_data}
index_dates = [r[0] for r in index_data]
date_to_idx = {d: i for i, d in enumerate(index_dates)}
print(f"  沪深300: {len(index_data)} 天 ({index_dates[0]}~{index_dates[-1]})")

cur = conn.execute("""
    SELECT stock_code, trade_date, open, high, low, close, volume
    FROM daily_bars ORDER BY stock_code, trade_date
""")

stock_bars = defaultdict(list)
for row in cur:
    code, dt, op, hi, lo, cl, vol = row
    if op and cl and hi and lo and float(cl) > 0:
        stock_bars[code].append({
            'd': dt, 'o': float(op), 'h': float(hi),
            'l': float(lo), 'c': float(cl), 'v': float(vol) if vol else 0
        })

conn.close()

stock_date_idx = {}
for code, bars in stock_bars.items():
    stock_date_idx[code] = {b['d']: i for i, b in enumerate(bars)}

print(f"  股票: {len(stock_bars)} 只")

# ============================================================
# 核心函数
# ============================================================
def get_market_state(day_idx):
    if day_idx < 60:
        return "中性", 3
    closes = [index_data[i][1] for i in range(day_idx-59, day_idx+1)]
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes)
    latest = closes[-1]
    if latest >= ma60 and ma20 >= ma60:
        return "牛市", 5
    elif latest >= ma60:
        return "中性", 3
    else:
        return "熊市", 2

def score_stock(code, date_str):
    if code not in stock_date_idx or date_str not in stock_date_idx[code]:
        return None
    idx = stock_date_idx[code][date_str]
    bars = stock_bars[code]
    if idx < 60:
        return None
    close = bars[idx]['c']
    if close < 3:
        return None
    c5, c10, c20 = bars[idx-5]['c'], bars[idx-10]['c'], bars[idx-20]['c']
    c60 = bars[max(0, idx-60)]['c']
    if c5==0 or c10==0 or c20==0 or c60==0:
        return None
    ret5 = (close-c5)/c5
    ret10 = (close-c10)/c10
    ret20 = (close-c20)/c20
    prev_c = bars[idx-1]['c']
    if prev_c > 0 and (close-prev_c)/prev_c > 0.095:
        return None
    if ret5 > 0.12 or ret20 > 0.30 or ret5 < -0.03:
        return None
    vol_20 = np.mean([bars[idx-j]['v'] for j in range(20)])
    if vol_20 < 3000:
        return None
    vol_5 = np.mean([bars[idx-j]['v'] for j in range(5)])
    vol_ratio = vol_5/vol_20 if vol_20 > 0 else 0
    if vol_ratio < 0.8:
        return None
    ma5 = np.mean([bars[idx-j]['c'] for j in range(5)])
    ma20 = np.mean([bars[idx-j]['c'] for j in range(20)])
    ma60 = np.mean([bars[idx-j]['c'] for j in range(min(60, idx+1))])
    if close < ma5 or close < ma20 or ma5 < ma20:
        return None
    trend = (0.5 if ma20 > ma60 else 0) + (0.5 if ma5 > ma20 else 0)
    rets = [(bars[idx-j]['c']-bars[idx-j-1]['c'])/bars[idx-j-1]['c'] for j in range(1,21) if bars[idx-j-1]['c']>0]
    if rets and np.std(rets) > 0.04:
        return None
    hi, op = bars[idx]['h'], bars[idx]['o']
    body = abs(close - op)
    upper = hi - max(close, op)
    if body > 0 and upper > 1.5 * body:
        return None
    momentum = (ret5*2 + ret10 + ret20*0.5) / 3.5
    score = momentum*0.45 + min(vol_ratio,2.5)/2.5*0.20 + trend*0.35
    return score if score > SCORE_THRESHOLD else None

# ============================================================
# 回测主循环
# ============================================================
print("\n回测中...")
capital = 200000.0
positions = []
closed_trades = []
equity_curve = []
yearly_equity = {}

start_idx = 61
total_days = len(index_dates)
t0 = time.time()

for day_idx in range(start_idx, total_days - 1):
    today = index_dates[day_idx]
    tomorrow = index_dates[day_idx + 1]
    
    # 1. 检查持仓
    new_positions = []
    for pos in positions:
        code = pos['code']
        if today not in stock_date_idx.get(code, {}):
            new_positions.append(pos)
            continue
        bar_idx = stock_date_idx[code][today]
        bar = stock_bars[code][bar_idx]
        hold_days = day_idx - pos['buy_idx']
        sold = False
        sell_price = 0
        sell_reason = ""
        
        # 止损
        if bar['l'] <= pos['stop_loss']:
            sell_price = pos['stop_loss']
            sell_reason = "止损"
            sold = True
        
        # 移动止盈
        if not sold:
            if not pos['trail_active'] and bar['h'] >= pos['trail_activate']:
                pos['trail_active'] = True
                pos['highest'] = bar['h']
                pos['trail_sell'] = pos['highest'] * (1 - TRAIL_BACK_PCT)
            if pos['trail_active']:
                if bar['h'] > pos['highest']:
                    pos['highest'] = bar['h']
                    pos['trail_sell'] = pos['highest'] * (1 - TRAIL_BACK_PCT)
                if bar['l'] <= pos['trail_sell']:
                    sell_price = pos['trail_sell']
                    sell_reason = "止盈"
                    sold = True
        
        # 超时
        if not sold and hold_days >= MAX_HOLD_DAYS:
            sell_price = bar['c']
            sell_reason = "超时"
            sold = True
        
        if sold:
            net_sell = sell_price * (1 - COMMISSION - SLIPPAGE)
            pnl = (net_sell - pos['buy_price']) * pos['shares']
            capital += net_sell * pos['shares']
            closed_trades.append({
                'buy_date': pos['buy_date'], 'sell_date': today,
                'buy_price': pos['buy_price'], 'sell_price': sell_price,
                'pnl': pnl, 'pnl_pct': (net_sell - pos['buy_price'])/pos['buy_price'],
                'hold_days': hold_days, 'reason': sell_reason,
            })
        else:
            new_positions.append(pos)
    positions = new_positions
    
    # 2. 大盘状态
    state, max_pos = get_market_state(day_idx)
    
    # 3. 选股买入（T+1开盘价）
    if len(positions) < max_pos:
        scores = []
        for code in stock_bars:
            s = score_stock(code, today)
            if s is not None and tomorrow in stock_date_idx.get(code, {}):
                scores.append((code, s))
        scores.sort(key=lambda x: -x[1])
        
        slots_available = max_pos - len(positions)
        pos_value = sum(
            stock_bars[p['code']][stock_date_idx[p['code']][today]]['c'] * p['shares']
            if today in stock_date_idx.get(p['code'], {}) else p['buy_price'] * p['shares']
            for p in positions
        )
        total_equity = capital + pos_value
        slot_size = total_equity / max_pos
        
        bought = 0
        for code, score in scores:
            if bought >= slots_available:
                break
            if any(p['code'] == code for p in positions):
                continue
            t1_idx = stock_date_idx[code][tomorrow]
            open_price = stock_bars[code][t1_idx]['o']
            buy_price = open_price * (1 + SLIPPAGE + COMMISSION)
            shares = int(slot_size / buy_price / 100) * 100
            if shares < 100:
                continue
            cost = shares * buy_price
            if cost > capital:
                shares = int(capital / buy_price / 100) * 100
                if shares < 100:
                    continue
                cost = shares * buy_price
            capital -= cost
            positions.append({
                'code': code, 'buy_price': buy_price,
                'buy_date': tomorrow, 'buy_idx': day_idx + 1,
                'shares': shares,
                'stop_loss': open_price * (1 + STOP_LOSS),
                'trail_activate': open_price * (1 + TRAIL_ACTIVATE),
                'trail_active': False, 'highest': open_price, 'trail_sell': 0,
            })
            bought += 1
    
    # 权益
    pos_value = sum(
        stock_bars[p['code']][stock_date_idx[p['code']][today]]['c'] * p['shares']
        if today in stock_date_idx.get(p['code'], {}) else p['buy_price'] * p['shares']
        for p in positions
    )
    total_equity = capital + pos_value
    equity_curve.append((today, total_equity))
    
    # 年度记录
    year = today[:4]
    if year not in yearly_equity:
        yearly_equity[year] = total_equity
    yearly_equity[year] = total_equity

elapsed = time.time() - t0
print(f"  完成! 耗时 {elapsed:.1f}s")

# ============================================================
# 统计
# ============================================================
final_equity = equity_curve[-1][1]
total_return = (final_equity - 200000) / 200000 * 100
years = (total_days - start_idx) / 252
annual_return = ((final_equity / 200000) ** (1/years) - 1) * 100

wins = [t for t in closed_trades if t['pnl'] > 0]
losses = [t for t in closed_trades if t['pnl'] <= 0]
win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
avg_win = np.mean([t['pnl_pct'] for t in wins]) * 100 if wins else 0
avg_loss = np.mean([abs(t['pnl_pct']) for t in losses]) * 100 if losses else 0
profit_ratio = avg_win / avg_loss if avg_loss > 0 else 0

# 最大回撤
peak = 200000
max_dd = 0
for _, eq in equity_curve:
    if eq > peak:
        peak = eq
    dd = (peak - eq) / peak
    if dd > max_dd:
        max_dd = dd

# Sharpe
returns = []
for i in range(1, len(equity_curve)):
    r = (equity_curve[i][1] - equity_curve[i-1][1]) / equity_curve[i-1][1]
    returns.append(r)
sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if returns else 0

print(f"\n{'='*60}")
print(f"  V6 修正版回测结果 (T+1开盘+滑点+佣金)")
print(f"{'='*60}")
print(f"  初始资金:   200,000")
print(f"  最终权益:   {final_equity:,.0f}")
print(f"  总收益:     {total_return:+.1f}%")
print(f"  年化收益:   {annual_return:.1f}%")
print(f"  Sharpe:     {sharpe:.2f}")
print(f"  最大回撤:   {max_dd*100:.1f}%")
print(f"  总交易:     {len(closed_trades)} 笔")
print(f"  胜率:       {win_rate:.1f}%")
print(f"  平均盈利:   {avg_win:.1f}%")
print(f"  平均亏损:   {avg_loss:.1f}%")
print(f"  盈亏比:     {profit_ratio:.2f}")

# 年度表现
print(f"\n  年度表现:")
prev_eq = 200000
years_list = sorted(yearly_equity.keys())
for y in years_list:
    eq = yearly_equity[y]
    yr_ret = (eq - prev_eq) / prev_eq * 100
    print(f"    {y}: {yr_ret:+.1f}%  (权益 {eq:,.0f})")
    prev_eq = eq

# 卖出原因统计
reasons = defaultdict(int)
for t in closed_trades:
    reasons[t['reason']] += 1
print(f"\n  卖出原因:")
for r, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f"    {r}: {cnt} 笔 ({cnt/len(closed_trades)*100:.1f}%)")

# 对比原版
print(f"\n{'='*60}")
print(f"  对比:")
print(f"    原版(收盘价买入):  年化31.2%  Sharpe 0.99  回撤33.9%")
print(f"    修正版(T+1开盘):   年化{annual_return:.1f}%  Sharpe {sharpe:.2f}  回撤{max_dd*100:.1f}%")
print(f"    折扣率:            {annual_return/31.2*100:.0f}%")
print(f"{'='*60}")
