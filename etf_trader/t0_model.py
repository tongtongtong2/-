"""老登股T+0模型 — 核电+农行专做波段"""
import pymysql, numpy as np
from collections import defaultdict

MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root",
              "database": "stock_recommendation", "charset": "utf8mb4"}

def load(stock_code):
    conn = pymysql.connect(**MYSQL_CFG)
    cur = conn.cursor()
    cur.execute("""SELECT b.trade_date, b.open, b.high, b.low, b.close, b.volume
                   FROM daily_bars b WHERE b.stock_code=%s AND b.trade_date>='2024-01-01'
                   ORDER BY b.trade_date""", (stock_code,))
    data = [(str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)) for r in cur.fetchall()]
    conn.close()
    return data


def analyze(code, name):
    data = load(code)
    closes = np.array([d[4] for d in data])
    highs = np.array([d[2] for d in data])
    lows = np.array([d[3] for d in data])
    volumes = np.array([d[5] for d in data])
    
    last_close = closes[-1]
    last_date = data[-1][0]
    
    # 1. 支撑位/压力位（近20日）
    support = np.min(lows[-20:])
    resistance = np.max(highs[-20:])
    mid = (support + resistance) / 2
    
    # 2. 当前位置
    position = (last_close - support) / (resistance - support) if resistance > support else 0.5
    
    # 3. ATR（日均波动）
    tr = np.maximum(highs[-14:] - lows[-14:], 
                    np.maximum(np.abs(highs[-14:] - closes[-15:-1]),
                               np.abs(lows[-14:] - closes[-15:-1])))
    atr = float(np.mean(tr))
    atr_pct = atr / last_close * 100
    
    # 4. 缩量判断（缩量适合做T）
    vol5 = np.mean(volumes[-5:])
    vol20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol5
    vol_ratio = vol5 / vol20
    
    # 5. 建议
    buy_zone = support + atr * 0.5  # 支撑上方半个ATR
    sell_zone = resistance - atr * 0.5
    
    print(f"\n{'='*55}")
    print(f"  {name} ({code})  T+0模型 — {last_date}")
    print(f"{'='*55}")
    print(f"  现价: {last_close:.2f}")
    print(f"  支撑: {support:.2f}  压力: {resistance:.2f}  中轴: {mid:.2f}")
    print(f"  日波动: ±{atr_pct:.1f}%  (ATR: {atr:.2f})")
    print(f"  当前: 距支撑{((last_close-support)/support*100):+.1f}%  距压力{((last_close-resistance)/resistance*100):+.1f}%")
    
    if position < 0.3:
        print(f"\n  🟢 接近支撑！明天挂单{last_close*0.995:.2f}~{buy_zone:.2f}买入")
        print(f"     目标卖出: {sell_zone:.2f} (赚{(sell_zone/buy_zone-1)*100:.1f}%)")
        print(f"     止损: {support*0.98:.2f}")
    elif position > 0.7:
        print(f"\n  🔴 接近压力！明天挂单{sell_zone:.2f}~{last_close*1.005:.2f}卖出")
        print(f"     回落到{buy_zone:.2f}再买回")
    else:
        print(f"\n  🟡 中间位置，缩量{'中适合做T' if vol_ratio<0.8 else '不适合做T'}")
        print(f"     买点: {buy_zone:.2f}  卖点: {sell_zone:.2f}")
        print(f"     差价空间: {(sell_zone-buy_zone)/buy_zone*100:.1f}%")
    
    # 回测T+0效果
    wins = 0
    total_pnl = 0
    for i in range(20, len(data)):
        local_high = np.max(highs[i-20:i])
        local_low = np.min(lows[i-20:i])
        buy_target = local_low + np.mean(tr[i-14:i]) * 0.5
        sell_target = local_high - np.mean(tr[i-14:i]) * 0.5
        if buy_target < lows[i]:  # 盘中触及买点
            if highs[i] > sell_target:  # 当天就能卖
                pnl = (sell_target / buy_target - 1) * 100
                total_pnl += pnl
                wins += 1 if pnl > 0 else 0
    if wins > 0:
        print(f"\n  回测(T+0模拟,1年): 成功{wins}次  均利:{total_pnl/wins:+.2f}%")
        print(f"  预估年化: {total_pnl:.0f}% (每日操作)")

# 分析
analyze('601985', '中国核电')
analyze('601288', '农业银行')
analyze('600900', '长江电力')  # 对比
