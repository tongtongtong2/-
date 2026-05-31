"""ETF每日轮动 — 每天买1只，总持4只，自动轮换。
用法:
  uv run python portfolio.py daily     # 今天该买哪只？买入价？
  uv run python portfolio.py bought 513100 2.85  # 记录买入（代码 价格）
  uv run python portfolio.py check    # 查看持仓+该卖哪只
  uv run python portfolio.py sell 513100  # 记录卖出
"""
import json, sys
from datetime import date
from pathlib import Path
import pymysql

PORTFOLIO_FILE = Path(__file__).parent / "my_holdings.json"
TOP_HOLD = 4       # 最多持4只
SELL_RANK = 12     # 排名跌出前12名建议卖出

MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root",
              "database": "etf_trader", "charset": "utf8mb4"}


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8'))
    return {"holdings": [], "history": []}

def save_portfolio(p: dict):
    PORTFOLIO_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')

def get_rankings() -> tuple[list[dict], str]:
    """获取最新排名"""
    conn = pymysql.connect(**MYSQL_CFG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT MAX(date) as d FROM signals")
            latest = str(cur.fetchone()['d'])
            cur.execute("""
                SELECT s.code, s.signal,
                       CAST(JSON_EXTRACT(s.signal_meta, '$.score') AS DOUBLE) AS score,
                       CAST(JSON_EXTRACT(s.signal_meta, '$.s_trend') AS DOUBLE) AS s_trend,
                       CAST(JSON_EXTRACT(s.signal_meta, '$.s_macd') AS DOUBLE) AS s_macd,
                       CAST(JSON_EXTRACT(s.signal_meta, '$.s_rsi') AS DOUBLE) AS s_rsi
                FROM signals s WHERE s.date = %s AND s.score IS NOT NULL
                ORDER BY score DESC
            """, (latest,))
            return cur.fetchall(), latest
    finally:
        conn.close()

def get_last_price(code: str) -> float | None:
    """获取最新收盘价"""
    conn = pymysql.connect(**MYSQL_CFG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT close FROM quote WHERE code=%s ORDER BY date DESC LIMIT 1", (code,))
            r = cur.fetchone()
            return float(r[0]) if r else None
    finally:
        conn.close()

def get_etf_name(code: str) -> str:
    try:
        import yaml
        with open("settings.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        for e in config.get('etf_list', []):
            if e['symbol'] == code:
                return e.get('name', code)
    except:
        pass
    return code

def get_open_estimate(code: str) -> str:
    """估算明日开盘价（用收盘价±1%估算）"""
    p = get_last_price(code)
    if p:
        low = round(p * 0.99, 3)
        high = round(p * 1.01, 3)
        return f"≈{p} (挂单价建议{low}~{high})"
    return "无数据"


def cmd_daily():
    """每日推荐：今天该买哪只"""
    rankings, latest = get_rankings()
    p = load_portfolio()
    held = {h['code'] for h in p['holdings']}

    print(f"\n{'='*65}")
    print(f"  每日推荐 — {latest}  共{len(rankings)}只")
    print(f"{'='*65}")

    # 检查是否有该卖的
    sells = []
    for h in p['holdings']:
        rank = next((i+1 for i,r in enumerate(rankings) if r['code']==h['code']), 999)
        sig = next((r['signal'] for r in rankings if r['code']==h['code']), '?')
        if rank > SELL_RANK or sig == 'SELL':
            sells.append(h)

    if sells:
        print(f"\n  ⚠️  建议卖出 ({len(sells)}只):")
        for h in sells:
            rank = next((i+1 for i,r in enumerate(rankings) if r['code']==h['code']), '?')
            name = get_etf_name(h['code'])
            print(f"    🔴 {h['code']} {name}  排名:#{rank}  买入价:{h.get('price','?')}  买入日:{h.get('date','?')}")

    # 还能买吗？
    available_slots = TOP_HOLD - len(p['holdings']) + len(sells)
    if available_slots <= 0:
        print(f"\n  已满仓{TOP_HOLD}只，无卖出 → 不操作")
        return

    # 推荐买入：最高分未持有的
    print(f"\n  🟢 可买{available_slots}只，推荐:")
    count = 0
    for i, r in enumerate(rankings):
        if r['code'] in held and r['code'] not in {s['code'] for s in sells}:
            continue
        rank = i + 1
        name = get_etf_name(r['code'])
        buy_price = get_open_estimate(r['code'])
        score = r['score']
        signal = r['signal']
        sig_icon = "🟢" if signal == 'BUY' else "🟡"

        print(f"  {sig_icon} #{rank} {r['code']} {name[:12]:12s}  评分:{score:+6.1f}")
        print(f"     明日挂单价: {buy_price}")
        count += 1
        if count >= available_slots:
            break

    if sells:
        print(f"\n  操作: 先卖 {', '.join(s['code'] for s in sells)}，再买上面的")


def cmd_bought(code: str, price: float):
    """记录买入"""
    p = load_portfolio()
    today = str(date.today())
    rank = next((i+1 for i,r in enumerate(get_rankings()[0]) if r['code']==code), '?')

    p['holdings'].append({
        'code': code, 'date': today, 'price': price, 'rank': rank
    })
    p['history'].append({'date': today, 'action': 'BUY', 'code': code, 'price': price})

    # 如果超过4只，提示卖出最差的
    if len(p['holdings']) > TOP_HOLD:
        min_rank = 0
        min_code = None
        for h in p['holdings']:
            r = next((i+1 for i,r in enumerate(get_rankings()[0]) if r['code']==h['code']), 999)
            if r > min_rank:
                min_rank = r
                min_code = h['code']
        print(f"  ⚠️ 持仓已达{len(p['holdings'])}只，建议卖出排名最低的: {min_code} (排名#{min_rank})")

    save_portfolio(p)
    print(f"✅ 已记录: {code} @ {price}  排名#{rank}")


def cmd_sell(code: str):
    """记录卖出"""
    p = load_portfolio()
    today = str(date.today())
    sold = None
    for h in p['holdings']:
        if h['code'] == code:
            sold = h
            break
    if sold:
        p['holdings'].remove(sold)
        p['history'].append({'date': today, 'action': 'SELL', 'code': code,
                             'buy_price': sold.get('price'), 'buy_date': sold.get('date')})
        save_portfolio(p)
        print(f"✅ 已卖出: {code}  买入价:{sold.get('price')}  买入日:{sold.get('date')}")
    else:
        print(f"❌ 持仓中没有 {code}")


def cmd_check():
    """查看持仓状态"""
    rankings, latest = get_rankings()
    p = load_portfolio()

    print(f"\n{'='*65}")
    print(f"  持仓检查 — {latest}")
    print(f"{'='*65}")

    if not p['holdings']:
        print("  空仓。运行 'daily' 看今天该买什么。")
        return

    for h in p['holdings']:
        code = h['code']
        rank = next((i+1 for i,r in enumerate(rankings) if r['code']==code), 999)
        score = next((r['score'] for r in rankings if r['code']==code), 0)
        signal = next((r['signal'] for r in rankings if r['code']==code), '?')
        name = get_etf_name(code)
        last_px = get_last_price(code)
        pnl = ""
        if last_px and h.get('price'):
            pct = (last_px / h['price'] - 1) * 100
            pnl = f"浮{'盈' if pct>=0 else '亏'}{pct:+.1f}%"

        status = "✅" if rank <= TOP_HOLD else "⚠️" if rank <= SELL_RANK else "🔴"
        print(f"  {status} {code} {name[:12]:12s}  排名:#{rank}  评分:{score:+6.1f}  {pnl}  "
              f"买入@{h.get('price','?')} {h.get('date','?')}")

    # 下一个该买的
    held = {h['code'] for h in p['holdings']}
    if len(held) < TOP_HOLD:
        for r in rankings:
            if r['code'] not in held:
                name = get_etf_name(r['code'])
                print(f"\n  🟢 还差{TOP_HOLD-len(held)}只，下次买: {r['code']} {name}  "
                      f"挂单价:{get_open_estimate(r['code'])}")
                break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  uv run python portfolio.py daily          # 今天该买什么")
        print("  uv run python portfolio.py bought <代码> <价格>  # 记录买入")
        print("  uv run python portfolio.py sell <代码>         # 记录卖出")
        print("  uv run python portfolio.py check              # 查看持仓")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'daily':
        cmd_daily()
    elif cmd == 'bought':
        if len(sys.argv) < 4:
            print("用法: uv run python portfolio.py bought 513100 2.85")
            sys.exit(1)
        cmd_bought(sys.argv[2], float(sys.argv[3]))
    elif cmd == 'sell':
        if len(sys.argv) < 3:
            print("用法: uv run python portfolio.py sell 513100")
            sys.exit(1)
        cmd_sell(sys.argv[2])
    elif cmd == 'check':
        cmd_check()
    else:
        print(f"未知命令: {cmd}")
