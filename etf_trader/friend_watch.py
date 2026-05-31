"""你朋友的10只ETF — 每日监控"""
import pymysql, json, sys
from datetime import date
from pathlib import Path

MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root",
              "database": "etf_trader", "charset": "utf8mb4"}

FRIEND_ETFS = {
    '562500': '机器人ETF华夏', '513100': '纳指ETF国泰', '159949': '创业板50ETF华安',
    '515700': '新能源车ETF平安', '159755': '电池ETF广发', '561700': '电力ETF广发',
    '515790': '光伏ETF华泰柏瑞', '515880': '通信ETF华夏', '159996': '家电ETF国泰',
    '516880': '光伏ETF银华'
}

PORTFOLIO_FILE = Path(__file__).parent / "friend_holdings.json"
TOP_N = 5  # 建议持有前5


def get_latest():
    conn = pymysql.connect(**MYSQL_CFG)
    cur = conn.cursor()
    cur.execute("SELECT MAX(`date`) FROM signals")
    d = str(cur.fetchone()[0])
    codes = list(FRIEND_ETFS.keys())
    ph = ','.join(['%s'] * len(codes))
    cur.execute(f"SELECT code, `signal`, CAST(JSON_EXTRACT(signal_meta,'$.score') AS DOUBLE) as sc, CAST(JSON_EXTRACT(signal_meta,'$.s_trend') AS DOUBLE) as st FROM signals WHERE `date`=%s AND code IN ({ph}) ORDER BY sc DESC", [d] + codes)
    rows = cur.fetchall()
    conn.close()
    return d, rows


def cmd_check():
    d, rows = get_latest()
    holds = {}
    if PORTFOLIO_FILE.exists():
        holds = json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8'))

    print(f"\n  {'='*55}")
    print(f"  你朋友的10只ETF — {d}")
    print(f"  {'='*55}")
    print(f"  {'排名':<4} {'':2} {'代码':<8} {'名称':<16} {'评分':>8}  {'信号':>6}  {'操作':>6}")
    print(f"  {'-'*50}")

    for i, (code, sig, sc, st) in enumerate(rows):
        name = FRIEND_ETFS.get(code, code)
        held = code in holds
        h_mark = '📌' if held else '  '
        if sc >= 50:
            icon = '✅'; op = '买入/加仓' if not held else '持有'
        elif sc >= 0:
            icon = '💤'; op = '观望' if not held else '持有'
        elif sc >= -20:
            icon = '⚠️'; op = '减仓' if held else '观望'
        else:
            icon = '🔴'; op = '清仓' if held else '回避'
        print(f"  #{i+1:<3} {h_mark} {icon} {code:<6} {name:<14} {sc:+7.1f}  {sig:>6}  {op:>6}")

    # 统计
    avg = sum(r[2] for r in rows) / len(rows)
    buys = sum(1 for r in rows if r[2] >= 50)
    sells = sum(1 for r in rows if r[2] < 0)
    print(f"\n  平均:{avg:+5.1f} | 建议持有{buys}只 | 建议卖出{sells}只 | 持有TOP-{TOP_N}:")
    for i, (c, _, sc, _) in enumerate(rows[:TOP_N]):
        print(f"    {i+1}. {c} {FRIEND_ETFS.get(c,c)} ({sc:+5.0f})")


def cmd_bought(code: str):
    holds = {}
    if PORTFOLIO_FILE.exists():
        holds = json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8'))
    if code not in FRIEND_ETFS:
        print(f"不在监控列表中: {code}")
        return
    holds[code] = str(date.today())
    PORTFOLIO_FILE.write_text(json.dumps(holds, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ 已记录持有: {code} {FRIEND_ETFS[code]}")
    cmd_check()


def cmd_sold(code: str):
    holds = {}
    if PORTFOLIO_FILE.exists():
        holds = json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8'))
    if code in holds:
        del holds[code]
        PORTFOLIO_FILE.write_text(json.dumps(holds, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"✅ 已卖出: {code}")
    else:
        print(f"未持有: {code}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        cmd_check()
    elif sys.argv[1] == 'bought' and len(sys.argv) > 2:
        cmd_bought(sys.argv[2])
    elif sys.argv[1] == 'sold' and len(sys.argv) > 2:
        cmd_sold(sys.argv[2])
    else:
        cmd_check()
