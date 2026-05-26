"""AkShare 数据访问层。封装 A 股列表、历史日线、实时行情、交易日。

使用 AkShare 公开免费接口，自动重试与轻量缓存。"""
from __future__ import annotations

import os
import random
import socket
import threading
import time

# 兜底：本模块导入即清掉代理变量（run.py 已清，但 init_db.py / pytest / REPL 可能未清）。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

# 设置 socket 级超时作为最后的兜底
socket.setdefaulttimeout(60)

from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd
import requests

from app.utils import get_logger, retry
from config import Config

logger = get_logger(__name__)

# 东方财富全市场行情 API 配置
# 东方财富有多个 push2 分流子域，单一域名常被运营商/中间设备 RST，需轮询备用
_SPOT_HOSTS = [
    "82.push2.eastmoney.com",
    "push2.eastmoney.com",
    "1.push2.eastmoney.com",
    "2.push2.eastmoney.com",
    "19.push2.eastmoney.com",
    "29.push2.eastmoney.com",
    "48.push2.eastmoney.com",
    "76.push2.eastmoney.com",
]
_SPOT_PATH = "/api/qt/clist/get"
_SPOT_PARAMS = {
    "pn": "1",
    "pz": "200",
    "po": "1",
    "np": "1",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2",
    "invt": "2",
    "fid": "f12",
    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21",
}
_SPOT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
    "Connection": "close",
}

# 东方财富字段 → DataFrame 列名
_SPOT_FIELD_MAP = {
    "f1": "index",
    "f2": "最新价",
    "f3": "涨跌幅",
    "f4": "涨跌额",
    "f5": "成交量",
    "f6": "成交额",
    "f7": "振幅",
    "f8": "换手率",
    "f9": "市盈率-动态",
    "f10": "量比",
    "f12": "代码",
    "f14": "名称",
    "f15": "最高",
    "f16": "最低",
    "f17": "今开",
    "f18": "昨收",
    "f20": "总市值",
    "f21": "流通市值",
    "f100": "行业",
}


# 新浪财经全市场行情（东方财富整网不可达时作为兜底）
_SINA_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
_SINA_WARMUP_URL = "https://vip.stock.finance.sina.com.cn/mkt/"
# 实测 hs_a 节点已覆盖沪深主板+创业板+科创板+北交所（symbol 含 sh/sz/bj）
_SINA_NODES = ("hs_a",)
# 新浪 num 最大 100，传更大值会被截断为 100
_SINA_PAGE_SIZE = 100
_SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://vip.stock.finance.sina.com.cn/mkt/",
    "Connection": "close",
}


# 新浪日线接口（个股 K 线），module 级 Session 复用避免每次握手
_SINA_HIST_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/data/CN_MarketDataService.getKLineData"
_SINA_HIST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}
_sina_hist_session: Optional[requests.Session] = None
_sina_hist_session_lock = threading.Lock()


def _get_sina_hist_session() -> requests.Session:
    global _sina_hist_session
    if _sina_hist_session is not None:
        return _sina_hist_session
    with _sina_hist_session_lock:
        if _sina_hist_session is None:
            from requests.adapters import HTTPAdapter
            sess = requests.Session()
            sess.trust_env = False
            sess.proxies = {"http": None, "https": None}
            sess.headers.update(_SINA_HIST_HEADERS)
            adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
            _sina_hist_session = sess
    return _sina_hist_session


def _to_ymd(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "").replace("/", "")[:8]


class DataFetcher:
    """对 AkShare 的薄封装，统一返回 pandas DataFrame。"""

    def __init__(self):
        self._spot_cache: Optional[pd.DataFrame] = None
        self._spot_cache_at: Optional[date] = None
        self._hist_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._last_good_host: Optional[str] = None
        self._akshare_ok: bool = True  # 一次失败即置 False，后续全走 Sina

    # ------------------------------------------------------------------
    # A 股列表 + 实时
    # ------------------------------------------------------------------
    def _fetch_spot(self) -> pd.DataFrame:
        """直接请求东方财富行情 API，逐页拉取全市场 A 股实时数据。

        失败排查覆盖：
        - 系统代理 / VPN：清环境变量 + session.trust_env=False + proxies=None
        - 单一子域被 RST：在 _SPOT_HOSTS 中轮询备用域名
        - HTTPS 被中间设备劫持：先试 https，再回落 http
        - 偶发性 RemoteDisconnected：HTTPAdapter 内置重试 + 短连接
        """
        if Config.SPOT_SOURCE == "sina":
            logger.info("SPOT_SOURCE=sina，直接走新浪行情兜底")
            return self._fetch_spot_sina()

        import urllib.request
        from requests.adapters import HTTPAdapter
        try:
            from urllib3.util.retry import Retry
        except ImportError:  # 极端兼容
            from requests.packages.urllib3.util.retry import Retry  # type: ignore

        sys_proxies = urllib.request.getproxies()
        if any(v for v in sys_proxies.values() if v):
            logger.warning("检测到系统代理: %s，已强制绕过", sys_proxies)

        session = requests.Session()
        session.headers.update(_SPOT_HEADERS)
        session.trust_env = False
        session.proxies = {"http": None, "https": None}

        retry_cfg = Retry(
            total=0,
            connect=0,
            read=0,
            backoff_factor=0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_cfg, pool_connections=4, pool_maxsize=4)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # 先做一次最快的探测：单 host 1 秒超时，失败立刻走兜底，不再拖时间
        probe_url = f"https://{_SPOT_HOSTS[0]}{_SPOT_PATH}"
        try:
            session.get(probe_url, params={**_SPOT_PARAMS, "pn": "1", "pz": "1"}, timeout=(2, 3))
        except Exception as exc:  # noqa: BLE001
            logger.warning("东方财富探测失败，直接走新浪兜底: %s", exc)
            session.close()
            return self._fetch_spot_sina()

        # 先访问东方财富首页，建立合法的 Cookie 会话（失败不致命，超短超时）
        for home in ("https://quote.eastmoney.com/", "http://quote.eastmoney.com/"):
            try:
                home_resp = session.get(home, timeout=5)
                logger.info(
                    "首页会话建立: status=%d, cookies=%d (%s)",
                    home_resp.status_code,
                    len(session.cookies),
                    home,
                )
                if home_resp.status_code < 500:
                    break
            except Exception as _e:
                logger.warning("首页访问失败（非致命）: %s", _e)

        # 先试一页东方财富，整网不可达直接走新浪兜底（避免每页都重试浪费时间）
        params = _SPOT_PARAMS.copy()
        params["pn"] = "1"
        try:
            first_page = self._request_spot_page(session, params)
        except Exception as exc:  # noqa: BLE001
            session.close()
            logger.warning("东方财富行情整网不可达，回落到新浪财经: %s", exc)
            return self._fetch_spot_sina()

        all_rows: list[dict] = list(first_page or [])
        try:
            if all_rows and len(all_rows) >= int(params["pz"]):
                page = 2
                while True:
                    params["pn"] = str(page)
                    page_data = self._request_spot_page(session, params)
                    if not page_data:
                        break
                    all_rows.extend(page_data)
                    if len(page_data) < int(params["pz"]):
                        break
                    page += 1
                    time.sleep(random.uniform(0.2, 0.5))
        finally:
            session.close()

        if not all_rows:
            raise RuntimeError("东方财富返回空的 A 股实时数据")

        df = pd.DataFrame(all_rows)
        df.rename(columns=_SPOT_FIELD_MAP, inplace=True)
        # 东方财富有时只返回北交所股票（92xxxx），缺沪深主板则回退到新浪
        if "代码" in df.columns:
            codes = df["代码"].astype(str)
            valid = codes.str.startswith(("60", "00", "30"))
            if valid.sum() == 0:
                logger.warning("东方财富未返回沪深主板股票（仅 %d 条），回退到新浪财经", len(df))
                return self._fetch_spot_sina()
        return df

    def _fetch_spot_sina(self) -> pd.DataFrame:
        """使用新浪财经接口拉取沪深 A 股 + 科创板 + 北交所列表（东方财富不可用时的兜底）。

        实测 num 最多 100 条/页，全市场约 5500+ 行。
        策略：先串行第 1 页确认节点有数据，然后用一个并发池滑动拉后续页，
        遇到连续 N 个空页或不足页 (last page) 即停。每页失败本地重试 1 次，
        避免一批被最慢页拖。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        sess = requests.Session()
        sess.headers.update(_SINA_HEADERS)
        sess.trust_env = False
        sess.proxies = {"http": None, "https": None}

        # 预热：访问行情主页拿 cookie，避免被风控直接 456
        try:
            sess.get(_SINA_WARMUP_URL, timeout=(3, 5))
        except Exception as exc:  # noqa: BLE001
            logger.debug("新浪预热失败（非致命）: %s", exc)

        def fetch_page(node: str, page: int) -> list[dict]:
            params = {
                "page": str(page),
                "num": str(_SINA_PAGE_SIZE),
                "sort": "symbol",
                "asc": "1",
                "node": node,
                "_s_r_a": "page",
            }
            last_exc: Optional[BaseException] = None
            for _ in range(2):  # 1 次正常 + 1 次重试
                try:
                    resp = sess.get(_SINA_URL, params=params, timeout=(5, 12))
                    resp.raise_for_status()
                    return resp.json() or []
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            assert last_exc is not None
            raise last_exc

        all_rows: list[dict] = []
        try:
            for node in _SINA_NODES:
                # 第 1 页串行（探明该节点是否有数据）
                first = fetch_page(node, 1)
                if not first:
                    continue
                all_rows.extend(first)
                if len(first) < _SINA_PAGE_SIZE:
                    continue

                # 后续并发拉：每次同时投递 16 页，按页号顺序消费结果，
                # 遇到不足页/空页判断结束
                workers = 16
                batch_size = 16
                page = 2
                done = False
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    while not done:
                        batch_pages = list(range(page, page + batch_size))
                        futs = {pool.submit(fetch_page, node, p): p for p in batch_pages}
                        results: dict[int, list[dict] | None] = {}
                        for fut in as_completed(futs):
                            p = futs[fut]
                            try:
                                results[p] = fut.result()
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("新浪行情拉取失败 node=%s page=%d: %s", node, p, exc)
                                results[p] = None
                        # 按页号顺序消费，决定是否结束
                        for p in batch_pages:
                            rows = results.get(p)
                            if rows is None:
                                continue
                            if not rows:
                                done = True
                                break
                            all_rows.extend(rows)
                            if len(rows) < _SINA_PAGE_SIZE:
                                done = True
                                break
                        page += batch_size
        finally:
            sess.close()

        if not all_rows:
            raise RuntimeError("新浪财经返回空的 A 股实时数据")

        df = pd.DataFrame(all_rows)
        # 新浪字段 → 统一中文列名（与东方财富兼容）
        sina_map = {
            "code": "代码",
            "name": "名称",
            "trade": "最新价",
            "changepercent": "涨跌幅",
            "pricechange": "涨跌额",
            "volume": "成交量",
            "amount": "成交额",
            "open": "今开",
            "high": "最高",
            "low": "最低",
            "settlement": "昨收",
            "per": "市盈率-动态",
            "turnoverratio": "换手率",
            "mktcap": "总市值",
            "nmc": "流通市值",
        }
        df = df.rename(columns=sina_map)
        # 盘前 trade 可能为 0，回退到昨收 (settlement)
        if "最新价" in df.columns and "昨收" in df.columns:
            df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")
            settle_series = pd.to_numeric(df["昨收"], errors="coerce")
            mask = df["最新价"].fillna(0) <= 0
            df.loc[mask, "最新价"] = settle_series[mask]
        # 新浪 mktcap/nmc 单位是「万元」，转成「元」
        for col in ("总市值", "流通市值"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce") * 10000
        return df

    @retry(times=2, delay=1)
    def _request_spot_page(self, session: requests.Session, params: dict) -> list[dict]:
        """请求单页行情数据：依次尝试 https/http × 多个子域，命中即返回。"""
        last_exc: Optional[BaseException] = None
        # 把上次成功的 host 放到首位以保证局部稳定
        hosts = list(_SPOT_HOSTS)
        if self._last_good_host and self._last_good_host in hosts:
            hosts.remove(self._last_good_host)
            hosts.insert(0, self._last_good_host)

        for scheme in ("https", "http"):
            for host in hosts:
                url = f"{scheme}://{host}{_SPOT_PATH}"
                try:
                    resp = session.get(url, params=params, timeout=(5, 15))
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("data") is None:
                        # 接口偶尔 data=null，换 host 再试
                        last_exc = RuntimeError(f"data=null from {host}")
                        continue
                    diff = data["data"].get("diff") or []
                    self._last_good_host = host
                    return diff  # type: ignore[return-value]
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.debug("行情节点失败 %s://%s: %s", scheme, host, exc)
                    continue

        assert last_exc is not None
        raise last_exc

    def get_stock_spot(self, force_refresh: bool = False) -> pd.DataFrame:
        """获取沪深 A 股实时行情（含名称、代码、最新价、成交额等）。当日缓存。"""
        today = date.today()
        if (
            not force_refresh
            and self._spot_cache is not None
            and self._spot_cache_at == today
        ):
            return self._spot_cache.copy()

        df = self._fetch_spot()
        df = df.copy()

        rename_map = {
            "代码": "stock_code",
            "名称": "stock_name",
            "最新价": "current_price",
            "涨跌幅": "change_percent",
            "成交量": "volume",
            "成交额": "turnover",
            "总市值": "market_cap",
            "流通市值": "float_market_cap",
        }
        for src, dst in rename_map.items():
            if src in df.columns:
                df[dst] = df[src]

        if "stock_code" not in df.columns and "code" in df.columns:
            df["stock_code"] = df["code"].astype(str)
        if "stock_name" not in df.columns and "name" in df.columns:
            df["stock_name"] = df["name"].astype(str)

        df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)

        for col in ("current_price", "change_percent", "volume", "turnover"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self._spot_cache = df
        self._spot_cache_at = today
        return df.copy()

    def get_stock_list(self) -> pd.DataFrame:
        """返回 A 股列表（code, name）。"""
        spot = self.get_stock_spot()
        cols = [c for c in ("stock_code", "stock_name") if c in spot.columns]
        return spot[cols].drop_duplicates().reset_index(drop=True)

    # ------------------------------------------------------------------
    # 历史日线
    # ------------------------------------------------------------------
    def _fetch_hist_akshare(self, stock_code: str, start: str, end: str) -> pd.DataFrame:
        """akshare 单次调用（不放重试，由上层 fallback 处理）。"""
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def _sina_symbol(stock_code: str) -> str:
        """将 6 位代码转为新浪 symbol 格式：sh600519 / sz000001 / bj920000。"""
        code = str(stock_code).zfill(6)
        if code.startswith(("60", "68")):
            return "sh" + code
        elif code.startswith(("00", "30")):
            return "sz" + code
        elif code.startswith("8") or code.startswith("4"):
            return "bj" + code
        else:
            return "sh" + code

    def _fetch_hist_sina(self, stock_code: str, datalen: int = 200) -> pd.DataFrame:
        """从新浪财经拉取个股日线数据，作为东方财富不可用时的备选。"""
        import json as _json
        import re

        symbol = self._sina_symbol(stock_code)
        params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)}
        sess = _get_sina_hist_session()
        try:
            resp = sess.get(_SINA_HIST_URL, params=params, timeout=(5, 15))
            resp.raise_for_status()
            # JSONP 格式: data([{...}, ...])
            text = resp.text
            match = re.search(r"data\((.+)\)", text, re.DOTALL)
            if not match:
                logger.warning("新浪日线返回非预期格式: %s", text[:100])
                return pd.DataFrame()
            rows = _json.loads(match.group(1))
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            df = df.rename(columns={
                "day": "trade_date",
                "open": "open",
                "close": "close",
                "high": "high",
                "low": "low",
                "volume": "volume",
            })
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            for col in ("open", "close", "high", "low", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            # 计算涨跌幅：(当日收盘 - 前日收盘) / 前日收盘
            if "close" in df.columns and len(df) > 1:
                df["change_percent"] = df["close"].pct_change()
            return df.sort_values("trade_date").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("新浪日线抓取失败 %s: %s", stock_code, exc)
            return pd.DataFrame()

    def get_stock_daily(
        self,
        stock_code: str,
        start_date,
        end_date=None,
    ) -> pd.DataFrame:
        """获取个股前复权日线数据。返回列：trade_date, open, close, high, low, volume, turnover, change_percent"""
        end_date = end_date or date.today()
        start = _to_ymd(start_date)
        end = _to_ymd(end_date)

        cache_key = (stock_code, start, end)
        if cache_key in self._hist_cache:
            return self._hist_cache[cache_key].copy()

        raw = pd.DataFrame()
        # 先试 akshare（东方财富），失败立刻走新浪；一次失败后续全跳过
        if self._akshare_ok:
            try:
                raw = self._fetch_hist_akshare(stock_code, start, end)
            except Exception as exc:  # noqa: BLE001
                logger.debug("akshare 日线失败 %s: %s，后续全走新浪", stock_code, exc)
                self._akshare_ok = False
                raw = pd.DataFrame()
        else:
            raw = pd.DataFrame()

        # 东方财富不可用时回退到新浪
        if raw is None or raw.empty:
            logger.info("改用新浪获取 %s 日线", stock_code)
            raw = self._fetch_hist_sina(stock_code, datalen=200)

        if raw is None or raw.empty:
            return pd.DataFrame()

        rename_map = {
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "turnover",
            "涨跌幅": "change_percent",
            "换手率": "turnover_rate",
        }
        df = raw.rename(columns=rename_map).copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        for col in ("open", "close", "high", "low", "volume", "turnover", "change_percent"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.sort_values("trade_date").reset_index(drop=True)
        self._hist_cache[cache_key] = df
        return df.copy()

    def get_recent_daily(self, stock_code: str, days: int = 60) -> pd.DataFrame:
        """获取最近 N 个自然日内的日线数据（足够覆盖 60 个交易日，调用方按需截尾）。"""
        end = date.today()
        start = end - timedelta(days=int(days * 1.7) + 10)
        return self.get_stock_daily(stock_code, start, end)

    # ------------------------------------------------------------------
    # 实时单价
    # ------------------------------------------------------------------
    def get_realtime_prices(self, stock_codes: List[str]) -> pd.DataFrame:
        """根据 spot 表筛出指定代码的最新行情。"""
        if not stock_codes:
            return pd.DataFrame()
        spot = self.get_stock_spot()
        codes = {str(c).zfill(6) for c in stock_codes}
        return spot[spot["stock_code"].isin(codes)].copy()

    # ------------------------------------------------------------------
    # 交易日
    # ------------------------------------------------------------------
    @retry(times=2, delay=1)
    def get_trade_calendar(self) -> pd.DataFrame:
        import akshare as ak
        return ak.tool_trade_date_hist_sina()


_default_fetcher: Optional[DataFetcher] = None


def get_default_fetcher() -> DataFetcher:
    """全局共享一个 DataFetcher 实例以复用缓存。"""
    global _default_fetcher
    if _default_fetcher is None:
        _default_fetcher = DataFetcher()
    return _default_fetcher
