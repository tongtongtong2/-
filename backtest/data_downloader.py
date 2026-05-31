"""下载历史数据到本地 SQLite。

数据源：新浪财经日线接口（已验证可用）。
范围：沪深主板 + 创业板，约4900只，过去14个月日线。
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

# 清代理
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import requests

from data_store import DataStore


def get_all_a_codes() -> list[tuple[str, str]]:
    """生成沪深A股代码列表，返回 [(code, sina_symbol), ...]"""
    codes = []
    for i in range(600000, 606000):
        codes.append((f"{i:06d}", f"sh{i:06d}"))
    for i in range(1, 4000):
        codes.append((f"{i:06d}", f"sz{i:06d}"))
    for i in range(300000, 302000):
        codes.append((f"{i:06d}", f"sz{i:06d}"))
    return codes


def fetch_sina_daily(sina_symbol: str, session: requests.Session, days: int = 300) -> pd.DataFrame:
    url = "https://quotes.sina.cn/cn/api/jsonp_v2.php"
    url += f"/var%20_{sina_symbol}_{days}/CN_MarketDataService.getKLineData"
    params = {
        "symbol": sina_symbol,
        "scale": "240",
        "ma": "no",
        "datalen": str(days),
    }
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code != 200:
                time.sleep(1)
                continue
            break
        except Exception:
            time.sleep(2)
            continue
    else:
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
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df


def fetch_tencent_names(codes_with_prefix: list[str], session: requests.Session) -> dict[str, str]:
    """批量从腾讯拿股票名称。"""
    names = {}
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
            if len(parts) >= 3:
                code = parts[2]
                name = parts[1]
                if code and name:
                    names[code] = name
    return names


def fetch_index_daily(session: requests.Session, days: int = 300) -> pd.DataFrame:
    """下载沪深300指数日线。"""
    sina_symbol = "sh000300"
    url = "https://quotes.sina.cn/cn/api/jsonp_v2.php"
    url += f"/var%20_{sina_symbol}_{days}/CN_MarketDataService.getKLineData"
    params = {"symbol": sina_symbol, "scale": "240", "ma": "no", "datalen": str(days)}
    try:
        r = session.get(url, params=params, timeout=20)
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

    df = pd.DataFrame(data)
    df.rename(columns={"day": "trade_date"}, inplace=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df[["trade_date", "close"]]


def main():
    print("=" * 60)
    print("  历史数据下载器")
    print("=" * 60)

    store = DataStore()
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    all_codes = get_all_a_codes()
    print(f"\n  目标: {len(all_codes)} 只股票, 约300个交易日日线")
    print(f"  数据源: 新浪财经")

    existing_count = store.count_bars()
    if existing_count > 0:
        print(f"  已有数据: {existing_count} 条 ({store.count_stocks()} 只股票)")
        print(f"  将增量更新...")

    # 下载股票名称
    print("\n[1/3] 下载股票名称...")
    prefix_codes = []
    code_map = {}
    for code, sina_sym in all_codes:
        prefix = "sh" + code if code.startswith("6") else "sz" + code
        prefix_codes.append(prefix)
        code_map[code] = sina_sym

    names = fetch_tencent_names(prefix_codes, session)
    for code, name in names.items():
        board = "创业板" if code.startswith("30") else "主板"
        store.upsert_stock_info(code, name, board)
    print(f"  获取到 {len(names)} 只股票名称")

    # 过滤掉ST和退市
    valid_codes = []
    for code, sina_sym in all_codes:
        name = names.get(code, "")
        if "ST" in name.upper() or "退" in name:
            continue
        if not name:
            continue
        valid_codes.append((code, sina_sym))
    print(f"  去除ST/退市后: {len(valid_codes)} 只")

    # 下载日线数据
    print(f"\n[2/3] 下载日线数据 (12线程并发)...")
    done = 0
    failed = 0
    total = len(valid_codes)

    def download_one(item):
        code, sina_sym = item
        df = fetch_sina_daily(sina_sym, session, days=300)
        return code, df

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(download_one, item) for item in valid_codes]
        for fut in as_completed(futures):
            done += 1
            code, df = fut.result()
            if df.empty or len(df) < 10:
                failed += 1
            else:
                df["stock_code"] = code
                store.upsert_daily_bars(df[["stock_code", "trade_date", "open", "high", "low", "close", "volume"]])
            if done % 100 == 0:
                pct = done / total * 100
                print(f"  进度: {done}/{total} ({pct:.1f}%) | 失败: {failed}")

    print(f"  完成: {done} 只 | 失败: {failed} 只")

    # 下载沪深300指数
    print(f"\n[3/3] 下载沪深300指数...")
    idx_df = fetch_index_daily(session, days=300)
    if not idx_df.empty:
        store.upsert_index_daily(idx_df)
        print(f"  获取到 {len(idx_df)} 个交易日")
    else:
        print(f"  下载失败，回测将无法对比基准")

    # 统计
    print(f"\n{'=' * 60}")
    print(f"  下载完成!")
    print(f"  总数据量: {store.count_bars()} 条")
    print(f"  覆盖股票: {store.count_stocks()} 只")
    trade_dates = store.get_trade_dates("2000-01-01", "2030-01-01")
    if trade_dates:
        print(f"  日期范围: {trade_dates[0]} ~ {trade_dates[-1]}")
        print(f"  交易日数: {len(trade_dates)} 天")
    print(f"{'=' * 60}")

    store.close()


if __name__ == "__main__":
    main()
