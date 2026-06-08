"""
MACD金叉过滤条件对比回测 — 5组策略横向比较
每组独立回测10只ETF各400天数据，输出对比汇总表

策略组:
  组1: 基准（纯MACD金叉: DIF>DEA AND hist>0，首日突破）
  组2: +MA趋势过滤（MA20 > MA60，趋势向上才买）
  组3: +量比过滤（5日均量/20日均量 > 0.8，放量确认）
  组4: +RSI过滤（RSI(14) < 60，不追高）
  组5: +DIF>0过滤（零轴上金叉，DIF值>0才买）

所有组统一: 持有30天 或 -8%止损卖出, 初始资金10万/ETF, 新浪API日线数据
"""
import json
import sys
import urllib.request
import numpy as np

sys.path.insert(0, r'E:\project\master\etf_trader_v2')
from engine.indicators import macd, rsi, ma

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
MIN_DATA = 65  # MA60 需要至少 60 根K线，加一些余量


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


# ── 辅助指标 ──────────────────────────────────────────
def calc_vol_ratio_5_20(volumes: np.ndarray) -> float:
    """5日均量 / 20日均量"""
    if len(volumes) < 20:
        return 1.0
    ma5 = float(np.mean(volumes[-5:]))
    ma20 = float(np.mean(volumes[-20:]))
    if ma20 == 0:
        return 1.0
    return float(ma5 / ma20)


# ── 买入条件函数（返回 bool） ─────────────────────────
def buy_condition_group1(dif, dea, hist, closes, volumes):
    """组1: 基准 — 纯MACD金叉"""
    return (dif > dea) and (hist > 0)


def buy_condition_group2(dif, dea, hist, closes, volumes):
    """组2: MACD金叉 + MA20 > MA60（趋势向上）"""
    if not ((dif > dea) and (hist > 0)):
        return False
    if len(closes) < 60:
        return False
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60)
    return ma20 > ma60


def buy_condition_group3(dif, dea, hist, closes, volumes):
    """组3: MACD金叉 + 量比>0.8（5日均量/20日均量 > 0.8）"""
    if not ((dif > dea) and (hist > 0)):
        return False
    vr = calc_vol_ratio_5_20(volumes)
    return vr > 0.8


def buy_condition_group4(dif, dea, hist, closes, volumes):
    """组4: MACD金叉 + RSI(14) < 60（不追高）"""
    if not ((dif > dea) and (hist > 0)):
        return False
    rsi_val = rsi(closes, 14)
    return rsi_val < 60.0


def buy_condition_group5(dif, dea, hist, closes, volumes):
    """组5: MACD金叉 + DIF > 0（零轴上金叉）"""
    if not ((dif > dea) and (hist > 0)):
        return False
    return dif > 0.0


# 策略组定义
STRATEGY_GROUPS = [
    ("组1 基准",       "纯MACD金叉",           buy_condition_group1),
    ("组2 +MA趋势",    "MA20>MA60趋势过滤",    buy_condition_group2),
    ("组3 +量比",      "5日/20日均量>0.8",     buy_condition_group3),
    ("组4 +RSI",       "RSI(14)<60不追高",     buy_condition_group4),
    ("组5 +DIF>0",     "零轴上金叉DIF>0",      buy_condition_group5),
]


# ── 回测引擎 ──────────────────────────────────────────
def run_backtest(code: str, name: str, quotes: list[dict],
                 buy_condition_fn, group_label: str) -> dict:
    """对单只ETF运行回测，使用指定的买入条件函数"""
    if len(quotes) < MIN_DATA:
        return {
            "code": code, "name": name, "group": group_label,
            "trades": [], "metrics": empty_metrics(),
        }

    quotes_sorted = sorted(quotes, key=lambda x: x["date"])
    closes = np.array([r["close"] for r in quotes_sorted], dtype=np.float64)
    volumes = np.array([r["volume"] for r in quotes_sorted], dtype=np.float64)
    dates = [r["date"] for r in quotes_sorted]

    trades = []
    held = False
    entry_price = 0.0
    entry_idx = 0

    for i in range(MIN_DATA, len(dates)):
        current_date = dates[i]
        current_close = float(closes[i])

        # 当前切片（包含当日）
        closes_slice = closes[: i + 1]
        volumes_slice = volumes[: i + 1]

        dif, dea, hist = macd(closes_slice)

        # 用策略组的买入条件判断
        is_buy_signal = buy_condition_fn(dif, dea, hist, closes_slice, volumes_slice)

        if not held:
            if is_buy_signal:
                # 上一日是否也满足买入条件（只取首个突破日）
                prev_closes = closes[:i]
                prev_volumes = volumes[:i]
                prev_dif, prev_dea, prev_hist = macd(prev_closes)
                was_buy_signal = buy_condition_fn(
                    prev_dif, prev_dea, prev_hist, prev_closes, prev_volumes
                )
                if not was_buy_signal:
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
        trades.append({
            "date": dates[-1], "action": "SELL",
            "code": code, "name": name,
            "price": final_close, "pnl": round(pnl, 2),
            "reason": "回测结束平仓",
            "days_held": len(dates) - 1 - entry_idx,
            "pnl_pct": round(pnl_pct * 100, 2),
        })

    return {
        "code": code, "name": name, "group": group_label,
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


# ── 输出 ──────────────────────────────────────────────
def print_group_table(group_label: str, description: str,
                      results: list[dict]):
    """打印单个策略组的汇总表"""
    print(f"\n{'='*82}")
    print(f"  {group_label}: {description}")
    print(f"{'='*82}")
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
        n_etf = len(results)
        overall_ret = sum_pnl / (INITIAL_CAPITAL * n_etf) * 100 if n_etf > 0 else 0.0
        print(f"{'合计':<8} {'':10} {total_sells:>5} {total_wins:>4} "
              f"{total_sells-total_wins:>4} {overall_wr:>7.1f}% "
              f"{overall_avg:>9,.0f} {overall_ret:>9.2f}%")
    else:
        print(f"{'合计':<8} {'':10} {'0':>5} {'0':>4} {'0':>4} "
              f"{'0.0':>7}% {'0':>9} {'0.00':>9}%")
    print("=" * 82)


def print_comparison_summary(all_group_results: list[tuple]):
    """打印5组横向对比汇总表"""
    print("\n\n" + "█" * 82)
    print("█" + "  MACD金叉过滤条件 — 5组横向对比汇总".center(78) + "█")
    print("█" * 82)

    # ── 表头 ──
    header = (f"{'策略组':<16} {'交易':>5} {'胜':>4} {'负':>4} "
              f"{'胜率':>8} {'均盈亏':>10} {'总收益':>10}")
    print(header)
    print("-" * 82)

    # ── 每组合计行 ──
    for group_label, description, results in all_group_results:
        total_sells = sum(r["metrics"]["total_trades"] for r in results)
        total_wins = sum(r["metrics"]["wins"] for r in results)
        sum_pnl = sum(r["metrics"]["total_pnl"] for r in results)
        n_etf = len(results)

        if total_sells > 0:
            wr = total_wins / total_sells * 100
            avg = sum_pnl / total_sells
            ret = sum_pnl / (INITIAL_CAPITAL * n_etf) * 100
        else:
            wr = 0.0
            avg = 0.0
            ret = 0.0

        print(f"{group_label:<16} {total_sells:>5} {total_wins:>4} "
              f"{total_sells-total_wins:>4} {wr:>7.1f}% "
              f"{avg:>9,.0f} {ret:>9.2f}%")
    print("-" * 82)
    print("█" * 82)

    # ── 逐只ETF对比表 ──
    print(f"\n{'─'*82}")
    print("  各ETF在不同策略下的总收益(%)对比")
    print(f"{'─'*82}")

    # 收集所有ETF代码（按顺序）
    etf_codes = [r["code"] for r in all_group_results[0][2]]
    etf_names = [r["name"] for r in all_group_results[0][2]]

    # 表头
    col_width = 12
    header2 = f"{'代码':<8} {'名称':<10}"
    for gl, _, _ in all_group_results:
        header2 += f" {gl:>{col_width}}"
    print(header2)
    print("-" * (18 + col_width * len(all_group_results)))

    for idx, code in enumerate(etf_codes):
        row = f"{code:<8} {etf_names[idx]:<10}"
        for _, _, results in all_group_results:
            ret = results[idx]["metrics"]["total_return"]
            row += f" {ret:>{col_width-1}.2f}%"
        print(row)

    # 合计行
    print("-" * (18 + col_width * len(all_group_results)))
    row = f"{'合计':<8} {'':10}"
    for _, _, results in all_group_results:
        total_ret = sum(r["metrics"]["total_return"] for r in results)
        row += f" {total_ret:>{col_width-1}.2f}%"
    print(row)
    print("─" * 82)

    # ── 明细 ──
    print("\n\n── 各策略组交易明细 ──")
    for group_label, description, results in all_group_results:
        print(f"\n  【{group_label}: {description}】")
        has_trades = False
        for r in results:
            sells = [t for t in r["trades"] if t["action"] == "SELL"]
            if not sells:
                continue
            has_trades = True
            print(f"    {r['code']} {r['name']} ({len(sells)}笔):")
            for t in sells:
                print(f"      {t['date']}  {t['reason']:<14}  "
                      f"盈亏{t['pnl_pct']:>+6.2f}%  ¥{t['pnl']:>+9,.0f}")
        if not has_trades:
            print("    (无交易)")


# ── 主流程 ────────────────────────────────────────────
def main():
    print("█" * 82)
    print("█" + "  MACD金叉过滤条件对比回测 — 5组 × 10只ETF".center(78) + "█")
    print("█" + "  持有最多30天 / -8%止损 / 初始资金10万/ETF".center(78) + "█")
    print("█" * 82)

    # ── 第一步：一次性获取所有ETF数据 ──
    print("\n[1/2] 获取数据...")
    all_quotes = {}  # code -> (name, quotes)
    for code, name, symbol in ETF_LIST:
        print(f"  {code} {name} ...", end=" ", flush=True)
        try:
            quotes = fetch_quotes(symbol)
            print(f"{len(quotes)}条日线")
            all_quotes[code] = (name, quotes)
        except Exception as e:
            print(f"失败: {e}")

    if not all_quotes:
        print("未获取到任何数据，退出。")
        return

    # ── 第二步：逐组回测 ──
    all_group_results = []

    for group_idx, (group_label, description, buy_fn) in enumerate(STRATEGY_GROUPS, 1):
        n_groups = len(STRATEGY_GROUPS)
        print(f"\n[组 {group_idx}/{n_groups}] {group_label}: {description}")
        group_results = []
        for code, (name, quotes) in all_quotes.items():
            result = run_backtest(code, name, quotes, buy_fn, group_label)
            group_results.append(result)
            m = result["metrics"]
            print(f"    {code} {name:<10} 交易{m['total_trades']:>3}次  "
                  f"胜率{m['win_rate']:>5.1f}%  总收益{m['total_return']:>7.2f}%")

        all_group_results.append((group_label, description, group_results))

        # 打印该组汇总表
        print_group_table(group_label, description, group_results)

    # ── 第三步：横向对比汇总 ──
    print_comparison_summary(all_group_results)

    print("\n回测完成。")


if __name__ == "__main__":
    main()
