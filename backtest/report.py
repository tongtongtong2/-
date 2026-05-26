"""回测报告生成。"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd


def generate_report(trades: list, daily_equity: list, index_df: pd.DataFrame,
                    start_date: str, end_date: str, output_dir: str = "backtest/results"):
    if not trades:
        print("\n  没有交易记录，无法生成报告。")
        return

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 基础统计
    returns = [t.return_pct for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    total_trades = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total_trades * 100
    avg_return = np.mean(returns) * 100
    avg_win = np.mean(wins) * 100 if wins else 0
    avg_loss = np.mean(losses) * 100 if losses else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
    max_win = max(returns) * 100
    max_loss = min(returns) * 100

    # 按月统计
    monthly = {}
    for t in trades:
        month = t.exit_date[:7]
        if month not in monthly:
            monthly[month] = []
        monthly[month].append(t.return_pct)

    # 年化收益（假设等权，每笔交易占总资金的 1/MAX_POSITIONS）
    # 简化计算：用所有交易的平均收益 × 年交易次数 / 持仓数
    avg_hold_days = np.mean([t.hold_days for t in trades])
    trades_per_year = 242 / avg_hold_days * 10  # 每年约242个交易日，每天最多10只
    annual_return = np.mean(returns) * trades_per_year / 10 * 100  # 除以10因为等权分10份

    # Sharpe（简化：用交易收益率序列）
    if len(returns) > 1:
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(trades_per_year / 10)
    else:
        sharpe = 0

    # 最大回撤（基于累计净值）
    cumulative = np.cumprod([1 + r / 10 for r in returns])  # 每笔占1/10仓位
    peak = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - peak) / peak
    max_drawdown = np.min(drawdowns) * 100

    # vs 沪深300
    benchmark_return = 0.0
    if not index_df.empty and len(index_df) >= 2:
        idx_start = index_df.iloc[0]["close"]
        idx_end = index_df.iloc[-1]["close"]
        benchmark_return = (idx_end / idx_start - 1) * 100

    # 平仓原因分布
    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # 输出报告
    print(f"\n{'=' * 60}")
    print(f"  回测报告  {start_date} ~ {end_date}")
    print(f"{'=' * 60}")
    print()
    print(f"  总交易次数:     {total_trades}")
    print(f"  胜率:           {win_rate:.1f}% ({win_count}胜 / {loss_count}负)")
    print(f"  平均收益:       {avg_return:+.2f}%")
    print(f"  平均盈利:       {avg_win:+.2f}%  (盈利交易)")
    print(f"  平均亏损:       {avg_loss:+.2f}%  (亏损交易)")
    print(f"  盈亏比:         {profit_factor:.2f}")
    print(f"  最大单笔盈利:   {max_win:+.1f}%")
    print(f"  最大单笔亏损:   {max_loss:+.1f}%")
    print(f"  平均持有天数:   {avg_hold_days:.1f} 天")
    print()
    print(f"  年化收益率:     {annual_return:+.1f}% (估算)")
    print(f"  Sharpe Ratio:   {sharpe:.2f}")
    print(f"  最大回撤:       {max_drawdown:.1f}%")
    print()
    print(f"  沪深300同期:    {benchmark_return:+.1f}%")
    print(f"  超额收益:       {annual_return - benchmark_return:+.1f}%")
    print()
    print(f"  平仓原因分布:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}次 ({count/total_trades*100:.1f}%)")
    print()
    print(f"  月度收益:")
    months_sorted = sorted(monthly.keys())
    for m in months_sorted:
        rets = monthly[m]
        m_avg = np.mean(rets) * 100
        m_count = len(rets)
        m_wr = sum(1 for r in rets if r > 0) / m_count * 100
        print(f"    {m}: 平均 {m_avg:+.2f}% | {m_count}笔 | 胜率 {m_wr:.0f}%")
    print(f"\n{'=' * 60}")

    # 导出 CSV
    csv_path = Path(output_dir) / "trades.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["代码", "名称", "买入日期", "买入价", "卖出日期", "卖出价", "收益率%", "持有天数", "平仓原因"])
        for t in trades:
            writer.writerow([
                t.code, t.name, t.entry_date, f"{t.entry_price:.2f}",
                t.exit_date, f"{t.exit_price:.2f}",
                f"{t.return_pct*100:.2f}", t.hold_days, t.exit_reason,
            ])
    print(f"  交易记录已导出: {csv_path}")
    print(f"{'=' * 60}")

    # 结论
    print()
    if win_rate >= 55 and avg_return > 0.5:
        print("  结论: 策略有正期望值，可以考虑实盘跟踪。")
        print(f"  建议: 胜率 {win_rate:.0f}%，平均每笔赚 {avg_return:.2f}%，长期可累积。")
    elif win_rate >= 50 and avg_return > 0:
        print("  结论: 策略勉强有正期望，但优势不明显。")
        print("  建议: 需要优化参数或加入更多过滤条件。")
    else:
        print("  结论: 策略在回测期间表现不佳。")
        print("  建议: 需要重新设计策略逻辑或调整参数。")
    print()
