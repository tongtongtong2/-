"""模拟盘每日更新 — 收盘后运行
1. 从搜狐拉今日行情
2. 检查止损/止盈/超时
3. 如果有空仓位，跑V6选股补仓
4. 输出当日持仓状态
"""
import os, sys, json, time, sqlite3
import numpy as np
import requests
from datetime import date, timedelta
from pathlib import Path

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

BASE = Path(__file__).parent
DB_PATH = BASE / "backtest" / "data" / "market_data.db"
SIM_PATH = BASE / "sim_portfolio.json"

def fetch_today_price(code):
    """从搜狐拉今日行情"""
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    
    today_str = date.today().strftime("%Y%m%d")
    prefix = "cn_"
    url = f"https://q.stock.sohu.com/hisHq?code={prefix}{code}&start={today_str}&end={today_str}&stat=1&order=D&period=d&rt=json"
    try:
        r = session.get(url, timeout=10)
        data = r.json()
        if data and isinstance(data, list) and data[0].get("hq"):
            row = data[0]["hq"][0]
            return {
                "date": row[0],
                "open": float(row[1]),
                "close": float(row[2]),
                "low": float(row[5]),
                "high": float(row[6]),
                "volume": float(row[7].replace(",", "")),
            }
    except Exception as e:
        print(f"  拉取{code}失败: {e}")
    return None


def main():
    today = date.today().isoformat()
    print(f"\n{'='*50}")
    print(f"  模拟盘更新  {today}")
    print(f"{'='*50}")
    
    # 加载持仓
    sim = json.loads(SIM_PATH.read_text(encoding='utf-8'))
    
    capital = sim["initial_capital"]
    used = sum(p["cost"] for p in sim["positions"] if p["status"] == "holding")
    available = capital - used
    
    print(f"  本金: {capital}  已用: {used}  可用: {available}")
    print(f"  持仓数: {sum(1 for p in sim['positions'] if p['status']=='holding')}/{sim['max_positions']}")
    
    daily_entry = {"date": today, "events": []}
    
    # 更新每只持仓
    for pos in sim["positions"]:
        if pos["status"] != "holding":
            continue
        
        price_data = fetch_today_price(pos["code"])
        if not price_data:
            print(f"  [{pos['code']}] {pos['name']} — 无法获取今日数据(非交易日?)")
            continue
        
        close = price_data["close"]
        high = price_data["high"]
        low = price_data["low"]
        pnl = (close - pos["buy_price"]) * pos["shares"]
        pnl_pct = (close - pos["buy_price"]) / pos["buy_price"] * 100
        
        print(f"\n  [{pos['code']}] {pos['name']}")
        print(f"    买入{pos['buy_price']:.2f} → 今收{close:.2f}  盈亏{pnl:+.0f}元({pnl_pct:+.1f}%)")
        print(f"    今日: 开{price_data['open']:.2f} 高{high:.2f} 低{low:.2f} 收{close:.2f}")
        
        # 更新最高价
        if high > pos["highest_since_buy"]:
            pos["highest_since_buy"] = high
        
        # 检查止损
        if low <= pos["stop_loss"]:
            pos["status"] = "closed"
            pos["sell_date"] = today
            pos["sell_price"] = pos["stop_loss"]
            pos["pnl"] = (pos["stop_loss"] - pos["buy_price"]) * pos["shares"]
            sim["closed_trades"].append(pos.copy())
            event = f"止损卖出 {pos['code']} {pos['name']} @ {pos['stop_loss']:.2f}, 亏{pos['pnl']:.0f}元"
            daily_entry["events"].append(event)
            print(f"    ⛔ 触发止损! 卖出@{pos['stop_loss']:.2f}")
            continue
        
        # 检查移动止盈
        if not pos["trail_active"] and high >= pos["trail_activate"]:
            pos["trail_active"] = True
            pos["trail_sell_price"] = pos["highest_since_buy"] * 0.97
            print(f"    ✅ 移动止盈激活! 当前止盈价={pos['trail_sell_price']:.2f}")
            daily_entry["events"].append(f"{pos['code']} 移动止盈激活")
        
        if pos["trail_active"]:
            pos["trail_sell_price"] = pos["highest_since_buy"] * 0.97
            if low <= pos["trail_sell_price"]:
                pos["status"] = "closed"
                pos["sell_date"] = today
                pos["sell_price"] = pos["trail_sell_price"]
                pos["pnl"] = (pos["trail_sell_price"] - pos["buy_price"]) * pos["shares"]
                sim["closed_trades"].append(pos.copy())
                event = f"止盈卖出 {pos['code']} {pos['name']} @ {pos['trail_sell_price']:.2f}, 赚{pos['pnl']:.0f}元"
                daily_entry["events"].append(event)
                print(f"    💰 触发移动止盈! 卖出@{pos['trail_sell_price']:.2f}")
                continue
            else:
                print(f"    移动止盈跟踪中: 最高{pos['highest_since_buy']:.2f} 止盈价{pos['trail_sell_price']:.2f}")
        
        # 检查超时
        if today >= pos["max_hold_date"]:
            pos["status"] = "closed"
            pos["sell_date"] = today
            pos["sell_price"] = close
            pos["pnl"] = (close - pos["buy_price"]) * pos["shares"]
            sim["closed_trades"].append(pos.copy())
            event = f"超时卖出 {pos['code']} {pos['name']} @ {close:.2f}, {'赚' if pos['pnl']>0 else '亏'}{abs(pos['pnl']):.0f}元"
            daily_entry["events"].append(event)
            print(f"    ⏰ 持仓满20天! 卖出@{close:.2f}")
            continue
    
    # 清理已平仓
    sim["positions"] = [p for p in sim["positions"] if p["status"] == "holding"]
    
    # 汇总
    holding_count = len(sim["positions"])
    total_pnl = sum(t.get("pnl", 0) or 0 for t in sim["closed_trades"])
    unrealized = sum((fetch_today_price(p["code"]) or {}).get("close", p["buy_price"]) - p["buy_price"]) * p["shares"] 
                     for p in sim["positions"]) if sim["positions"] else 0
    
    print(f"\n{'─'*50}")
    print(f"  持仓: {holding_count}/{sim['max_positions']}")
    print(f"  已实现盈亏: {total_pnl:+.0f}元")
    print(f"  总资产: {capital + total_pnl:.0f}元")
    
    sim["daily_log"].append(daily_entry)
    SIM_PATH.write_text(json.dumps(sim, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n  ✅ 已保存到 sim_portfolio.json")


if __name__ == "__main__":
    main()
