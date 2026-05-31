"""新浪免费API — 拉取ETF全量历史日线（前复权）
比Tushare快100倍，免费无限制。
"""
import requests, time, sys, json
from datetime import date
import pymysql

MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root",
              "database": "etf_trader", "charset": "utf8mb4"}

def load_etf_list():
    """从settings.yaml读取ETF列表"""
    import yaml
    with open("settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config['etf_list']

def fetch_sina(symbol: str):
    """从新浪拉取单只ETF全量日线"""
    market = "sz" if symbol.startswith("1") else "sh"
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={market}{symbol}&scale=240&ma=no&datalen=5000")
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return None
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        return data
    except Exception as e:
        print(f"  ✗ {symbol}: {e}")
        return None

def insert_quotes(symbol: str, rows: list):
    """批量插入行情到MySQL"""
    if not rows:
        return 0
    conn = pymysql.connect(**MYSQL_CFG)
    try:
        with conn.cursor() as cur:
            count = 0
            for row in rows:
                try:
                    day = row['day']
                    op = float(row['open'])
                    hi = float(row['high'])
                    lo = float(row['low'])
                    cl = float(row['close'])
                    vol = float(row['volume']) / 100  # 股→手
                    cur.execute(
                        "INSERT IGNORE INTO quote (code, date, open, high, low, close, volume) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (symbol, day, op, hi, lo, cl, vol)
                    )
                    count += 1
                except Exception:
                    continue
            conn.commit()
            return count
    finally:
        conn.close()

def main():
    etfs = load_etf_list()
    total = len(etfs)
    done = 0

    # 从已有数据继续
    conn = pymysql.connect(**MYSQL_CFG)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT code FROM quote")
        existing = {r[0] for r in cur.fetchall()}
    conn.close()

    print(f"ETF总数: {total}, 已有: {len(existing)}, 待拉: {total - len(existing)}")

    for i, etf in enumerate(etfs):
        code = etf['symbol']
        if code in existing:
            done += 1
            continue

        data = fetch_sina(code)
        if data:
            n = insert_quotes(code, data)
            print(f"  [{i+1}/{total}] {code} {etf['name'][:10]:10s} → {n}条")
            done += 1
        else:
            print(f"  [{i+1}/{total}] {code} → 无数据")

        # 温和间隔，避免被ban
        time.sleep(0.2)

    print(f"\n完成: {done}/{total}只")

if __name__ == "__main__":
    main()
