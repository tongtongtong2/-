from app.utils import format_pct, format_price, safe_float, chunked


def test_format_pct():
    assert format_pct(0.123) == "12.30%"
    assert format_pct(None) == "-"
    assert format_pct("bad") == "-"


def test_format_price():
    assert format_price(12.345) == "12.35"
    assert format_price(None) == "-"


def test_safe_float():
    assert safe_float("3.14") == 3.14
    assert safe_float(None, default=0.0) == 0.0
    assert safe_float("xx", default=-1) == -1


def test_chunked():
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunked([], 3)) == []
