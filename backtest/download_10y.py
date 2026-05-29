"""批量下载10年日线数据（搜狐财经）"""
import requests
import json
import time
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = Path(__file__).parent / "data" / "market_data.db"

session = requests.Session()
session.trust_env = False
session.headers.update({"User-Agent": "Mozilla/5.0"})

def fetch_sohu(sohu_code):
    """从搜狐拉10年日线"""
    url = "http://q.stock.sohu.com/hisHq"
    params = {"code": sohu_code, "start": "20160101", "end": "20260529", "stat": "1", "order": "A", "period": "d"}
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return data[0].get("hq", [])
            time.sleep(1)
        except:
            time.sleep(2)
    return []

def get_codes():
    codes = []
    for i in range(600000, 606000):
        codes.append((f"{i:06d}", f"cn_{i:06d}"))
    for i in range(1, 4000):
        codes.append((f"{i:06d}", f"cn_{i:06d}"))
    for i in range(300000, 302000):
        codes.append((f"{i:06d}", f"cn_{i:06d}"))
    return codes

def main():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    
    # 已有10年数据的跳过
    cur = conn.execute("""
        SELECT stock_code FROM daily_bars
        WHERE trade_date <= '2016-06-01'
        GROUP BY stock_code
        HAVING COUNT(*) >= 50
    """)
    existing = {row[0] for row in cur.fetchall()}
    
    all_codes = get_codes()
    to_download = [(code, sohu) for code, sohu in all_codes if code not in existing]
    
    print(f"下载目标: {len(to_download)} 只 (已有{len(existing)}只跳过)")
    
    done = 0
    success = 0
    failed = 0
    
    def download_one(item):
        code, sohu = item
        bars = fetch_sohu(sohu)
        return code, bars
    
    batch_size = 100
    for batch_start in range(0, len(to_download), batch_size):
        batch = to_download[batch_start:batch_start+batch_size]
        
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(download_one, item) for item in batch]
            for fut in as_completed(futures):
                code, bars = fut.result()
                done += 1
                if bars and len(bars) >= 100:
                    # 插入数据库
                    rows = []
                    for bar in bars:
                        try:
                            date = bar[0]
                            open_p = float(bar[1].replace(",","")) if bar[1] else None
                            close_p = float(bar[2].replace(",","")) if bar[2] else None
                            low_p = float(bar[5].replace(",","")) if bar[5] else None
                            high_p = float(bar[6].replace(",","")) if bar[6] else None
                            vol = float(bar[7].replace(",","")) if bar[7] else None
                            rows.append((code, date, open_p, high_p, low_p, close_p, vol))
                        except:
                            continue
                    if rows:
                        conn.executemany(
                            "INSERT OR REPLACE INTO daily_bars (stock_code, trade_date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                            rows
                        )
                        success += 1
                else:
                    failed += 1
        
        conn.commit()
        elapsed_pct = done / len(to_download) * 100
        print(f"  进度: {done}/{len(to_download)} ({elapsed_pct:.0f}%) | 成功{success} 失败{failed}")
    
    conn.close()
    print(f"\n完成! 成功{success} 失败{failed}")

if __name__ == "__main__":
    main()
