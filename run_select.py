"""直接用腾讯行情接口选股（绕过东方财富连接问题）。

流程：
1. 从腾讯拉全 A 股实时行情
2. 初筛（去 ST、去涨停、流动性过滤）
3. 从新浪拉日线做技术分析
4. 硬过滤 + 五因子打分
5. 输出 TOP 10
"""
import os
import sys
import time
import math
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import numpy as np
import pandas as pd
import requests

from config import Config

# ============================================================
# 腾讯行情接口
# ============================================================
def fetch_tencent_spot_batch(codes: list[str], session: requests.Session) -> list[dict]:
    """批量拉腾讯实时行情，每次最多 50 只。"""
    results = []
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        query = ",".join(batch)
        try:
            r = session.get(f"http://qt.gtimg.cn/q={query}", timeout=10)
            if r.status_code != 200:
                continue
        except Exception:
            continue
        for line in r.text.strip().split("\n"):
            if "=" not in line or '~' not in line:
                continue
            parts = line.split("~")
            if len(parts) < 45:
                continue
            try:
                results.append({
                    "stock_code": parts[2],
                    "stock_name": parts[1],
                    "current_price": float(parts[3]) if parts[3] else 0,
                    "change_percent": float(parts[32]) if parts[32] else 0,
                    "turnover": float(parts[37]) * 10000 if parts[37] else 0,  # 万元 -> 元
                    "volume": float(parts[36]) * 100 if parts[36] else 0,  # 手 -> 股
                    "high": float(parts[33]) if parts[33] else 0,
                    "low": float(parts[34]) if parts[34] else 0,
                    "total_market_cap": float(parts[45]) * 1e8 if len(parts) > 45 and parts[45] else 0,
                    "float_market_cap": float(parts[44]) * 1e8 if len(parts) > 44 and parts[44] else 0,
                })
            except (ValueError, IndexError):
                continue
    return results


def get_all_a_codes() -> list[str]:
    """生成沪深 A 股代码列表（主板+创业板，不含科创/北交所）。"""
    codes = []
    # 上证主板 600000-605999
    for i in range(600000, 606000):
        codes.append(f"sh{i:06d}")
    # 深证主板 000001-003999
    for i in range(1, 4000):
        codes.append(f"sz{i:06d}")
    # 创业板 300000-301999
    for i in range(300000, 302000):
        codes.append(f"sz{i:06d}")
    return codes


# ============================================================
# 新浪日线接口
# ============================================================
PLACEHOLDER_CONTINUE = "CONTINUE"

def fetch_sina_daily(code: str, session: requests.Session, days: int = 120) -> pd.DataFrame:
    """从新浪拉日线数据。"""
    # 新浪格式: sh600519 或 sz000001
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{symbol}_{days}/CN_MarketDataService.getKLineData"
    params = {
        "symbol": symbol,
        "scale": "240",  # 日线
        "ma": "no",
        "datalen": str(days),
    }
    try:
        r = session.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    text = r.text
    # 解析 JSONP: var _xxx=([{...},...]);
    start = text.find("([")
    end = text.rfind("])")
    if start < 0 or end < 0:
        return pd.DataFrame()
    import json
    try:
        data = json.loads(text[start+1:end+1])
    except json.JSONDecodeError:
        return pd.DataFrame()

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df.rename(columns={"day": "trade_date", "close": "close", "open": "open",
                       "high": "high", "low": "low", "volume": "volume"}, inplace=True)
    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df


# ============================================================
# 技术指标 + 硬过滤 + 打分（复用 stock_selector 的逻辑）
# ============================================================
MIN_DAILY_BARS = 70
MAX_RET_5 = 0.10
MAX_RET_20 = 0.30
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
    ret_10 = last / closes[-11] - 1 if len(closes) >= 11 else 0.0
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
        "last": last,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ret_5": float(ret_5), "ret_10": float(ret_10),
        "ret_20": float(ret_20), "ret_60": float(ret_60),
        "vol_std": vol_std, "max_dd": max_dd,
        "vol_ratio_5_20": vol_ratio,
        "avg_turnover_20": avg_turnover20,
        "dist_high60": dist_high60,
    }


def passes_hard_filter(ind):
    if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]):
        return False, "均线非多头"
    if ind["last"] <= ind["ma60"]:
        return False, "未站上MA60"
    if ind["ret_5"] >= MAX_RET_5:
        return False, "5日过热"
    if ind["ret_20"] >= MAX_RET_20:
        return False, "20日过热"
    if ind["vol_std"] >= MAX_VOL_STD:
        return False, "波动率高"
    if ind["dist_high60"] < 0.03:
        return False, "距高点过近"
    return True, ""


def score_dataframe(factors: pd.DataFrame, history_freq: dict = None) -> pd.DataFrame:
    df = factors.copy()

    def zrank(s):
        return s.rank(method="average", pct=True) * 100

    def bell_score(value, low, high):
        half = (high - low) / 2
        center = (low + high) / 2
        dist = (value - center).abs()
        over = (dist - half).clip(lower=0)
        score = 100 * (1 - over / half)
        return score.clip(lower=0, upper=100)

    df["score_ret60"] = zrank(df["ret_60"])
    df["bias_ma20"] = (df["last"] / df["ma20"]) - 1
    df["score_bias"] = zrank(df["bias_ma20"])
    df["trend_strength"] = df["score_ret60"] * 0.16 + df["score_bias"] * 0.09

    df["score_smooth_std"] = zrank(-df["vol_std"])
    df["score_smooth_dd"] = zrank(df["max_dd"])
    df["trend_smooth"] = df["score_smooth_std"] * 0.18 + df["score_smooth_dd"] * 0.12

    df["score_vol"] = bell_score(df["vol_ratio_5_20"], 1.0, 2.0)
    df["volume_factor"] = df["score_vol"] * 0.15

    df["score_pos"] = bell_score(df["dist_high60"], 0.05, 0.20)
    df["position"] = df["score_pos"] * 0.12

    df["score_liq"] = zrank(df["avg_turnover_20"])
    df["liquidity"] = df["score_liq"] * 0.08

    # 历史连续性因子（10%）：近7天出现次数越多，加分越高
    if history_freq:
        df["history_count"] = df["stock_code"].map(history_freq).fillna(0).astype(int)
        df["history_score"] = (df["history_count"].clip(upper=3) / 3) * 100
    else:
        df["history_score"] = 0
    df["history_factor"] = df["history_score"] * 0.10

    # ── 回撤惩罚：60日最大回撤 > 15% 扣分 ──
    df["dd_penalty"] = df["max_dd"].apply(lambda x: max(0, abs(x) - 0.15) * 200)
    df["dd_penalty"] = df["dd_penalty"].clip(upper=15)

    df["total_score"] = (
        df["trend_strength"] * 0.8929 +
        df["trend_smooth"] * 1.00 +
        df["volume_factor"] * 1.00 +
        df["position"] * 1.00 +
        df["liquidity"] * 0.75 +
        df["history_factor"] * 1.20 -
        df["dd_penalty"]
    )
    return df


# ============================================================
# 历史推荐频次（增强选股连续性，减少单日噪声）
# ============================================================
def get_history_frequency(lookback_days: int = 7):
    """查询近 N 天系统推荐记录，返回 {stock_code: count}。"""
    import pymysql
    from config import Config
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER, password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE, charset='utf8mb4',
            connect_timeout=5,
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT stock_code, COUNT(*) as cnt FROM stock_recommendations "
            "WHERE source='system' AND recommend_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY) "
            "GROUP BY stock_code", (lookback_days,)
        )
        freq = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        print(f"  历史推荐记录加载: {len(freq)} 只票 (近{lookback_days}天)" if freq else "  历史推荐记录为空 (首次运行?)")
        return freq
    except Exception as e:
        print(f"  历史推荐查询失败（将跳过历史因子）: {e}")
        return {}


# ============================================================
# 主流程
# ============================================================
def main():
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print("=" * 60)
    print(f"  A股量化选股  {date.today().isoformat()}  (腾讯行情 + 新浪日线)")
    print("=" * 60)

    # 1) 拉全 A 股实时行情
    print("\n[1/4] 拉取实时行情...")
    all_codes = get_all_a_codes()
    spot_data = fetch_tencent_spot_batch(all_codes, session)
    print(f"  获取到 {len(spot_data)} 只股票行情")

    if not spot_data:
        print("  行情为空，退出（可能非交易时段）")
        sys.exit(1)

    df = pd.DataFrame(spot_data)

    # 2) 初筛
    print("\n[2/4] 初筛...")
    # 去 ST
    df = df[~df["stock_name"].str.contains("ST|退", case=False, na=False)]
    # 价格 > 0
    df = df[df["current_price"] > 0]
    # 成交额 >= 1 亿
    df = df[df["turnover"] >= 1e8]
    # 流通市值 >= 50 亿
    df = df[df["float_market_cap"] >= 5e9]
    # 当日不涨停（主板 9.5%，创业板 19.5%），不跌停
    is_growth = df["stock_code"].str.startswith("30")
    limit_up = np.where(is_growth, 19.5, 9.5)
    limit_down = np.where(is_growth, -19.5, -9.5)
    df = df[(df["change_percent"] < limit_up) & (df["change_percent"] > limit_down)]
    # 日内跌幅 > 5% 排除（暴跌不追）
    df = df[df["change_percent"] > -5.0]

    df = df.sort_values("turnover", ascending=False).head(300).reset_index(drop=True)
    print(f"  初筛后 {len(df)} 只（取成交额前 300）")

    if df.empty:
        print("  初筛后无候选，退出")
        sys.exit(0)

    # 3) 并发拉日线 + 硬过滤
    print(f"\n[3/4] 并发拉日线 + 技术分析（12线程）...")
    candidates = df.to_dict("records")
    rows = []
    rejected = {}

    def _has_recent_limit_up(daily, code, lookback=5):
        if daily is None or daily.empty or "close" not in daily.columns:
            return False
        df = daily.sort_values("trade_date").tail(lookback + 2)
        if len(df) < 3:
            return False
        closes = df["close"].astype(float).values
        for i in range(1, len(closes)):
            if closes[i-1] > 0:
                chg = (closes[i] - closes[i-1]) / closes[i-1]
                limit = 0.195 if (str(code).startswith("30") or str(code).startswith("68")) else 0.095
                if chg >= limit:
                    return True
        return False

    def process_one(rec):
        code = rec["stock_code"]
        daily = fetch_sina_daily(code, session, days=120)
        return code, rec, daily

    done = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(process_one, r) for r in candidates]
        for fut in as_completed(futures):
            done += 1
            code, rec, daily = fut.result()
            ind = compute_indicators(daily)
            if ind is None:
                rejected["数据不足"] = rejected.get("数据不足", 0) + 1
                continue
            ok, reason = passes_hard_filter(ind)
            if not ok:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            if _has_recent_limit_up(daily, code, lookback=5):
                rejected["近5日涨停"] = rejected.get("近5日涨停", 0) + 1
                continue
            rows.append({
                "stock_code": code,
                "stock_name": rec["stock_name"],
                "current_price": rec["current_price"],
                "turnover": rec["turnover"],
                "float_market_cap": rec["float_market_cap"],
                "change_percent": rec["change_percent"],
                **ind,
            })
            if done % 50 == 0:
                print(f"  已处理 {done}/{len(candidates)}...")

    print(f"  硬过滤后剩 {len(rows)} 只")
    print(f"  淘汰原因: {rejected}")

    if not rows:
        print("\n  硬过滤后无候选，今日无推荐。")
        print("  （可能市场整体偏弱，不满足均线多头条件）")
        sys.exit(0)

    # 4) 打分排序（含历史连续性因子）
    print(f"\n[4/4] 五因子+历史连续性打分...")
    history_freq = get_history_frequency(lookback_days=7)
    factors = pd.DataFrame(rows)
    scored = score_dataframe(factors, history_freq)
    scored = scored.sort_values("total_score", ascending=False)
    top = scored.head(Config.TOP_N_STOCKS)

    print(f"\n{'='*60}")
    print(f"  今日推荐 TOP {len(top)}")
    print(f"{'='*60}\n")

    for i, (_, row) in enumerate(top.iterrows(), 1):
        code = row["stock_code"]
        name = row["stock_name"]
        price = row["current_price"]
        total = row["total_score"]
        chg = row["change_percent"]
        r60 = row["ret_60"] * 100
        r5 = row["ret_5"] * 100
        vs = row["vol_std"] * 100
        vr = row["vol_ratio_5_20"]
        dd = row["max_dd"] * 100
        dist = row["dist_high60"] * 100
        mcap = row["float_market_cap"] / 1e8

        hcnt = int(row.get("history_count", 0))
        htag = f"【连续{hcnt}次】" if hcnt >= 2 else (f"【首次推荐】" if hcnt == 1 else "")
        print(f"  {i:2d}. [{code}] {name}  {htag}")
        print(f"      现价 {price:.2f} ({chg:+.2f}%)  流通市值 {mcap:.0f}亿  综合分 {total:.1f}/100")
        print(f"      60日涨 {r60:+.1f}% | 5日涨 {r5:+.1f}% | 波动率 {vs:.2f}% | 量比 {vr:.2f} | 回撤 {dd:.1f}% | 距高点 {dist:.1f}%")
        print()

    print(f"{'='*60}")
    print("  策略: 中长期稳健趋势（持有10-30天）")
    print("  选股逻辑: 均线多头 + 趋势平稳 + 温和放量 + 距高点5-15%")
    print("  止盈 15% / 止损 -5% / 最长持有 30 天")
    print(f"{'='*60}")

    # ── 自动保存到数据库（供历史连续性因子使用）──
    _save_to_database(top)
    return top


def _save_to_database(top: pd.DataFrame, top_n: int = 10):
    """将 TOP N 推荐写入 stock_recommendations 表（先清旧数据再插入）。"""
    import pymysql
    from config import Config
    today = date.today().isoformat()
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER, password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE, charset='utf8mb4',
            connect_timeout=5,
        )
        cursor = conn.cursor()
        # 先清除今日旧推荐
        cursor.execute(
            "DELETE FROM stock_recommendations WHERE recommend_date=%s AND source='system'",
            (today,)
        )
        deleted = cursor.rowcount
        saved = 0
        for _, row in top.head(top_n).iterrows():
            code = row["stock_code"]
            name = row["stock_name"]
            price = float(row["current_price"])
            reason = {
                "total_score": float(row["total_score"]),
                "ret_60": float(row["ret_60"]),
                "ret_5": float(row["ret_5"]),
                "vol_std": float(row.get("vol_std", 0)),
                "vol_ratio_5_20": float(row.get("vol_ratio_5_20", 0)),
                "dist_high60": float(row.get("dist_high60", 0)),
                "trend_strength": float(row.get("trend_strength", 0)),
                "trend_smooth": float(row.get("trend_smooth", 0)),
                "volume_factor": float(row.get("volume_factor", 0)),
                "position": float(row.get("position", 0)),
                "history_count": int(row.get("history_count", 0)),
                "current_price": float(row["current_price"]),
                "change_percent": float(row["change_percent"]) / 100,  # 统一存小数
            }
            import json
            reason_json = json.dumps(reason, ensure_ascii=False)
            # UPSERT: 同票同日同来源则更新
            cursor.execute(
                "INSERT INTO stock_recommendations "
                "(stock_code, stock_name, recommend_date, recommend_price, "
                " price_status, recommend_reason, status, source, is_watched) "
                "VALUES (%s,%s,%s,%s,'filled',%s,'active','system',0) "
                "ON DUPLICATE KEY UPDATE "
                "recommend_price=VALUES(recommend_price), "
                "recommend_reason=VALUES(recommend_reason)",
                (code, name, today, price, reason_json)
            )
            saved += 1
        conn.commit()
        print(f"  \u2705 已保存 {saved}/{top_n} 条推荐到数据库")
    except Exception as e:
        print(f"  \u26a0\ufe0f 数据库保存失败（不影响选股结果）: {e}")
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
