"""
每日交易助手 - 早上9点运行
用法: python daily_advisor.py
功能:
  1. 显示昨日选股结果 + 今日开盘买入价
  2. 检查持仓是否需要卖出
  3. 输出今日操作建议
"""
import os, sys, json
from datetime import date, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 清代理
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

from config import Config
from app.database import db
from app import create_app
from app.models import StockRecommendation, StockDailyPerformance
from app.performance_tracker import PerformanceTracker
from app.signal_generator import SignalGenerator
from app.data_fetcher import get_default_fetcher
from app.utils import is_trading_day, get_logger

logger = get_logger("daily_advisor")

def check_today():
    """检查今天是否交易日"""
    today = date.today()
    if not is_trading_day(today):
        print(f"  {today} 非交易日，休息~")
        return False
    print(f"  {today} 交易日，开始分析...")
    return True

def show_yesterday_picks(app):
    """显示昨日选股 + 今早开盘价"""
    today = date.today()
    with app.app_context():
        # 找昨天的 pending 推荐（还没回填开盘价）
        pending = StockRecommendation.query.filter_by(
            recommend_date=today,
            source="system",
        ).all()
        
        # 也找最近3天的推荐
        from datetime import timedelta
        recent = StockRecommendation.query.filter(
            StockRecommendation.recommend_date >= today - timedelta(days=3),
            StockRecommendation.source == "system",
        ).order_by(StockRecommendation.recommend_date.desc()).all()
        
        if not recent:
            print("\n  最近3天无系统选股记录")
            return
        
        print(f"\n  {'='*50}")
        print(f"  选股记录 (最近3天)")
        print(f"  {'='*50}")
        
        fetcher = get_default_fetcher()
        for rec in recent:
            # 尝试获取实时价格
            try:
                spot = fetcher.get_realtime_prices([rec.stock_code])
                if not spot.empty:
                    cur_price = float(spot.iloc[0]["current_price"])
                else:
                    cur_price = float(rec.recommend_price) if rec.recommend_price else 0
            except:
                cur_price = float(rec.recommend_price) if rec.recommend_price else 0
            
            profit = 0
            if rec.recommend_price and cur_price:
                profit = (cur_price / float(rec.recommend_price) - 1) * 100
            
            status_icon = {"pending": "⏳", "filled": "✅", "void": "❌"}.get(rec.price_status, "?")
            print(f"\n  {status_icon} {rec.stock_code} {rec.stock_name}")
            print(f"     推荐日: {rec.recommend_date} | 推荐价: {rec.recommend_price}")
            print(f"     当前价: {cur_price:.2f} | 盈亏: {profit:+.2f}%")
            print(f"     来源: {rec.source} | 状态: {rec.status} | 观察: {'是' if rec.is_watched else '否'}")
            
            if rec.price_status == "pending":
                print(f"     ⚠️  等待今日开盘价回填 (09:35 自动执行)")
            elif rec.price_status == "filled" and profit >= 7:
                print(f"     🔔 盈利 > 7%，注意保本止损！")

def check_active_positions(app):
    """检查活跃持仓的卖出信号"""
    today = date.today()
    with app.app_context():
        actives = StockRecommendation.query.filter_by(
            status="active", price_status="filled"
        ).all()
        
        if not actives:
            print(f"\n  无活跃持仓")
            return
        
        print(f"\n  {'='*50}")
        print(f"  持仓监控 ({len(actives)} 只活跃)")
        print(f"  {'='*50}")
        
        sg = SignalGenerator()
        fetcher = get_default_fetcher()
        
        for rec in actives:
            try:
                spot = fetcher.get_realtime_prices([rec.stock_code])
                cur_price = float(spot.iloc[0]["current_price"]) if not spot.empty else 0
                change = (cur_price / float(rec.recommend_price) - 1) if rec.recommend_price and cur_price else 0
            except:
                cur_price = 0
                change = 0
            
            # 计算持有天数
            hold_days = (today - rec.recommend_date).days if rec.recommend_date else 0
            
            # 获取历史数据判断技术面
            try:
                history = fetcher.get_daily_history(rec.stock_code, days=60)
            except:
                history = None
            
            # 生成信号（非初始）
            signal, reason = sg.generate_signal(change, history=history, hold_days=hold_days, is_initial=False)
            
            icon = {"buy": "🟢", "hold": "🟡", "sell": "🔴"}.get(signal, "⚪")
            print(f"\n  {icon} {rec.stock_code} {rec.stock_name}")
            print(f"     成本: {rec.recommend_price} | 现价: {cur_price:.2f} | {change*100:+.2f}%")
            print(f"     持有: {hold_days}天 | 信号: {signal} — {reason}")
            
            if signal == "sell":
                print(f"     🚨 建议卖出！原因: {reason}")

def main():
    print("=" * 50)
    print("  每日交易助手")
    print("=" * 50)
    
    if not check_today():
        return
    
    app = create_app()
    
    # 1. 显示选股
    show_yesterday_picks(app)
    
    # 2. 检查持仓
    check_active_positions(app)
    
    # 3. 策略状态
    print(f"\n  {'='*50}")
    print(f"  策略参数")
    print(f"  {'='*50}")
    print(f"  止盈: +{Config.TAKE_PROFIT*100:.0f}%")
    print(f"  止损: {Config.STOP_LOSS*100:.0f}%")
    print(f"  最长持有: {Config.MAX_HOLD_DAYS}天")
    print(f"  市场过滤: {'开' if Config.MARKET_FILTER else '关'}")
    print(f"  行业限制: {Config.MAX_PER_SECTOR}只/行业")
    
    print(f"\n  {'='*50}")
    print(f"  操作建议:")
    print(f"  1. 查看上面 ✅ 的推荐，在 9:30 开盘后买入")
    print(f"  2. 看到 🔴 卖出信号，当天卖出")
    print(f"  3. 在 Web 界面标记 is_watched=True 后系统自动跟踪")
    print(f"  4. 明天早上 9 点再找我跑一次")
    print(f"  {'='*50}")

if __name__ == "__main__":
    main()
