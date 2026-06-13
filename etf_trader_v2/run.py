#!/usr/bin/env python3
"""CLI入口 — 展示ETF信号

用法:
    python run.py            # 显示所有信号
    python run.py buy        # 仅显示买入信号
    python run.py watch      # 仅显示关注列表
    python run.py rank       # 按评分排名显示
"""
import sys
from datetime import date

import numpy as np

from config import POOL, MAX_HOLD
from engine.decision import decide
from engine.indicators import bollinger_bands, rsi, atr, ma, chg_pct, vol_ratio
from engine.scoring import composite_score
from models.etf_data import ETFDataRepo
from models.holdings import HoldingsRepo


def run():
    repo = ETFDataRepo()
    quotes = repo.get_all_quotes(lookback=66)
    metrics = repo.compute_metrics(quotes)
    market = repo.get_market()
    holdings_repo = HoldingsRepo()
    all_holdings = holdings_repo.list_all()
    held_codes = {h['code']: h for h in all_holdings}

    results = []

    for code, name in POOL.items():
        rows = quotes.get(code, [])

        if not rows or len(rows) < 21 or code not in metrics:
            results.append({
                'code': code, 'name': name,
                'action': 'NO_DATA', 'reason': '缺少数据',
                'score': 0, 'close': 0, 'bb_pos': 0, 'rsi': 0,
                'chg_5d': 0, 'chg_20d': 0, 'trend': '?',
            })
            continue

        closes = np.array([r['close'] for r in rows])
        highs = np.array([r['high'] for r in rows])
        lows = np.array([r['low'] for r in rows])
        volumes = np.array([r['volume'] for r in rows])
        met = metrics[code]

        _, _, _, bb_pos = bollinger_bands(closes)
        rsi_val = rsi(closes)
        ma20_val = ma(closes, 20)
        ma60_val = ma(closes, 60)
        sc, _ = composite_score(closes, highs, lows, volumes)

        held = code in held_codes
        entry_pnl = 0.0
        if held:
            h = held_codes[code]
            if h['buy_price'] > 0 and met['close'] > 0:
                entry_pnl = (met['close'] - h['buy_price']) / h['buy_price']

        d = decide(
            code=code, score=sc, bb_pos=bb_pos, rsi_val=rsi_val,
            ma20=ma20_val, ma60=ma60_val, close=met['close'],
            chg_5d=met['chg_5d'], chg_20d=met['chg_20d'],
            atr_pct=met['atr_pct'], vol_ratio=met['vol_ratio'],
            market_state=market.get('state', 'unknown'),
            held=held, entry_pnl=entry_pnl,
        )
        d['code'] = code
        d['name'] = name
        results.append(d)

    # === 输出 ===
    latest = repo.latest_date() or str(date.today())
    held_count = len(all_holdings)

    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    print(f"\n{'='*60}")
    print(f"  ETF 布林带轮动 v2 — {latest}")
    print(f"  大盘: {market.get('state','?')}({market.get('trend',0):+.1f}%) | "
          f"池子{len(POOL)}只 | 持仓{held_count}/{MAX_HOLD}")
    print(f"{'='*60}")

    buys = [r for r in results if r['action'] == 'BUY']
    watches = [r for r in results if r['action'] == 'WATCH']
    sells = [r for r in results if r['action'] in ('SELL', 'TAKE_PROFIT', 'STOP')]
    holds = [r for r in results if r['action'] == 'HOLD']
    avoids = [r for r in results if r['action'] == 'AVOID']

    buys.sort(key=lambda x: -x['score'])
    watches.sort(key=lambda x: x['bb_pos'])

    if mode == 'buy':
        _print_buys(buys)
    elif mode == 'watch':
        _print_watches(watches)
    elif mode == 'rank':
        ranked = sorted(results, key=lambda x: -x['score'])
        _print_rank(ranked)
    else:
        _print_buys(buys)
        _print_sells(sells)
        _print_holds(holds)
        _print_watches(watches)


def _print_buys(buys):
    if not buys:
        print("\n  暂无买入信号")
        return
    print(f"\n  🟢 买入信号 ({len(buys)}只)")
    print(f"  {'代码':<8} {'名称':<12} {'现价':>7} {'评分':>6} {'布林':>6} {'5日':>7} {'20日':>7} {'RSI':>5}")
    print(f"  {'-'*65}")
    for r in buys:
        print(f"  {r['code']:<8} {r['name']:<12} {r['close']:>7.3f} {r['score']:+6.0f} "
              f"{r['bb_pos']:>5.0%} {r['chg_5d']:+6.1f}%{r['chg_20d']:+6.1f}% {r['rsi']:>5.0f}")
        print(f"    → {r['reason']}")


def _print_watches(watches):
    if not watches:
        return
    print(f"\n  👀 关注 ({len(watches)}只)")
    for r in watches[:6]:
        print(f"  {r['code']} {r['name']:<12} 评分{r['score']:+5.0f} "
              f"布林{r['bb_pos']:.0%} {r['chg_5d']:+5.1f}% → {r['reason']}")


def _print_sells(sells):
    if not sells:
        return
    print(f"\n  🔴 卖出/止损 ({len(sells)}只)")
    print(f"  {'代码':<8} {'名称':<12} {'现价':>7} {'评分':>6}")
    print(f"  {'-'*40}")
    for r in sells:
        print(f"  {r['code']:<8} {r['name']:<12} {r['close']:>7.3f} {r['score']:+6.0f}")
        print(f"    → {r['reason']}")


def _print_holds(holds):
    if not holds:
        return
    print(f"\n  💤 持仓观望 ({len(holds)}只)")
    for r in holds:
        print(f"  {r['code']} {r['name']:<12} {r['close']:>7.3f} 评分{r['score']:+5.0f}")


def _print_rank(ranked):
    print(f"\n  📊 评分排名")
    print(f"  {'#':<3} {'代码':<8} {'名称':<12} {'现价':>7} {'评分':>6} {'布林':>6} {'RSI':>5} {'操作':<12}")
    print(f"  {'-'*70}")
    for i, r in enumerate(ranked):
        if r['action'] == 'NO_DATA':
            continue
        print(f"  {i+1:<3} {r['code']:<8} {r['name']:<12} {r['close']:>7.3f} "
              f"{r['score']:+6.0f} {r['bb_pos']:>5.0%} {r['rsi']:>5.0f} {r['action']:<12}")


if __name__ == '__main__':
    run()
