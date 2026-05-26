"""通用工具：日志、交易日、重试装饰器、格式化辅助。"""
from __future__ import annotations

import functools
import logging
import os
import random
import time
from datetime import date, datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Callable, Iterable, Optional

from config import Config


_LOG_INITIALIZED = False
_TRADING_DAYS_CACHE: Optional[set[str]] = None
_TRADING_DAYS_CACHE_AT: Optional[date] = None


def setup_logger(name: str = "app") -> logging.Logger:
    """初始化全局日志，按日轮转，保留 30 天。多次调用幂等。"""
    global _LOG_INITIALIZED

    logger = logging.getLogger(name)
    if _LOG_INITIALIZED:
        return logger

    logger.setLevel(getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    os.makedirs(Config.LOG_DIR, exist_ok=True)
    log_path = os.path.join(Config.LOG_DIR, Config.LOG_FILE)

    file_handler = TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logger.level)
    if not any(isinstance(h, TimedRotatingFileHandler) for h in root.handlers):
        root.addHandler(file_handler)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, TimedRotatingFileHandler) for h in root.handlers):
        root.addHandler(stream_handler)

    _LOG_INITIALIZED = True
    return logger


def get_logger(name: str) -> logging.Logger:
    """模块级 logger 获取入口。"""
    setup_logger()
    return logging.getLogger(name)


def retry(times: int = 3, delay: float = 1.0, exceptions: tuple = (Exception,)):
    """重试装饰器：指数退避 + 随机抖动，最多 times 次。
    delay 默认 1s，避免一次失败就把请求拖到 5+s。
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            last_exc: Optional[BaseException] = None
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning(
                        "%s 第 %d/%d 次调用失败: %s",
                        func.__name__, attempt, times, exc,
                    )
                    if attempt < times:
                        backoff = delay * (2 ** (attempt - 1))
                        jitter = random.uniform(0, delay)
                        time.sleep(backoff + jitter)
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator


def _normalize_date(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value.replace("/", "-")[:10]
    raise TypeError(f"unsupported date value: {value!r}")


def _load_trading_days() -> set[str]:
    """从 akshare 加载交易日历，整日缓存。失败时返回空集合。"""
    global _TRADING_DAYS_CACHE, _TRADING_DAYS_CACHE_AT
    today = date.today()
    if _TRADING_DAYS_CACHE is not None and _TRADING_DAYS_CACHE_AT == today:
        return _TRADING_DAYS_CACHE

    logger = get_logger(__name__)
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        days = {_normalize_date(d) for d in df["trade_date"].tolist()}
        _TRADING_DAYS_CACHE = days
        _TRADING_DAYS_CACHE_AT = today
        return days
    except Exception as exc:  # noqa: BLE001
        logger.error("加载交易日历失败：%s", exc)
        return _TRADING_DAYS_CACHE or set()


def is_trading_day(d=None) -> bool:
    """判断给定日期是否为 A 股交易日；默认今天。"""
    target = _normalize_date(d) if d is not None else date.today().strftime("%Y-%m-%d")
    days = _load_trading_days()
    if not days:
        weekday = datetime.strptime(target, "%Y-%m-%d").weekday()
        return weekday < 5
    return target in days


def format_pct(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def format_price(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def safe_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def chunked(iterable: Iterable, size: int):
    bucket: list = []
    for item in iterable:
        bucket.append(item)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket
