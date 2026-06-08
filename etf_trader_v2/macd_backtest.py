"""
纯MACD金叉回测脚本
策略：DIF>DEA AND hist>0 买入，持有30天或-8%止损
每只ETF初始资金10万，独立计算盈亏
"""
import json
import sys
import urllib.request
import numpy as np

sys.path.insert(0, r'E:\project\master\etf_trader_v2')
from engine.indicators import macd

# ── 配置 ──────────────────────────────────────────────
SINA_API = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=400"
)

ETF_LIST = [
    ("510500", "中证500",   "sh510500"),
    ("159996", "家电",      "sz159996"),
    ("515790", "光伏华泰",  "sh515790"),
    ("588000", "科创50",    "sh588000"),
    ("510300", "沪深300",   "sh510300"),
    ("515700", "新能源车",  "sh515700"),
    ("159755", "电池",      "sz159755"),
    ("510050", "上证50",    "sh510050"),
    ("159920", "恒生ETF",   "sz159920"),
    ("159915", "创业板",    "sz159915"),
]

HOLD_DAYS = 30
STOP_LOSS = -0.08
INITIAL_CAPITAL = 100000.0


# ── 数据获取 ──────────────────────────────────────────
def fetch_quotes(symbol: str) -> list[dict]:
    """从新浪API拉取日线数据"""
    url = SINA_API.format(symbol=symbol)
    with urllib.request.urlopen(url, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    quotes = []
    for item in raw:
        try:
            quotes.append({
                "date": item["day"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item["volume"]),
            })
        except (KeyError, ValueError):
            continue
    return quotes


# ── MACD 回测 ─────────────────────────────────────────
def run_macd_backtest(code: str, name: str, quotes: list[dict]) -> dict:
    """对单只ETF运行纯MACD金叉回测"""
    min_data = 35  # MACD 需要至少 26+9

    if len(quotes) < min_data:
        return {
            "code": code, "name": name,
            "trades": [], "metrics": empty_metrics(),
        }

    quotes_sorted = sorted(quotes, key=lambda x: x["date"])
    closes = np.array([r["close"] for r in quotes_sorted], dtype=np.float64)
    dates = [r["date"] for r in quotes_sorted]

    trades = []
    held = False
    entry_price = 0.0
    entry_idx = 0
    total_pnl = 0.0

    for i in range(min_data, len(dates)):
        current_date = dates[i]
        current_close = float(closes[i])

        dif, dea, hist = macd(closes[: i + 1])

        # ── 金叉判断 ──
        is_golden = (dif > dea) and (hist > 0)

        if not held:
            if is_golden:
                # 上一日是否也为金叉（首个金叉日才买入）
                prev_dif, prev_dea, prev_hist = macd(closes[:i])
                was_golden = (prev_dif > prev_dea) and (prev_hist > 0)
                if not was_golden:
                    held = True
                    entry_price = current_close
                    entry_idx = i
                    trades.append({
                        "date": current_date, "action": "BUY",
                        "code": code, "name": name,
                        "price": current_close, "pnl": 0.0,
                    })
        else:
            days_held = i - entry_idx
            pnl_pct = (current_close - entry_price) / entry_price
            end_of_data = (i == len(dates) - 1)

            should_sell = False
            reason = ""

            if pnl_pct <= STOP_LOSS:
                should_sell = True
                reason = f"止损({pnl_pct*100:.1f}%)"
            elif days_held >= HOLD_DAYS:
                should_sell = True
                reason = f"持有期满({days_held}天)"
            elif end_of_data:
                should_sell = True
                reason = "数据结束"

            if should_sell:
                pnl = pnl_pct * INITIAL_CAPITAL
                total_pnl += pnl
                trades.append({
                    "date": current_date, "action": "SELL",
                    "code": code, "name": name,
                    "price": current_close, "pnl": round(pnl, 2),
                    "reason": reason, "days_held": days_held,
                    "pnl_pct": round(pnl_pct * 100, 2),
                })
                held = False
                entry_price = 0.0

    # 强制平仓
    if held and entry_price > 0:
        final_close = float(closes[-1])
        pnl_pct = (final_close - entry_price) / entry_price
        pnl = pnl_pct * INITIAL_CAPITAL
        total_pnl += pnl
        trades.append({
            "date": dates[-1], "action": "SELL",
            "code": code, "name": name,
            "price": final_close, "pnl": round(pnl, 2),
            "reason": "回测结束平仓",
            "days_held": len(dates) - 1 - entry_idx,
            "pnl_pct": round(pnl_pct * 100, 2),
        })

    return {
        "code": code, "name": name,
        "trades": trades,
        "metrics": calc_metrics(trades),
    }


def calc_metrics(trades: list[dict]) -> dict:
    sells = [t for t in trades if t["action"] == "SELL"]
    n = len(sells)
    if n == 0:
        return empty_metrics()

    wins = [t for t in sells if t["pnl"] > 0]
    total_pnl = sum(t["pnl"] for t in sells)

    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": n - len(wins),
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_pnl": round(total_pnl / n, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return": round(total_pnl / INITIAL_CAPITAL * 100, 2),
    }


def empty_metrics() -> dict:
    return {
        "total_trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "avg_pnl": 0.0,
        "total_pnl": 0.0, "total_return": 0.0,
    }


# ── 主流程 ────────────────────────────────────────────
def main():
    print("=" * 82)
    print("  纯MACD金叉回测 — 持有最多30天 / -8%止损 — 初始资金10万/ETF")
    print("=" * 82)

    results = []
    for code, name, symbol in ETF_LIST:
        print(f"\n[ ] 获取 {code} {name} ...", end=" ", flush=True)
        try:
            quotes = fetch_quotes(symbol)
            print(f"{len(quotes)}条日线", end=" ", flush=True)
        except Exception as e:
            print(f" 失败: {e}")
            continue

        result = run_macd_backtest(code, name, quotes)
        results.append(result)
        m = result["metrics"]
        print(f"→ 交易{m['total_trades']}次  胜率{m['win_rate']}%  "
              f"均盈亏{m['avg_pnl']:,.0f}  总收益{m['total_return']}%")

    # ── 汇总表 ──
    print("\n" + "=" * 82)
    header = (f"{'代码':<8} {'名称':<10} {'交易':>5} {'胜':>4} {'负':>4} "
              f"{'胜率':>8} {'均盈亏':>10} {'总收益':>10}")
    print(header)
    print("-" * 82)

    total_sells = 0
    total_wins = 0
    sum_pnl = 0.0

    for r in results:
        m = r["metrics"]
        print(f"{r['code']:<8} {r['name']:<10} {m['total_trades']:>5} "
              f"{m['wins']:>4} {m['losses']:>4} {m['win_rate']:>7.1f}% "
              f"{m['avg_pnl']:>9,.0f} {m['total_return']:>9.2f}%")
        total_sells += m["total_trades"]
        total_wins += m["wins"]
        sum_pnl += m["total_pnl"]

    print("-" * 82)
    if total_sells > 0:
        overall_wr = total_wins / total_sells * 100
        overall_avg = sum_pnl / total_sells
        overall_ret = sum_pnl / (INITIAL_CAPITAL * len(results)) * 100
        print(f"{'合计':<8} {'':10} {total_sells:>5} {total_wins:>4} "
              f"{total_sells-total_wins:>4} {overall_wr:>7.1f}% "
              f"{overall_avg:>9,.0f} {overall_ret:>9.2f}%")
    print("=" * 82)

    # 明细
    print("\n── 各ETF交易明细 ──")
    for r in results:
        sells = [t for t in r["trades"] if t["action"] == "SELL"]
        if not sells:
            print(f"  {r['code']} {r['name']}: 无交易")
            continue
        print(f"\n  {r['code']} {r['name']} ({len(sells)}笔):")
        for t in sells:
            print(f"    {t['date']}  {t['reason']:<14}  "
                  f"盈亏{t['pnl_pct']:>+6.2f}%  ¥{t['pnl']:>+9,.0f}")


if __name__ == "__main__":
    main()
