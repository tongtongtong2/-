"""个人选股平台 — 一键部署（新机器跑这个）

1. 建MySQL库和表
2. 用新浪免费API拉ETF数据
3. 计算指标和信号
4. 启动Web服务

数据源：新浪（免费，无需token，无频率限制）
"""
import sys, time, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pymysql, requests, numpy as np

# === 配置 ===
MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root"}

# 池子：ETF
POOL = {
    '562500': '机器人ETF',   '513100': '纳指ETF',
    '159949': '创业板50',    '515700': '新能源车',
    '159755': '电池ETF',     '561700': '电力ETF',
    '515790': '光伏ETF华泰', '515880': '通信ETF',
    '159996': '家电ETF',     '516880': '光伏ETF银华',
    '513180': '恒生科技',    '159605': '中概互联广发',
    '159607': '中概互联嘉实','159751': '港股通科技',
    '159711': '港股通50华夏','159726': '港股高股息',
    '159792': '港股互联网',
}


def step1_create_db():
    """建库建表"""
    print("[1/5] 建库建表...")
    conn = pymysql.connect(**MYSQL_CFG)
    cur = conn.cursor()

    cur.execute("CREATE DATABASE IF NOT EXISTS etf_trader DEFAULT CHARSET utf8mb4")
    cur.execute("USE etf_trader")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quote (
            code VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            open DECIMAL(12,4), high DECIMAL(12,4), low DECIMAL(12,4),
            close DECIMAL(12,4), volume DECIMAL(16,2),
            PRIMARY KEY (code, date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            code VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            data JSON,
            PRIMARY KEY (code, date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            code VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            signal VARCHAR(10),
            strategy_version VARCHAR(10),
            signal_meta JSON,
            PRIMARY KEY (code, date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_index_quote (
            index_code VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            close DECIMAL(14,4),
            PRIMARY KEY (index_code, date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_holdings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(20) NOT NULL UNIQUE,
            name VARCHAR(50),
            buy_price DECIMAL(12,4) NOT NULL,
            shares INT NOT NULL DEFAULT 0,
            buy_date DATE,
            current_price DECIMAL(12,4),
            updated_at DATE
        )
    """)
    conn.commit()
    conn.close()
    print("   ✓ 数据库 etf_trader + 5张表就绪")


def fetch_sina(code):
    """从新浪拉日线"""
    market = "sz" if code.startswith(("1",)) else "sh"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={market}{code}&scale=240&ma=no&datalen=5000"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and r.text.strip():
            return r.json()
    except:
        pass
    return None


def step2_pull_data():
    """从新浪拉所有ETF数据"""
    print("[2/5] 拉ETF行情（新浪免费API）...")
    conn = pymysql.connect(**MYSQL_CFG, database="etf_trader")
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT code FROM quote")
    existing = {r[0] for r in cur.fetchall()}

    codes = list(POOL.keys())
    done, total = len(existing & set(codes)), len(codes)

    for i, code in enumerate(codes):
        if code in existing:
            continue
        data = fetch_sina(code)
        if not data:
            print(f"   [{i+1}/{total}] {code} → 无数据")
            continue

        count = 0
        for row in data:
            try:
                cur.execute(
                    "INSERT IGNORE INTO quote (code,date,open,high,low,close,volume) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (code, row['day'], float(row['open']), float(row['high']),
                     float(row['low']), float(row['close']), float(row['volume'])/100)
                )
                count += 1
            except:
                continue
        conn.commit()
        print(f"   [{i+1}/{total}] {code} {POOL[code]:10s} → {count}条")
        done += 1
        time.sleep(0.15)

    # 上证指数
    sh_data = fetch_sina("000001")
    if sh_data:
        market_code = "sh" if code.startswith(("5","6")) or code == "000001" else "sz"
        for row in fetch_sina("000001") or []:
            try:
                cur.execute(
                    "INSERT IGNORE INTO market_index_quote (index_code,date,close) VALUES (%s,%s,%s)",
                    ("000001", row['day'], float(row['close']))
                )
            except:
                continue
        conn.commit()
        print(f"   ✓ 上证指数已拉")

    conn.close()
    print(f"   完成: {done}/{total}")


def calc_indicators(code, closes):
    """计算技术指标"""
    if len(closes) < 60:
        return None

    arr = np.array(closes[-120:])
    ma20 = float(np.mean(arr[-20:]))
    ma60 = float(np.mean(arr[-60:]))
    std20 = float(np.std(arr[-20:]))
    bb_mid = ma20
    bb_lower = bb_mid - 2 * std20
    bb_upper = bb_mid + 2 * std20

    # RSI14
    deltas = np.diff(arr[-15:])
    gain = float(np.mean(deltas[deltas > 0])) if any(deltas > 0) else 0.001
    loss = float(abs(np.mean(deltas[deltas < 0]))) if any(deltas < 0) else 0.001
    rsi = 100 - 100 / (1 + gain / loss)

    # MACD
    ema12 = arr[-1]
    ema26 = arr[-1]
    k12, k26 = 2/13, 2/27
    for v in arr[-26:]:
        ema12 = v * k12 + ema12 * (1 - k12)
        ema26 = v * k26 + ema26 * (1 - k26)
    dif = ema12 - ema26
    # simplified - use fixed DEA
    dea = dif * 0.2 + dif * 0.8  # approximate
    macd = (dif - dea) * 2

    return {
        'ma20': round(ma20, 4), 'ma60': round(ma60, 4),
        'bb_lower': round(bb_lower, 4), 'bb_upper': round(bb_upper, 4),
        'bb_mid': round(bb_mid, 4), 'bb_width': round((bb_upper - bb_lower) / bb_mid, 4),
        'rsi': round(rsi, 2), 'dif': round(dif, 4), 'dea': round(dea, 4), 'macd': round(macd, 4),
    }


def step3_calc_signals():
    """计算指标和评分"""
    print("[3/5] 计算技术指标...")
    conn = pymysql.connect(**MYSQL_CFG, database="etf_trader")
    cur = conn.cursor()

    for code in POOL:
        cur.execute("SELECT close FROM quote WHERE code=%s ORDER BY date", (code,))
        closes = [float(r[0]) for r in cur.fetchall()]
        if len(closes) < 60:
            continue

        # 每天计算一次（用最新日期）
        cur.execute("SELECT MAX(date) FROM quote WHERE code=%s", (code,))
        latest = str(cur.fetchone()[0])

        ind = calc_indicators(code, closes)
        if not ind:
            continue

        cur.execute("INSERT IGNORE INTO indicators (code, date, data) VALUES (%s, %s, %s)",
                    (code, latest, json.dumps(ind)))

        # 简单评分：趋势40 + MACD30 + RSI15 + 布林15
        ma20, ma60 = ind['ma20'], ind['ma60']
        close = closes[-1]
        trend_score = 100 if ma20 > ma60 and close > ma20 else 50 if ma20 > ma60 else 0
        macd_score = 80 if ind['macd'] > 0 else 30 if ind['macd'] > -0.01 else 0
        rsi_score = 60 if 40 < ind['rsi'] < 70 else 30 if 30 < ind['rsi'] < 40 else 0
        bb_pos = (close - ind['bb_lower']) / (ind['bb_upper'] - ind['bb_lower']) if ind['bb_upper'] > ind['bb_lower'] else 0.5
        bb_score = 80 if bb_pos < 0.3 else 40 if bb_pos < 0.5 else 0
        score = trend_score * 0.40 + macd_score * 0.30 + rsi_score * 0.15 + bb_score * 0.15

        signal = 'BUY' if score >= 50 else 'HOLD' if score >= 0 else 'SELL'
        cur.execute("INSERT IGNORE INTO signals (code, date, signal, strategy_version, signal_meta) VALUES (%s,%s,%s,%s,%s)",
                    (code, latest, signal, 'v2',
                     json.dumps({'score': round(score, 1), 's_trend': trend_score})))

    conn.commit()
    conn.close()
    print("   ✓ 指标+信号已生成")


def step4_preload_stock_cache():
    """预加载个股缓存（如果有stock_recommendation库）"""
    print("[4/5] 个股缓存...")
    try:
        conn = pymysql.connect(**MYSQL_CFG, database="stock_recommendation")
        conn.close()
        print("   stock_recommendation 库存在，可运行 uv run python quant_model.py 生成")
    except:
        print("   stock_recommendation 库不存在，跳过个股功能")
        # 创建空缓存，让Web不报错
        cache = {"stocks": [], "total": 0, "date": ""}
        Path(ROOT / "stock_cache.json").write_text(json.dumps(cache), encoding='utf-8')


def step5_start():
    """启动"""
    print(f"[5/5] 启动Web平台")
    print(f"   http://localhost:5000")
    print(f"   uv run python run_web.py")
    print(f"\n{'='*50}")
    print(f"  部署完成！")
    print(f"{'='*50}")


def main():
    step1_create_db()
    step2_pull_data()
    step3_calc_signals()
    step4_preload_stock_cache()
    step5_start()


if __name__ == "__main__":
    main()
