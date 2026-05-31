import pandas as pd

from app.signal_generator import SignalGenerator


def _fake_history(closes, vols=None):
    n = len(closes)
    if vols is None:
        vols = [1_000_000] * n
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=n, freq="D").date,
            "close": closes,
            "volume": vols,
        }
    )


def test_initial_signal_is_buy():
    g = SignalGenerator()
    signal, reason = g.generate_signal(0.0, history=None, hold_days=0, is_initial=True)
    assert signal == "buy"
    assert "买入" in reason


def test_take_profit_triggers_sell():
    g = SignalGenerator(take_profit=0.10)
    signal, reason = g.generate_signal(0.12, history=_fake_history([10] * 25))
    assert signal == "sell"
    assert "止盈" in reason


def test_stop_loss_triggers_sell():
    g = SignalGenerator(stop_loss=-0.05)
    signal, reason = g.generate_signal(-0.06, history=_fake_history([10] * 25))
    assert signal == "sell"
    assert "止损" in reason


def test_max_hold_days_when_negative_triggers_sell():
    g = SignalGenerator(max_hold_days=20)
    signal, _ = g.generate_signal(-0.02, history=_fake_history([10] * 25), hold_days=21)
    assert signal == "sell"


def test_normal_change_returns_hold():
    closes = list(range(10, 35))  # 上升趋势，5日均线 > 10日均线
    g = SignalGenerator()
    signal, _ = g.generate_signal(0.04, history=_fake_history(closes), hold_days=3)
    assert signal == "hold"


def test_ma_deterioration_with_negative_return_sells():
    # 先涨后跌，造成 MA10 低于 MA20；change_percent 为负才触发卖出
    closes = list(range(10, 30)) + list(range(29, 14, -1))  # 20 bars 上涨 + 15 bars 下跌
    g = SignalGenerator()
    signal, reason = g.generate_signal(-0.03, history=_fake_history(closes), hold_days=5)
    assert signal == "sell"
    assert "MA10" in reason
