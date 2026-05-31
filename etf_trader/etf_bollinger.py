"""ETF布林带轮动 — 18只精选池
信号体系：数据库评分(趋势+MACD+RSI)为主，布林带为过滤器。
GPT-5.5策划 → Hermes开发 → 用户agent验收 → Hermes修复v2
"""
import pymysql, json, sys
from datetime import date
from pathlib import Path
from collections import defaultdict
import numpy as np

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root",
         "database":"etf_trader","charset":"utf8mb4"}

# === 池子 ===
POOL = {
    '562500': '机器人ETF',   '513100': '纳指ETF',
    '159949': '创业板50',    '515700': '新能源车',
    '159755': '电池ETF',     '561700': '电力ETF',
    '515790': '光伏ETF华泰', '515880': '通信ETF',
    '159996': '家电ETF',     '516880': '光伏ETF银华',
    '513180': '恒生科技',    '159605': '中概互联广发',
    '159607': '中概互联嘉实','159751': '港股通科技',
    '159711': '港股通50华夏','159726': '港股高股息',
    '159792': '港股互联网',  '513050': '中概互联ETF',
}

# === 参数 ===
MAX_HOLD = 6
STOP_LOSS = -0.08
TOLERANCE = 0.5           # 浮点阈值容差
BOLL_OVERHEAT = 0.90      # 布林过热线
BOLL_OVERSOLD = 0.25      # 布林超卖线
POSITION_FILE = Path(__file__).parent / "etf_positions.json"


def get_data():
    """一次查询拉取所有需要的数据"""
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT MAX(date) FROM indicators")
    latest = str(cur.fetchone()['MAX(date)'])

    codes = list(POOL.keys())
    ph = ','.join(['%s']*len(codes))

    # 最近66天的high/low/close/volume（用于ATR和涨跌幅）
    cur.execute(f"""
        SELECT code, date, high, low, close, volume FROM quote
        WHERE code IN ({ph}) AND date >= DATE_SUB(%s, INTERVAL 66 DAY)
        ORDER BY code, date
    """, codes + [latest])

    quotes = defaultdict(list)
    for r in cur.fetchall():
        quotes[r['code']].append({
            'date': str(r['date']),
            'high': float(r['high']),
            'low': float(r['low']),
            'close': float(r['close']),
            'volume': float(r['volume']),
        })

    # 最新indicators（布林带、RSI、MACD等）
    cur.execute(f"SELECT code, data FROM indicators WHERE code IN ({ph}) AND date=%s", codes + [latest])
    indicators = {}
    for r in cur.fetchall():
        indicators[r['code']] = json.loads(r['data'])

    # 最新signals（评分）
    cur.execute(f"""
        SELECT code,
               CAST(JSON_EXTRACT(signal_meta,'$.score') AS DOUBLE) as sc,
               CAST(JSON_EXTRACT(signal_meta,'$.s_trend') AS DOUBLE) as st
        FROM signals WHERE code IN ({ph}) AND `date`=%s
    """, codes + [latest])
    signals = {}
    for r in cur.fetchall():
        signals[r['code']] = {'score': r['sc'] or 0, 'trend': r['st'] or 0}

    # 市场指数（上证）
    cur.execute("""
        SELECT close FROM market_index_quote
        WHERE index_code='000001' AND date >= DATE_SUB(%s, INTERVAL 60 DAY)
        ORDER BY date
    """, (latest,))
    idx_closes = [float(r['close']) for r in cur.fetchall()]
    market = _market_env(idx_closes)

    conn.close()
    return latest, quotes, indicators, signals, market


def _market_env(closes):
    """判断大盘环境：上升/震荡/下跌"""
    if len(closes) < 20:
        return {'state': 'unknown', 'ma20_trend': 0}
    arr = np.array(closes)
    ma20 = np.mean(arr[-20:])
    current = arr[-1]
    ma20_5d_ago = np.mean(arr[-25:-5]) if len(arr) >= 25 else ma20
    trend = (ma20 - ma20_5d_ago) / ma20_5d_ago * 100

    if trend > 1:
        state = 'bull'
    elif trend < -1:
        state = 'bear'
    else:
        state = 'range'

    return {
        'state': state,
        'current': current,
        'ma20': ma20,
        'ma20_trend': trend,
        'volatility': float(np.std(arr[-20:] / arr[-21:-1] - 1) if len(arr) >= 21 else 0),
    }


def compute_metrics(quotes):
    """从high/low/close计算ATR、涨跌幅、成交量"""
    result = {}
    for code, rows in quotes.items():
        if len(rows) < 21:
            continue

        closes = [r['close'] for r in rows]
        highs = [r['high'] for r in rows]
        lows = [r['low'] for r in rows]
        volumes = [r['volume'] for r in rows]

        current = closes[-1]
        chg_5d = (current / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
        chg_20d = (current / closes[-21] - 1) * 100 if len(closes) >= 21 else 0

        # True Range (正确的ATR)
        tr_list = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr_list.append(tr)
        atr14 = np.mean(tr_list[-14:]) if len(tr_list) >= 14 else (np.mean(tr_list) if tr_list else 0)
        atr_pct = (atr14 / current * 100) if current > 0 else 0

        # 成交量
        vol_ma20 = np.mean(volumes[-21:]) if len(volumes) >= 21 else 0
        vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 > 0 else 1

        result[code] = {
            'close': current,
            'chg_5d': chg_5d,
            'chg_20d': chg_20d,
            'atr_pct': atr_pct,
            'vol_ratio': vol_ratio,
            'lowest_20d': min(lows[-20:]),
        }
    return result


def decide(code, indicators, signals, metrics, market, held, entry_pnl):
    """
    核心决策逻辑：
    - 评分为主（趋势+MACD+RSI的综合信号）
    - 布林为过滤器（高位不追、低位可接）
    - 大盘熊市时只卖不买
    """
    ind = indicators.get(code, {})
    sig = signals.get(code, {})
    met = metrics.get(code, {})

    if not ind or not met:
        return {'action': 'NO_DATA', 'reason': '缺少指标或行情数据', 'score': 0}

    score = sig.get('score', 0)
    bb_lower = ind.get('bb_lower', 0)
    bb_upper = ind.get('bb_upper', 0)
    bb_mid = ind.get('bb_mid', 0)
    ma20 = ind.get('ma20', 0)
    ma60 = ind.get('ma60', 0)
    rsi = ind.get('rsi', 50)
    close = met['close']

    bb_range = bb_upper - bb_lower
    bb_pos = (close - bb_lower) / bb_range if bb_range > 0 else 0.5

    # === 评分体系（主导）===
    strong_buy = score >= 50               # 数据库强烈看多
    buy_signal = score >= 30               # 数据库看多
    neutral = -30 <= score < 30            # 中性
    sell_signal = score < -30              # 数据库看空
    strong_sell = score < -70              # 数据库强烈看空

    # === 布林过滤器（辅助）===
    overheated = bb_pos > BOLL_OVERHEAT    # 过热
    oversold = bb_pos < BOLL_OVERSOLD      # 超卖
    mid_low = bb_pos < 0.50                # 中下部

    # === 趋势 ===
    uptrend = ma20 > ma60

    # === 大盘限制 ===
    bear_block = market['state'] == 'bear'

    # === 决策矩阵 ===
    action = 'HOLD'
    reason = ''

    # 先检查止损
    if held and entry_pnl <= STOP_LOSS:
        return {'action': 'STOP',
                'reason': f'硬止损 {entry_pnl*100:.1f}%',
                'score': score, 'bb_pos': bb_pos, 'rsi': rsi}

    if strong_buy:
        if oversold:
            action = 'BUY'
            reason = f'超卖+强看多 (布林{bb_pos:.0%} 评分{score:.0f})'
        elif mid_low:
            action = 'BUY'
            reason = f'回调+强看多 (布林{bb_pos:.0%} 评分{score:.0f})'
        elif overheated:
            if held:
                action = 'TAKE_PROFIT'
                reason = f'冲顶止盈 (布林{bb_pos:.0%} RSI{rsi:.0f})'
            else:
                action = 'AVOID'
                reason = f'强看多但已冲顶 等回调 (布林{bb_pos:.0%} RSI{rsi:.0f})'
        else:
            action = 'HOLD' if held else 'WATCH'
            reason = f'强看多但偏高 等回踩 (布林{bb_pos:.0%})'

    elif buy_signal:
        if oversold:
            if bear_block:
                action = 'WATCH'
                reason = f'超卖但大盘熊市 等企稳 (布林{bb_pos:.0%})'
            else:
                action = 'BUY'
                reason = f'超卖+看多 (布林{bb_pos:.0%} 评分{score:.0f})'
        elif mid_low:
            action = 'WATCH'
            reason = f'中性偏低 评分{score:.0f} 等信号'
        elif overheated:
            if held:
                action = 'TAKE_PROFIT'
                reason = f'高位+评分{score:.0f} 建议止盈'
            else:
                action = 'AVOID'
                reason = f'高位 不追 (布林{bb_pos:.0%})'
        else:
            action = 'HOLD'
            reason = f'评分{score:.0f} 中高位观望'

    elif neutral:
        if oversold:
            action = 'WATCH'
            reason = f'超卖但评分中性({score:.0f}) 等转强'
        elif overheated:
            if held:
                action = 'TAKE_PROFIT'
                reason = f'高位+评分中性 减仓'
            else:
                action = 'AVOID'
                reason = f'高位+无信号 不碰'
        else:
            action = 'HOLD' if held else 'AVOID'
            reason = f'中性({score:.0f}) 无信号'

    elif sell_signal:
        if held:
            action = 'STOP' if strong_sell else 'SELL'
            reason = f'看空信号 评分{score:.0f}'
        else:
            action = 'AVOID'
            reason = f'评分差({score:.0f}) 不参与'

    # 大盘熊市 + 买入信号 → 降级为WATCH
    if action == 'BUY' and bear_block:
        action = 'WATCH'
        reason += ' [大盘熊市]'

    # 趋势过滤器：下跌趋势不买
    if action == 'BUY' and not uptrend:
        action = 'WATCH'
        reason += ' [下跌趋势]'

    # 成交量：缩量不买
    if action == 'BUY' and met.get('vol_ratio', 1) < 0.5:
        action = 'WATCH'
        reason += ' [缩量]'

    return {
        'action': action,
        'reason': reason,
        'score': score,
        'bb_pos': bb_pos,
        'rsi': rsi,
        'ma20': ma20,
        'ma60': ma60,
        'close': close,
        'chg_5d': met['chg_5d'],
        'chg_20d': met['chg_20d'],
        'atr_pct': met['atr_pct'],
    }


def load_positions():
    if POSITION_FILE.exists():
        return json.loads(POSITION_FILE.read_text(encoding='utf-8'))
    return {}


def run():
    latest, quotes, indicators, signals, market = get_data()
    metrics = compute_metrics(quotes)
    positions = load_positions()

    # 检查僵尸ETF
    zombies = [code for code in POOL if code not in indicators]
    if zombies:
        print(f"\n  ⚠ 无数据ETF: {', '.join(zombies)} — 已从池子跳过")

    results = []
    buys, watches, sells, holds, avoids = [], [], [], [], []

    for code, name in POOL.items():
        if code in zombies:
            continue

        entry = positions.get(code, {})
        held = code in positions
        entry_price = entry.get('cost', 0)
        close = metrics.get(code, {}).get('close', 0)
        pnl = (close - entry_price) / entry_price if held and entry_price > 0 else 0

        d = decide(code, indicators, signals, metrics, market, held, pnl)
        d['code'] = code
        d['name'] = name
        d['held'] = held
        d['entry_price'] = entry_price
        d['pnl'] = pnl
        d['trend_str'] = '↑' if d.get('ma20', 0) > d.get('ma60', 0) else '↓'
        d['risk_str'] = '⚠过热' if d.get('rsi', 50) > 70 else ('💧超卖' if d.get('rsi', 50) < 30 else '正常')

        results.append(d)

        action = d['action']
        if action == 'BUY':
            buys.append(d)
        elif 'WATCH' in action:
            watches.append(d)
        elif action in ('SELL', 'TAKE_PROFIT', 'STOP'):
            sells.append(d)
        elif action == 'AVOID':
            avoids.append(d)
        else:
            holds.append(d)

    # 排序：BUY按score降序，WATCH按bb_pos升序(更接近下轨的优先)
    buys.sort(key=lambda x: -x['score'])
    watches.sort(key=lambda x: x['bb_pos'])
    sells.sort(key=lambda x: -x['score'])
    holds.sort(key=lambda x: -x['score'])

    # === 输出 ===
    print(f"\n{'='*60}")
    print(f"  ETF 布林带轮动 v2 — {latest}")
    print(f"  大盘: {market['state']}({market['ma20_trend']:+.1f}%) | "
          f"池子{len(POOL)}只 | 持仓{len(positions)}/{MAX_HOLD}")
    print(f"  📈 评分为主 ✓ | 📊 布林过滤 ✓ | 🌡 大盘感知 ✓")
    print(f"{'='*60}")

    # 买入
    if buys:
        print(f"\n  🟢 买入信号 ({len(buys)}只)")
        print(f"  {'代码':<8} {'名称':<12} {'现价':>7} {'评分':>6} {'布林':>6} {'5日':>7} {'20日':>7} {'RSI':>5}")
        print(f"  {'-'*65}")
        for r in buys:
            print(f"  {r['code']:<8} {r['name']:<12} {r['close']:>7.3f} {r['score']:+6.0f} "
                  f"{r['bb_pos']:>5.0%} {r['chg_5d']:+6.1f}%{r['chg_20d']:+6.1f}% {r['rsi']:>5.0f}")
            print(f"    → {r['reason']}")

    # 持仓中的高位（卖出）
    if sells:
        print(f"\n  🔴 卖出/止损 ({len(sells)}只)")
        print(f"  {'代码':<8} {'名称':<12} {'现价':>7} {'成本':>7} {'盈亏':>7} {'评分':>6}")
        print(f"  {'-'*50}")
        for r in sells:
            pnl_s = f"{r['pnl']*100:+5.1f}%" if r['pnl'] else '---'
            print(f"  {r['code']:<8} {r['name']:<12} {r['close']:>7.3f} "
                  f"{r['entry_price']:>7.3f} {pnl_s:>7} {r['score']:+6.0f}")
            print(f"    → {r['reason']}")

    # 持仓中
    if holds:
        print(f"\n  💤 持仓观望 ({len(holds)}只)")
        print(f"  {'代码':<8} {'名称':<12} {'现价':>7} {'成本':>7} {'盈亏':>7} {'评分':>6} {'布林':>5}")
        print(f"  {'-'*55}")
        for r in holds:
            pnl_s = f"{r['pnl']*100:+5.1f}%" if r['pnl'] else '---'
            print(f"  {r['code']:<8} {r['name']:<12} {r['close']:>7.3f} "
                  f"{r['entry_price']:>7.3f} {pnl_s:>7} {r['score']:+6.0f} {r['bb_pos']:>4.0%}")

    # 关注
    if watches:
        print(f"\n  👀 关注 ({len(watches)}只)")
        for r in watches[:6]:
            print(f"  {r['code']} {r['name']:<12} 评分{r['score']:+5.0f} "
                  f"布林{r['bb_pos']:.0%} {r['chg_5d']:+5.1f}% → {r['reason']}")

    # 操作建议汇总
    print(f"\n  {'─'*60}")
    print(f"  操作建议：")
    if buys:
        remaining = MAX_HOLD - len(positions) + len(sells)
        n_buy = min(len(buys), max(0, remaining))
        if n_buy > 0:
            # 等权分配
            allocation = 100 / max(1, n_buy + len([p for p in positions if p not in [s['code'] for s in sells]]))
            print(f"  可建仓{n_buy}只，每只约{allocation:.0f}%仓位：")
            for i, r in enumerate(buys[:n_buy]):
                print(f"  {i+1}. {r['code']} {r['name']} @ {r['close']:.3f} → {r['reason']}")
    if sells:
        for r in sells:
            follow = "等布林回落再买" if 'TAKE_PROFIT' in r['action'] else "等评分转正"
            print(f"    卖出 {r['code']} {r['name']} → 后续: {follow}")
    if not buys and not sells:
        print(f"  当前无明确操作。{market['state']}市 — "
              f"{'等回调买入' if market['state'] == 'bull' else '等市场企稳'}")

    print(f"\n  (etf_bollinger.py bought <代码> [价格] / sold <代码> 记录交易)")


def cmd_bought(code, price=None):
    positions = load_positions()
    if code not in POOL:
        print(f"不在池子中: {code}")
        return
    if price is None:
        conn = pymysql.connect(**MYSQL)
        cur = conn.cursor()
        cur.execute("SELECT close FROM quote WHERE code=%s ORDER BY date DESC LIMIT 1", (code,))
        r = cur.fetchone()
        conn.close()
        price = float(r[0]) if r else 0
    positions[code] = {'cost': price, 'date': str(date.today())}
    POSITION_FILE.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ 已买入: {code} {POOL[code]} @ {price:.3f}")
    run()


def cmd_sold(code):
    positions = load_positions()
    if code in positions:
        del positions[code]
        POSITION_FILE.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"✅ 已卖出: {code}")
    else:
        print(f"未持有: {code}")
    run()


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'bought':
        price = float(sys.argv[3]) if len(sys.argv) >= 4 else None
        cmd_bought(sys.argv[2], price)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'sold':
        cmd_sold(sys.argv[2])
    else:
        run()
