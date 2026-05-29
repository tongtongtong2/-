"""
全市场自适应量化交易系统 - 主入口

用法：python run_backtest.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quant_engine.data.data_loader import DataLoader
from quant_engine.backtest.engine import BacktestEngine, BacktestConfig


def main():
    print("=" * 60)
    print("    全市场自适应量化交易系统 v1.0")
    print("    牛市进攻 | 熊市防守 | 震荡套利")
    print("=" * 60)
    
    # 配置
    config = BacktestConfig(
        initial_cash=200_000,
        start_date="2024-01-01",
        end_date="2026-05-29",
    )
    
    # 加载数据
    print("\n[1/4] 加载数据...")
    loader = DataLoader()
    
    # 直接用模拟数据（包含牛熊震荡三种行情）
    index_data = loader._generate_synthetic_index(config.start_date, config.end_date)
    stock_data = loader.generate_synthetic_stocks(50, config.start_date, config.end_date)
    
    # 运行回测
    print("\n[2/4] 运行回测...")
    engine = BacktestEngine(config)
    result = engine.run(index_data, stock_data)
    
    # 输出报告
    print("\n[3/4] 生成报告...")
    engine.print_report(result)
    
    # 输出交易明细（最近20笔）
    print("\n[4/4] 最近交易记录:")
    print(f"{'日期':<12}{'代码':<8}{'操作':<6}{'价格':<10}{'数量':<8}{'原因':<30}{'状态':<6}")
    print("-" * 80)
    for t in result.trades[-20:]:
        print(f"{t.date:<12}{t.code:<8}{t.action:<6}{t.price:<10.2f}{t.shares:<8}{t.reason[:28]:<30}{t.market_state:<6}")
    
    print(f"\n总交易: {len(result.trades)} 笔")
    
    return result


if __name__ == "__main__":
    main()
