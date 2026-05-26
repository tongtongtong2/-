import pandas as pd

from app.stock_selector import StockSelector


def _make_daily(prices):
    n = len(prices)
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=n, freq="D").date,
            "close": prices,
            "open": prices,
            "high": prices,
            "low": prices,
            "volume": [1_000_000 + i * 1000 for i in range(n)],
            "turnover": [1e8 + i * 1e5 for i in range(n)],
            "change_percent": [0.0] * n,
        }
    )


def test_compute_indicators_returns_key_fields():
    prices = list(range(100, 180))  # 80 bars, 稳步上涨
    daily = _make_daily(prices)
    ind = StockSelector._compute_indicators(daily)
    assert ind is not None
    assert "ret_5" in ind and "ret_20" in ind and "ret_60" in ind
    assert ind["ret_5"] > 0


def test_compute_indicators_none_for_short_history():
    daily = _make_daily([10, 11, 12])
    assert StockSelector._compute_indicators(daily) is None


def test_hard_filter_passes_bullish_trend():
    # 构造均线多头排列的数据：稳步上涨 80 天
    prices = [50 + i * 0.5 for i in range(80)]
    daily = _make_daily(prices)
    ind = StockSelector._compute_indicators(daily)
    assert ind is not None
    passed, _ = StockSelector._passes_hard_filter(ind)
    assert passed


def test_hard_filter_rejects_bearish_trend():
    # 构造均线空头排列的数据：先涨后跌
    prices = [50 + i * 0.5 for i in range(40)] + [70 - i * 0.5 for i in range(40)]
    daily = _make_daily(prices)
    ind = StockSelector._compute_indicators(daily)
    assert ind is not None
    passed, reason = StockSelector._passes_hard_filter(ind)
    assert not passed


def test_prefilter_removes_st_and_low_turnover():
    sel = StockSelector(min_volume=1e8)
    spot = pd.DataFrame(
        [
            {"stock_code": "600000", "stock_name": "浦发银行", "current_price": 10.0, "turnover": 5e8},
            {"stock_code": "000001", "stock_name": "ST 风险", "current_price": 5.0, "turnover": 5e8},
            {"stock_code": "000002", "stock_name": "万科A", "current_price": 18.0, "turnover": 1e7},
            {"stock_code": "688981", "stock_name": "中芯国际", "current_price": 80.0, "turnover": 5e8},
            {"stock_code": "300750", "stock_name": "宁德时代", "current_price": 200.0, "turnover": 5e8},
        ]
    )
    out = sel._prefilter(spot)
    codes = set(out["stock_code"].tolist())
    assert "600000" in codes
    assert "300750" in codes
    assert "000001" not in codes  # ST
    assert "000002" not in codes  # 成交额不足
    assert "688981" not in codes  # 科创板
