"""回测入口脚本。

用法:
    python backtest/run_backtest.py
    python backtest/run_backtest.py --take-profit 0.10 --stop-loss -0.03 --max-hold 20
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from data_store import DataStore
from engine import BacktestEngine
from report import generate_report


def main():
    parser = argparse.ArgumentParser(description="股票选股策略回测")
    parser.add_argument("--start", default="2025-06-01", help="回测开始日期")
    parser.add_argument("--end", default="2026-05-22", help="回测结束日期")
    parser.add_argument("--take-profit", type=float, default=0.15, help="止盈比例")
    parser.add_argument("--stop-loss", type=float, default=-0.05, help="止损比例")
    parser.add_argument("--max-hold", type=int, default=30, help="最长持有天数")
    parser.add_argument("--top-n", type=int, default=10, help="每日选股数")
    parser.add_argument("--max-positions", type=int, default=10, help="最大持仓数")
    parser.add_argument("--no-chase", type=float, default=0, help="今日涨幅超过此值不买(百分比,如7)")
    parser.add_argument("--min-dist", type=float, default=0, help="距60日高点低于此值不买(小数,如0.05)")
    parser.add_argument("--no-market-filter", action="store_true", help="关闭市场环境过滤")
    parser.add_argument("--no-atr-stop", action="store_true", help="关闭ATR动态止损，用固定止损")
    parser.add_argument("--atr-mult", type=float, default=2.0, help="ATR止损倍数")
    parser.add_argument("--max-per-sector", type=int, default=2, help="同板块最大持仓数")
    args = parser.parse_args()

    print("=" * 60)
    print("  股票选股策略回测")
    print("=" * 60)

    store = DataStore()
    bar_count = store.count_bars()
    stock_count = store.count_stocks()

    if bar_count == 0:
        print("\n  错误: 没有本地数据！请先运行 data_downloader.py 下载数据。")
        print("  命令: python backtest/data_downloader.py")
        sys.exit(1)

    print(f"\n  本地数据: {bar_count} 条 | {stock_count} 只股票")
    print(f"  回测参数:")
    print(f"    区间: {args.start} ~ {args.end}")
    print(f"    止盈: {args.take_profit*100:.0f}%")
    print(f"    止损: {args.stop_loss*100:.0f}%")
    print(f"    最长持有: {args.max_hold} 天")
    print(f"    每日选股: {args.top_n} 只")
    print(f"    最大持仓: {args.max_positions} 只")
    print(f"    市场过滤: {'开' if not args.no_market_filter else '关'}（仅在沪深300>MA60时开仓）")
    print(f"    ATR止损: {'开' if not args.no_atr_stop else '关'}（ATR×{args.atr_mult}）")
    print(f"    板块上限: {args.max_per_sector} 只/板块")
    print()

    engine = BacktestEngine(
        store=store,
        take_profit=args.take_profit,
        stop_loss=args.stop_loss,
        max_hold=args.max_hold,
        top_n=args.top_n,
        max_positions=args.max_positions,
        no_chase_pct=args.no_chase,
        min_dist_high=args.min_dist,
        use_market_filter=not args.no_market_filter,
        use_atr_stop=not args.no_atr_stop,
        atr_mult=args.atr_mult,
        max_per_sector=args.max_per_sector,
    )

    print("  开始回测...")
    t0 = time.time()
    trades = engine.run(args.start, args.end)
    elapsed = time.time() - t0
    print(f"\n  回测完成，耗时 {elapsed:.1f} 秒")

    # 获取基准数据
    index_df = store.get_index_daily(args.start, args.end)

    # 生成报告
    generate_report(
        trades=trades,
        daily_equity=engine.daily_equity,
        index_df=index_df,
        start_date=args.start,
        end_date=args.end,
    )

    store.close()


if __name__ == "__main__":
    main()
