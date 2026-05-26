"""每日选股推荐 + 买卖建议。

输出：
  1. 今日推荐（明天买什么、什么价买、止盈止损价）
  2. 持仓跟踪（已买的票现在怎样、该不该卖）

用法：
  python daily_advice.py              # 完整推荐 + 持仓跟踪
  python daily_advice.py --pick-only  # 只看推荐
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests

# ---- 参数（回测验证最优）----
TAKE_PROFIT = 0.10
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 20
MAX_OPEN_GAP = 0.05  # 高开超5%不追
TOP_N = 5  # 每天推荐5只（精选）

PORTFOLIO_FILE = Path(__file__).parent / "my_portfolio.json"


# ---- 数据获取（腾讯+新浪）----
def create_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s


def fetch_tencent_spot(codes_with_prefix: list[str], session: requests.Session) -> list[dict]:
    results = []
    batch_size = 50
    for i in range(0, len(codes_with_prefix), batch_size):
        batch = codes_with_prefix[i:i + batch_size]
        query = ",".join(batch)
        try:
            r = session.get(f"http://qt.gtimg.cn/q={query}", timeout=10)
            if r.status_code != 200:
                continue
        except Exception:
            continue
        for line in r.text.strip().split("\n"):
            if "=" not in line or "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 45:
                continue
            try:
                results.append({
                    "stock_code": parts[2],
                    "stock_name": parts[1],
                    "current_price": float(parts[3]) if parts[3] else 0,
                    "prev_close": float(parts[4]) if parts[4] else 0,
                    "open": float(parts[5]) if parts[5] else 0,
                    "change_percent": float(parts[32]) if parts[32] else 0,
                    "turnover": float(parts[37]) * 10000 if parts[37] else 0,
                    "volume": float(parts[36]) * 100 if parts[36] else 0,
                    "float_market_cap": float(parts[44]) * 1e8 if len(parts) > 44 and parts[44] else 0,
                })
            except (ValueError, IndexError):
                continue
    return results


def fetch_sina_daily(code: str, session: requests.Session, days: int = 120) -> pd.DataFrame:
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{symbol}_{days}/CN_MarketDataService.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(days)}
    try:
        r = session.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()
    text = r.text
    start = text.find("([")
    end = text.rfind("])")
    if start < 0 or end < 0:
        return pd.DataFrame()
    try:
        data = json.loads(text[start + 1:end + 1])
    except (json.JSONDecodeError, ValueError):
        return pd.DataFrame()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df.rename(columns={"day": "trade_date"}, inplace=True)
    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df


# ---- 选股逻辑（同 backtest/engine.py）----
MIN_DAILY_BARS = 70
MAX_RET_5 = 0.15
MAX_RET_20 = 0.40
MAX_VOL_STD = 0.04


def compute_indicators(daily: pd.DataFrame):
    if daily is None or daily.empty or "close" not in daily.columns:
        return None
    df = daily.sort_values("trade_date").reset_index(drop=True)
    if len(df) < MIN_DAILY_BARS:
        return None
    closes = df["close"].astype(float).values
    vols = df["volume"].astype(float).values if "volume" in df.columns else None
    if vols is None or len(vols) < MIN_DAILY_BARS:
        return None
    last = float(closes[-1])
    ma5 = float(np.mean(closes[-5:]))
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))
    ret_5 = last / closes[-6] - 1 if len(closes) >= 6 else 0.0
    ret_20 = last / closes[-21] - 1 if len(closes) >= 21 else 0.0
    ret_60 = last / closes[-61] - 1 if len(closes) >= 61 else 0.0
    daily_ret_20 = np.diff(closes[-21:]) / closes[-21:-1]
    vol_std = float(np.std(daily_ret_20))
    peak = np.maximum.accumulate(closes[-20:])
    drawdown = (closes[-20:] / peak) - 1
    max_dd = float(np.min(drawdown))
    avg5 = float(np.mean(vols[-5:]))
    avg20 = float(np.mean(vols[-20:]))
    vol_ratio = avg5 / avg20 if avg20 > 0 else 0.0
    avg_turnover20 = avg20 * np.mean(closes[-20:])
    high60 = float(np.max(closes[-60:]))
    dist_high60 = (high60 - last) / high60 if high60 > 0 else 0.0
    return {
        "last": last, "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ret_5": float(ret_5), "ret_20": float(ret_20), "ret_60": float(ret_60),
        "vol_std": vol_std, "max_dd": max_dd,
        "vol_ratio_5_20": vol_ratio, "avg_turnover_20": avg_turnover20,
        "dist_high60": dist_high60,
    }


def passes_hard_filter(ind):
    if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]):
        return False
    if ind["last"] <= ind["ma60"]:
        return False
    if ind["ret_5"] >= MAX_RET_5:
        return False
    if ind["ret_20"] >= MAX_RET_20:
        return False
    if ind["vol_std"] >= MAX_VOL_STD:
        return False
    return True


def score_dataframe(factors: pd.DataFrame) -> pd.DataFrame:
    df = factors.copy()
    def zrank(s): return s.rank(method="average", pct=True) * 100
    def bell(value, low, high):
        half = (high - low) / 2
        center = (low + high) / 2
        dist = (value - center).abs()
        over = (dist - half).clip(lower=0)
        return (100 * (1 - over / half)).clip(lower=0, upper=100)

    df["total_score"] = (
        zrank(df["ret_60"]) * 0.18 +
        zrank((df["last"] / df["ma20"]) - 1) * 0.12 +
        zrank(-df["vol_std"]) * 0.15 +
        zrank(df["max_dd"]) * 0.10 +
        bell(df["vol_ratio_5_20"], 1.0, 2.0) * 0.20 +
        bell(df["dist_high60"], 0.05, 0.15) * 0.15 +
        zrank(df["avg_turnover_20"]) * 0.10
    )
    return df


# ---- 持仓管理 ----
def load_portfolio() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return []


def save_portfolio(positions: list[dict]):
    PORTFOLIO_FILE.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 主流程 ----
def get_all_a_codes() -> list[str]:
    codes = []
    for i in range(600000, 606000):
        codes.append(f"sh{i:06d}")
    for i in range(1, 4000):
        codes.append(f"sz{i:06d}")
    for i in range(300000, 302000):
        codes.append(f"sz{i:06d}")
    return codes


def run_selection(session: requests.Session) -> list[dict]:
    """执行选股，返回推荐列表。"""
    print("  拉取实时行情...")
    all_codes = get_all_a_codes()
    spot_data = fetch_tencent_spot(all_codes, session)
    if not spot_data:
        print("  行情为空（可能非交易时段）")
        return []

    df = pd.DataFrame(spot_data)
    # 初筛
    df = df[~df["stock_name"].str.contains("ST|退", case=False, na=False)]
    df = df[df["current_price"] > 0]
    df = df[df["turnover"] >= 1e8]
    df = df[df["float_market_cap"] >= 5e9]
    # 去涨停
    is_growth = df["stock_code"].str.startswith("30")
    limit = np.where(is_growth, 19.5, 9.5)
    df = df[df["change_percent"] < limit]
    # 今日涨幅 > 7% 不推荐（避免追高）
    df = df[df["change_percent"] <= 7.0]

    df = df.sort_values("turnover", ascending=False).head(200).reset_index(drop=True)
    print(f"  初筛后 {len(df)} 只，开始技术分析...")

    candidates = df.to_dict("records")
    rows = []

    def process(rec):
        code = rec["stock_code"]
        daily = fetch_sina_daily(code, session, days=120)
        return code, rec, daily

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(process, r) for r in candidates]
        for fut in as_completed(futures):
            code, rec, daily = fut.result()
            ind = compute_indicators(daily)
            if ind is None:
                continue
            if not passes_hard_filter(ind):
                continue
            # 额外过滤：距高点 < 3% 不推荐（高位接盘）
            if ind["dist_high60"] < 0.03:
                continue
            rows.append({
                "stock_code": code,
                "stock_name": rec["stock_name"],
                "current_price": rec["current_price"],
                "change_percent": rec["change_percent"],
                "float_market_cap": rec["float_market_cap"],
                **ind,
            })

    if not rows:
        return []

    factors = pd.DataFrame(rows)
    scored = score_dataframe(factors)
    scored = scored.sort_values("total_score", ascending=False)
    return scored.head(TOP_N).to_dict("records")


def print_recommendations(picks: list[dict]):
    today = date.today().isoformat()
    print(f"\n{'=' * 60}")
    print(f"  明日买入建议  (基于 {today} 收盘数据)")
    print(f"{'=' * 60}\n")

    if not picks:
        print("  今日无推荐（市场条件不满足或非交易日）")
        return

    for i, p in enumerate(picks, 1):
        code = p["stock_code"]
        name = p["stock_name"]
        price = p["current_price"]
        score = p["total_score"]
        max_buy = price * (1 + MAX_OPEN_GAP)
        tp = price * (1 + TAKE_PROFIT)
        sl = price * (1 + STOP_LOSS)

        print(f"  {i}. [{code}] {name}")
        print(f"     今日收盘: {price:.2f}  综合分: {score:.1f}")
        print(f"     买入条件: 明日开盘价 <= {max_buy:.2f} 时买入（高开超5%放弃）")
        print(f"     止盈价:   {tp:.2f} (+{TAKE_PROFIT*100:.0f}%)")
        print(f"     止损价:   {sl:.2f} ({STOP_LOSS*100:.0f}%)")
        print(f"     最晚持有: {MAX_HOLD_DAYS} 个交易日")
        print()


def check_portfolio(session: requests.Session):
    """检查持仓状态。"""
    positions = load_portfolio()
    if not positions:
        print("\n  当前无持仓。")
        return

    # 拉持仓票的实时价格
    codes_prefix = []
    for pos in positions:
        code = pos["code"]
        prefix = "sh" + code if code.startswith("6") else "sz" + code
        codes_prefix.append(prefix)

    spot_data = fetch_tencent_spot(codes_prefix, session)
    price_map = {s["stock_code"]: s for s in spot_data}

    print(f"\n{'=' * 60}")
    print(f"  持仓跟踪  ({date.today().isoformat()} 收盘)")
    print(f"{'=' * 60}\n")

    updated_positions = []
    for pos in positions:
        code = pos["code"]
        entry_price = pos["entry_price"]
        entry_date = pos["entry_date"]
        hold_days = pos.get("hold_days", 0) + 1

        spot = price_map.get(code)
        if not spot:
            print(f"  [{code}] {pos.get('name','')} — 无法获取价格")
            updated_positions.append(pos)
            continue

        current = spot["current_price"]
        ret = (current / entry_price - 1) * 100
        tp_price = entry_price * (1 + TAKE_PROFIT)
        sl_price = entry_price * (1 + STOP_LOSS)

        # 判断信号
        if ret >= TAKE_PROFIT * 100:
            signal = "卖出（止盈）"
        elif ret <= STOP_LOSS * 100:
            signal = "卖出（止损）"
        elif hold_days >= MAX_HOLD_DAYS:
            signal = "卖出（到期）"
        else:
            signal = "继续持有"

        print(f"  [{code}] {pos.get('name','')}  买入价 {entry_price:.2f}  现价 {current:.2f}  收益 {ret:+.1f}%  持有 {hold_days}天")
        if "卖出" in signal:
            print(f"     >>> {signal}，明日开盘卖出 <<<")
        else:
            print(f"     {signal} | 止盈 {tp_price:.2f} | 止损 {sl_price:.2f} | 剩余 {MAX_HOLD_DAYS - hold_days} 天")
        print()

        if "卖出" not in signal:
            pos["hold_days"] = hold_days
            updated_positions.append(pos)

    save_portfolio(updated_positions)
    sold = len(positions) - len(updated_positions)
    if sold > 0:
        print(f"  已标记 {sold} 只待卖出（明日开盘执行）")


def add_to_portfolio(picks: list[dict]):
    """将推荐加入持仓跟踪（用户确认买入后调用）。"""
    positions = load_portfolio()
    existing_codes = {p["code"] for p in positions}
    added = 0
    for p in picks:
        if p["stock_code"] not in existing_codes:
            positions.append({
                "code": p["stock_code"],
                "name": p["stock_name"],
                "entry_price": p["current_price"],
                "entry_date": date.today().isoformat(),
                "hold_days": 0,
            })
            added += 1
    save_portfolio(positions)
    if added:
        print(f"\n  已将 {added} 只加入持仓跟踪。")


def main():
    parser = argparse.ArgumentParser(description="每日选股建议")
    parser.add_argument("--pick-only", action="store_true", help="只看推荐，不检查持仓")
    parser.add_argument("--add", action="store_true", help="将今日推荐加入持仓跟踪")
    args = parser.parse_args()

    session = create_session()

    # 选股推荐
    picks = run_selection(session)
    print_recommendations(picks)

    # 持仓跟踪
    if not args.pick_only:
        check_portfolio(session)

    # 加入持仓
    if args.add and picks:
        add_to_portfolio(picks)


if __name__ == "__main__":
    main()
