"""回测框架 — 基于历史数据的策略回测和绩效指标计算"""
import uuid
from datetime import datetime
from typing import Optional

import numpy as np
import db
from engine.decision import decide
from engine.indicators import bollinger_bands, rsi, atr, ma, chg_pct, vol_ratio
from engine.scoring import composite_score


def compute_metrics(trades: list[dict], initial_capital: float = 100000.0) -> dict:
    """计算回测绩效指标

    Args:
        trades: 交易列表，每笔包含 {'pnl': float, 'date': str, ...}
        initial_capital: 初始资金

    Returns:
        {
            'total_return': float,      # 总收益率(%)
            'annualized_return': float,  # 年化收益率(%)
            'max_drawdown': float,       # 最大回撤(%)
            'sharpe_ratio': float,       # 夏普比率
            'win_rate': float,           # 胜率(%)
            'total_trades': int,         # 总交易数
        }
    """
    if not trades:
        return {
            'total_return': 0.0,
            'annualized_return': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'win_rate': 0.0,
            'total_trades': 0,
        }

    winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
    losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]

    total_pnl = sum(t.get('pnl', 0) for t in trades)
    total_return = (total_pnl / initial_capital) * 100

    win_rate = (len(winning_trades) / len(trades)) * 100 if trades else 0

    # 年化收益率
    if trades and len(trades) >= 1:
        first_date = datetime.strptime(trades[0]['date'], '%Y-%m-%d')
        last_date = datetime.strptime(trades[-1]['date'], '%Y-%m-%d')
        days = (last_date - first_date).days or 1
        years = days / 365.0
        if years > 0:
            annualized_return = (((1 + total_return / 100) ** (1 / years)) - 1) * 100
        else:
            annualized_return = total_return
    else:
        annualized_return = 0.0

    # 夏普比率
    daily_returns = []
    daily_pnl = {}
    for t in trades:
        date_key = t['date']
        daily_pnl[date_key] = daily_pnl.get(date_key, 0.0) + t.get('pnl', 0)

    if daily_pnl:
        pnl_values = list(daily_pnl.values())
        if len(pnl_values) > 1:
            daily_returns = [v / initial_capital for v in pnl_values]
            avg_return = np.mean(daily_returns)
            std_return = np.std(daily_returns, ddof=1)
            if std_return > 0:
                sharpe_ratio = (avg_return / std_return) * np.sqrt(252)
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0
    else:
        sharpe_ratio = 0.0

    # 最大回撤
    cumulative = initial_capital
    peak = initial_capital
    max_dd = 0.0
    for t in trades:
        cumulative += t.get('pnl', 0)
        if cumulative > peak:
            peak = cumulative
        dd = (cumulative - peak) / peak * 100 if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd

    return {
        'total_return': round(total_return, 2),
        'annualized_return': round(annualized_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'win_rate': round(win_rate, 1),
        'total_trades': len(trades),
    }


def run_backtest(
    code: str,
    name: str,
    quotes: list[dict],
    save_results: bool = False,
) -> dict:
    """对单只ETF运行回测

    Args:
        code: ETF代码
        name: ETF名称
        quotes: OHLCV数据列表，每项 {'date', 'open', 'high', 'low', 'close', 'volume'}
        save_results: 是否保存到数据库

    Returns:
        包含trades和metrics的字典
    """
    if len(quotes) < 66:
        return {
            'code': code,
            'name': name,
            'trades': [],
            'metrics': compute_metrics([]),
        }

    quotes_sorted = sorted(quotes, key=lambda x: x['date'])

    closes = np.array([r['close'] for r in quotes_sorted])
    highs = np.array([r['high'] for r in quotes_sorted])
    lows = np.array([r['low'] for r in quotes_sorted])
    volumes = np.array([r['volume'] for r in quotes_sorted])
    dates = [r['date'] for r in quotes_sorted]

    trades = []
    held = False
    entry_price = 0.0
    capital = 100000.0
    run_id = str(uuid.uuid4())[:8]

    # 滑动窗口：至少需要66天数据
    min_window = 66

    for i in range(min_window, len(dates)):
        window_closes = closes[:i + 1]
        window_highs = highs[:i + 1]
        window_lows = lows[:i + 1]
        window_volumes = volumes[:i + 1]
        current_date = dates[i]
        current_close = float(window_closes[-1])

        # 计算指标
        _, _, _, bb_pos = bollinger_bands(window_closes)
        rsi_val = rsi(window_closes)
        atr_pct_val = (atr(window_highs, window_lows, window_closes) / current_close * 100) if current_close > 0 else 0.0
        ma20_val = ma(window_closes, 20)
        ma60_val = ma(window_closes, 60)
        chg_5d_val = chg_pct(window_closes, 5)
        chg_20d_val = chg_pct(window_closes, 20)
        vr = vol_ratio(window_volumes)

        # 综合评分
        sc, trend_sc = composite_score(window_closes, window_highs, window_lows, window_volumes)

        # 大盘环境用自身走势模拟（简化的回测环境）
        # 实际回测中使用指数数据，这里用ETF自身趋势代替
        market_closes = window_closes[-60:]
        market_trend = ma(market_closes, 20)
        market_trend_5d_ago = ma(market_closes[:-5], 20) if len(market_closes) >= 25 else market_trend
        if market_trend_5d_ago > 0:
            mkt_trend_val = (market_trend - market_trend_5d_ago) / market_trend_5d_ago * 100
        else:
            mkt_trend_val = 0.0

        if mkt_trend_val > 1:
            mkt_state = 'bull'
        elif mkt_trend_val < -1:
            mkt_state = 'bear'
        else:
            mkt_state = 'range'

        # 计算持仓盈亏
        entry_pnl_val = 0.0
        if held and entry_price > 0:
            entry_pnl_val = (current_close - entry_price) / entry_price

        # 决策
        result = decide(
            code=code,
            score=sc,
            bb_pos=bb_pos,
            rsi_val=rsi_val,
            ma20=ma20_val,
            ma60=ma60_val,
            close=current_close,
            chg_5d=chg_5d_val,
            chg_20d=chg_20d_val,
            atr_pct=atr_pct_val,
            vol_ratio=vr,
            market_state=mkt_state,
            held=held,
            entry_pnl=entry_pnl_val,
        )

        action = result['action']
        pnl = 0.0

        if not held and action == 'BUY':
            # 买入
            held = True
            entry_price = current_close
            trade = {
                'date': current_date,
                'action': 'BUY',
                'code': code,
                'name': name,
                'price': current_close,
                'score': sc,
                'bb_pos': bb_pos,
                'reason': result['reason'],
                'pnl': 0.0,
                'capital': capital,
            }
            trades.append(trade)

        elif held and action in ('SELL', 'TAKE_PROFIT', 'STOP'):
            # 卖出
            pnl = (current_close - entry_price) * 100  # 假设100股
            capital += pnl
            trade = {
                'date': current_date,
                'action': action,
                'code': code,
                'name': name,
                'price': current_close,
                'score': sc,
                'bb_pos': bb_pos,
                'reason': result['reason'],
                'pnl': pnl,
                'capital': capital,
            }
            trades.append(trade)
            held = False
            entry_price = 0.0

    # 如果回测结束时还持有，按最后价格平仓
    if held and entry_price > 0 and len(quotes_sorted) > 0:
        final_close = float(quotes_sorted[-1]['close'])
        pnl = (final_close - entry_price) * 100
        capital += pnl
        trades.append({
            'date': dates[-1],
            'action': 'SELL',
            'code': code,
            'name': name,
            'price': final_close,
            'score': 0,
            'bb_pos': 0.5,
            'reason': '回测结束平仓',
            'pnl': pnl,
            'capital': capital,
        })

    # 保存到数据库
    if save_results and trades:
        with db.connect() as conn:
            for t in trades:
                conn.execute(
                    """INSERT INTO backtest_results
                       (run_id, date, action, code, name, price, score, bb_pos, reason, pnl, capital)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, t['date'], t['action'], t['code'], t['name'],
                        t['price'], t.get('score', 0), t.get('bb_pos', 0),
                        t.get('reason', ''), t.get('pnl', 0), t.get('capital', 0),
                    ),
                )
            conn.commit()

    metrics = compute_metrics(trades)

    return {
        'code': code,
        'name': name,
        'trades': trades,
        'metrics': metrics,
        'run_id': run_id,
    }
