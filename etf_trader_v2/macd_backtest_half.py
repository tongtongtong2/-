"""
MACD 提前半仓 vs 标准策略 对比回测

策略A (标准): 纯MACD金叉(DIF>DEA+hist>0)首日满仓买入, 持有30天或-8%止损
策略B (提前): 预判条件触发后半仓(3万) → 5天内金叉→加满(6万) / 恶化→止损 / 超时→退出
              满仓后30天到期或-8%止损, 卖出后15天冷却

10只ETF各400天数据, 对比: 交易次数 / 胜率 / 总收益 / 最大回撤
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
INITIAL_CAPITAL = 100000.0       # 标准策略满仓
HALF_CAPITAL = 30000.0           # 提前策略半仓
FULL_CAPITAL = 60000.0           # 提前策略满仓
MIN_DATA = 35                    # MACD需要 26+9
PREJUDGE_WINDOW = 5              # 预判后等待金叉的天数
COOLDOWN_DAYS = 15               # 卖出后冷却天数
DETERIORATION_RATIO = 1.5        # 柱扩大50%视为恶化


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


# ──────────────────────────────────────────────────────
#  策略A: 标准纯MACD金叉 (同 macd_backtest.py)
# ──────────────────────────────────────────────────────
def run_standard_backtest(code: str, name: str, quotes: list[dict]) -> dict:
    """标准MACD金叉策略, 含最大回撤计算"""
    if len(quotes) < MIN_DATA:
        return _empty_result(code, name, "标准")

    quotes_sorted = sorted(quotes, key=lambda x: x["date"])
    closes = np.array([r["close"] for r in quotes_sorted], dtype=np.float64)
    dates = [r["date"] for r in quotes_sorted]

    trades = []
    held = False
    entry_price = 0.0
    entry_idx = 0
    realized_pnl = 0.0

    # 回撤跟踪
    equity_curve = []
    peak_equity = INITIAL_CAPITAL

    for i in range(MIN_DATA, len(dates)):
        current_date = dates[i]
        current_close = float(closes[i])

        dif, dea, hist = macd(closes[: i + 1])
        is_golden = (dif > dea) and (hist > 0)

        # ── 计算当日权益(含未实现盈亏) ──
        unrealized = 0.0
        if held and entry_price > 0:
            unrealized = (current_close - entry_price) / entry_price * INITIAL_CAPITAL
        equity = INITIAL_CAPITAL + realized_pnl + unrealized
        if equity > peak_equity:
            peak_equity = equity
        equity_curve.append(equity)

        if not held:
            if is_golden:
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
                realized_pnl += pnl
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
        realized_pnl += pnl
        trades.append({
            "date": dates[-1], "action": "SELL",
            "code": code, "name": name,
            "price": final_close, "pnl": round(pnl, 2),
            "reason": "回测结束平仓",
            "days_held": len(dates) - 1 - entry_idx,
            "pnl_pct": round(pnl_pct * 100, 2),
        })

    # 计算最大回撤
    max_dd = _calc_max_drawdown(equity_curve, INITIAL_CAPITAL)

    return {
        "code": code, "name": name, "strategy": "标准",
        "trades": trades,
        "metrics": calc_metrics(trades),
        "max_drawdown": max_dd,
    }


# ──────────────────────────────────────────────────────
#  策略B: 提前半仓
# ──────────────────────────────────────────────────────
def run_early_backtest(code: str, name: str, quotes: list[dict]) -> dict:
    """提前半仓策略: 预判→半仓→5天内金叉加满/恶化止损/超时退出"""
    if len(quotes) < MIN_DATA + 1:
        return _empty_result(code, name, "提前")

    quotes_sorted = sorted(quotes, key=lambda x: x["date"])
    closes = np.array([r["close"] for r in quotes_sorted], dtype=np.float64)
    dates = [r["date"] for r in quotes_sorted]
    N = len(dates)

    trades = []

    # 状态: 'idle', 'half', 'full', 'cooldown'
    state = "idle"
    cooldown_remaining = 0

    # 持仓数据
    entry_price_half = 0.0      # 半仓买入价
    entry_price_full = 0.0      # 加仓买入价 (仅full状态有效)
    entry_idx_half = 0          # 半仓买入 bar index
    entry_hist = 0.0            # 半仓买入时的 hist 值 (判断恶化用)
    entry_idx_full = 0          # 满仓 bar index (30天持有计时起点)

    realized_pnl = 0.0

    # 回撤跟踪
    equity_curve = []
    peak_equity = INITIAL_CAPITAL

    for i in range(MIN_DATA, N):
        current_date = dates[i]
        current_close = float(closes[i])

        dif, dea, hist = macd(closes[: i + 1])
        is_golden = (dif > dea) and (hist > 0)

        # ── 计算当日权益 ──
        unrealized = 0.0
        if state == "half" and entry_price_half > 0:
            unrealized = (current_close - entry_price_half) / entry_price_half * HALF_CAPITAL
        elif state == "full" and entry_price_half > 0 and entry_price_full > 0:
            u1 = (current_close - entry_price_half) / entry_price_half * HALF_CAPITAL
            u2 = (current_close - entry_price_full) / entry_price_full * HALF_CAPITAL
            unrealized = u1 + u2
        equity = INITIAL_CAPITAL + realized_pnl + unrealized
        if equity > peak_equity:
            peak_equity = equity
        equity_curve.append(equity)

        # ── 冷却处理 ──
        if state == "cooldown":
            cooldown_remaining -= 1
            if cooldown_remaining <= 0:
                state = "idle"
            continue

        # ── IDLE: 等待预判信号 ──
        if state == "idle":
            # 预判条件: 柱快缩没 + DIF靠近DEA + DIF回升
            prev_dif, prev_dea, _prev_hist = macd(closes[:i])
            pre_judge = (
                hist > -0.02
                and abs(dif - dea) < 0.01
                and dif > prev_dif
            )
            if pre_judge:
                state = "half"
                entry_price_half = current_close
                entry_idx_half = i
                entry_hist = hist
                trades.append({
                    "date": current_date, "action": "BUY_HALF",
                    "code": code, "name": name,
                    "price": current_close, "pnl": 0.0,
                    "amount": HALF_CAPITAL,
                })
            continue

        # ── HALF: 等待金叉 / 恶化 / 超时 ──
        if state == "half":
            bars_waited = i - entry_idx_half
            end_of_data = (i == N - 1)

            # 先检查是否触发金叉 → 加仓到满仓
            if is_golden:
                state = "full"
                entry_price_full = current_close
                entry_idx_full = i
                trades.append({
                    "date": current_date, "action": "BUY_FULL",
                    "code": code, "name": name,
                    "price": current_close, "pnl": 0.0,
                    "amount": HALF_CAPITAL,
                    "note": f"金叉确认, 加至满仓(等待{bars_waited}天)",
                })
                continue

            # 检查恶化: 柱扩大50%以上（更负）
            deteriorated = hist < entry_hist * DETERIORATION_RATIO

            # 检查超时
            timed_out = bars_waited >= PREJUDGE_WINDOW

            should_exit_half = False
            reason = ""

            if deteriorated:
                should_exit_half = True
                reason = f"恶化止损(hist{hist:.4f}<{entry_hist*DETERIORATION_RATIO:.4f})"
            elif timed_out:
                should_exit_half = True
                reason = f"预判超时({bars_waited}天未金叉)"
            elif end_of_data:
                should_exit_half = True
                reason = "数据结束"

            if should_exit_half:
                pnl_pct = (current_close - entry_price_half) / entry_price_half
                pnl = pnl_pct * HALF_CAPITAL
                realized_pnl += pnl
                trades.append({
                    "date": current_date, "action": "SELL_HALF",
                    "code": code, "name": name,
                    "price": current_close, "pnl": round(pnl, 2),
                    "reason": reason, "days_held": bars_waited,
                    "pnl_pct": round(pnl_pct * 100, 2),
                })
                state = "cooldown"
                cooldown_remaining = COOLDOWN_DAYS
                entry_price_half = 0.0
                entry_hist = 0.0
            continue

        # ── FULL: 满仓持有, 30天到期或-8%止损 ──
        if state == "full":
            days_held = i - entry_idx_full
            end_of_data = (i == N - 1)

            # 合并盈亏: 半仓 + 加仓
            pnl_pct_half = (current_close - entry_price_half) / entry_price_half
            pnl_pct_full = (current_close - entry_price_full) / entry_price_full
            combined_pnl_pct = (pnl_pct_half + pnl_pct_full) / 2.0
            combined_pnl = pnl_pct_half * HALF_CAPITAL + pnl_pct_full * HALF_CAPITAL

            should_sell = False
            reason = ""

            if combined_pnl_pct <= STOP_LOSS:
                should_sell = True
                reason = f"止损({combined_pnl_pct*100:.1f}%)"
            elif days_held >= HOLD_DAYS:
                should_sell = True
                reason = f"持有期满({days_held}天)"
            elif end_of_data:
                should_sell = True
                reason = "数据结束"

            if should_sell:
                realized_pnl += combined_pnl
                trades.append({
                    "date": current_date, "action": "SELL_FULL",
                    "code": code, "name": name,
                    "price": current_close, "pnl": round(combined_pnl, 2),
                    "reason": reason, "days_held": days_held,
                    "pnl_pct": round(combined_pnl_pct * 100, 2),
                })
                state = "cooldown"
                cooldown_remaining = COOLDOWN_DAYS
                entry_price_half = 0.0
                entry_price_full = 0.0

    # 强制平仓
    if state == "half" and entry_price_half > 0:
        final_close = float(closes[-1])
        pnl_pct = (final_close - entry_price_half) / entry_price_half
        pnl = pnl_pct * HALF_CAPITAL
        realized_pnl += pnl
        trades.append({
            "date": dates[-1], "action": "SELL_HALF",
            "code": code, "name": name,
            "price": final_close, "pnl": round(pnl, 2),
            "reason": "回测结束平仓(半仓)",
            "days_held": N - 1 - entry_idx_half,
            "pnl_pct": round(pnl_pct * 100, 2),
        })
    elif state == "full" and entry_price_half > 0 and entry_price_full > 0:
        final_close = float(closes[-1])
        pnl_pct_half = (final_close - entry_price_half) / entry_price_half
        pnl_pct_full = (final_close - entry_price_full) / entry_price_full
        combined_pnl = pnl_pct_half * HALF_CAPITAL + pnl_pct_full * HALF_CAPITAL
        combined_pnl_pct = (pnl_pct_half + pnl_pct_full) / 2.0
        realized_pnl += combined_pnl
        trades.append({
            "date": dates[-1], "action": "SELL_FULL",
            "code": code, "name": name,
            "price": final_close, "pnl": round(combined_pnl, 2),
            "reason": "回测结束平仓(满仓)",
            "days_held": N - 1 - entry_idx_full,
            "pnl_pct": round(combined_pnl_pct * 100, 2),
        })

    max_dd = _calc_max_drawdown(equity_curve, INITIAL_CAPITAL)

    return {
        "code": code, "name": name, "strategy": "提前",
        "trades": trades,
        "metrics": calc_metrics(trades),
        "max_drawdown": max_dd,
    }


# ── 指标计算 ──────────────────────────────────────────
def calc_metrics(trades: list[dict]) -> dict:
    sells = [t for t in trades if "SELL" in t["action"]]
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


def _empty_result(code: str, name: str, strategy: str) -> dict:
    return {
        "code": code, "name": name, "strategy": strategy,
        "trades": [], "metrics": empty_metrics(),
        "max_drawdown": 0.0,
    }


def _calc_max_drawdown(equity_curve: list, initial: float) -> float:
    """从权益曲线计算最大回撤百分比"""
    if not equity_curve:
        return 0.0
    peak = initial
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


# ── 输出 ──────────────────────────────────────────────
def print_header():
    print("█" * 95)
    print("█" + "  MACD 提前半仓 vs 标准策略 对比回测 — 10只ETF".center(91) + "█")
    print("█" + "  标准: 金叉满仓10万 / 提前: 预判半仓3万→金叉加满6万".center(91) + "█")
    print("█" * 95)


def print_per_etf_table(std_results: list[dict], early_results: list[dict]):
    """逐只ETF对比表"""
    print(f"\n{'═' * 95}")
    print("  逐只ETF对比: 交易次数 / 胜率 / 总收益 / 最大回撤")
    print(f"{'═' * 95}")

    header = (f"{'代码':<8} {'名称':<10} "
              f"{'策略':<6} {'交易':>5} {'胜':>4} {'负':>4} "
              f"{'胜率':>8} {'总收益':>10} {'最大回撤':>10}")
    print(header)
    print("─" * 95)

    total_std_trades = 0
    total_std_wins = 0
    total_std_pnl = 0.0
    total_early_trades = 0
    total_early_wins = 0
    total_early_pnl = 0.0

    for i, (sr, er) in enumerate(zip(std_results, early_results)):
        sm = sr["metrics"]
        em = er["metrics"]
        sdd = sr.get("max_drawdown", 0.0)
        edd = er.get("max_drawdown", 0.0)

        # 标准行
        print(f"{sr['code']:<8} {sr['name']:<10} "
              f"{'标准':<6} {sm['total_trades']:>5} {sm['wins']:>4} {sm['losses']:>4} "
              f"{sm['win_rate']:>7.1f}% {sm['total_return']:>9.2f}% {sdd:>9.2f}%")
        # 提前行
        print(f"{'':<8} {'':10} "
              f"{'提前':<6} {em['total_trades']:>5} {em['wins']:>4} {em['losses']:>4} "
              f"{em['win_rate']:>7.1f}% {em['total_return']:>9.2f}% {edd:>9.2f}%")
        print("─" * 95)

        total_std_trades += sm["total_trades"]
        total_std_wins += sm["wins"]
        total_std_pnl += sm["total_pnl"]
        total_early_trades += em["total_trades"]
        total_early_wins += em["wins"]
        total_early_pnl += em["total_pnl"]

    # 合计行
    n_etf = len(std_results)
    std_wr = total_std_wins / total_std_trades * 100 if total_std_trades > 0 else 0
    std_ret = total_std_pnl / (INITIAL_CAPITAL * n_etf) * 100
    early_wr = total_early_wins / total_early_trades * 100 if total_early_trades > 0 else 0
    early_ret = total_early_pnl / (INITIAL_CAPITAL * n_etf) * 100

    print(f"{'合计':<8} {'':10} "
          f"{'标准':<6} {total_std_trades:>5} {total_std_wins:>4} {total_std_trades-total_std_wins:>4} "
          f"{std_wr:>7.1f}% {std_ret:>9.2f}% {'—':>10}")
    print(f"{'':<8} {'':10} "
          f"{'提前':<6} {total_early_trades:>5} {total_early_wins:>4} {total_early_trades-total_early_wins:>4} "
          f"{early_wr:>7.1f}% {early_ret:>9.2f}% {'—':>10}")
    print("═" * 95)


def print_trade_details(std_results: list[dict], early_results: list[dict]):
    """打印交易明细"""
    print("\n\n── 标准策略 交易明细 ──")
    for r in std_results:
        sells = [t for t in r["trades"] if "SELL" in t["action"]]
        if not sells:
            print(f"  {r['code']} {r['name']}: 无交易")
            continue
        print(f"\n  {r['code']} {r['name']} ({len(sells)}笔):")
        for t in sells:
            print(f"    {t['date']}  {t['reason']:<18}  "
                  f"盈亏{t['pnl_pct']:>+6.2f}%  ¥{t['pnl']:>+9,.0f}")

    print("\n\n── 提前半仓策略 交易明细 ──")
    for r in early_results:
        sells = [t for t in r["trades"] if "SELL" in t["action"]]
        buys = [t for t in r["trades"] if "BUY" in t["action"]]
        if not sells and not buys:
            print(f"  {r['code']} {r['name']}: 无交易")
            continue
        total_actions = len(sells) + len(buys)
        print(f"\n  {r['code']} {r['name']} ({total_actions}笔操作, {len(sells)}笔平仓):")
        for t in r["trades"]:
            if t["action"] == "BUY_HALF":
                print(f"    {t['date']}  半仓买入            "
                      f"@{t['price']:.3f}  ¥{t['amount']:,.0f}")
            elif t["action"] == "BUY_FULL":
                note = t.get("note", "")
                print(f"    {t['date']}  加仓至满仓          "
                      f"@{t['price']:.3f}  ¥{t['amount']:,.0f}  {note}")
            elif "SELL" in t["action"]:
                print(f"    {t['date']}  {t['reason']:<18}  "
                      f"盈亏{t['pnl_pct']:>+6.2f}%  ¥{t['pnl']:>+9,.0f}")


# ── 主流程 ────────────────────────────────────────────
def main():
    print_header()

    # ── 1. 获取数据 ──
    print("\n[1/3] 获取数据...")
    all_quotes = {}
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

    # ── 2. 运行两种策略 ──
    std_results = []
    early_results = []

    print("\n[2/3] 运行回测...")
    for code, (name, quotes) in all_quotes.items():
        print(f"  {code} {name} ...", end=" ", flush=True)

        sr = run_standard_backtest(code, name, quotes)
        std_results.append(sr)
        sm = sr["metrics"]
        print(f"标准: {sm['total_trades']}次/{sm['win_rate']}%/{sm['total_return']}%", end=" | ", flush=True)

        er = run_early_backtest(code, name, quotes)
        early_results.append(er)
        em = er["metrics"]
        print(f"提前: {em['total_trades']}次/{em['win_rate']}%/{em['total_return']}%")

    # ── 3. 输出 ──
    print("\n[3/3] 结果汇总")
    print_per_etf_table(std_results, early_results)
    print_trade_details(std_results, early_results)

    print("\n\n回测完成。")


if __name__ == "__main__":
    main()
