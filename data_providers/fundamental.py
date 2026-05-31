"""基本面数据提供者：PE、ROE 批量获取与缓存。

数据源：东方财富 API
缓存：SQLite (backtest/data/market_data.db)
容错：API 失败时读缓存兜底，完全无缓存则放行（不过滤）
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import requests


_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backtest", "data", "market_data.db"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


class FundamentalDataProvider:
    def __init__(self, cache_db: str = None):
        self.db_path = cache_db or _DEFAULT_DB
        self._ensure_table()
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.proxies = {"http": None, "https": None}

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fundamental_cache (
                stock_code TEXT NOT NULL,
                cache_date TEXT NOT NULL,
                pe_dynamic REAL,
                roe REAL,
                PRIMARY KEY (stock_code, cache_date)
            )
        """)
        conn.commit()
        conn.close()

    # ─── PE：从东方财富全市场行情批量获取 ───

    def fetch_pe_batch(self) -> dict[str, float]:
        """批量拉全市场动态PE，返回 {stock_code: pe}。"""
        today = date.today().isoformat()
        cached = self._load_cache(today, "pe_dynamic")
        if cached:
            return cached

        pe_map = {}
        for page in range(1, 30):
            params = {
                "pn": str(page), "pz": "500", "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2", "fid": "f12",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f9,f12",
            }
            try:
                resp = self._session.get(
                    "http://push2.eastmoney.com/api/qt/clist/get",
                    params=params, headers=_HEADERS, timeout=15
                )
                data = resp.json()
                if data.get("rc") != 0 or not data.get("data"):
                    break
                items = data["data"].get("diff", [])
                if not items:
                    break
                for item in items:
                    code = item.get("f12", "")
                    pe = item.get("f9")
                    if code and pe and pe != "-":
                        try:
                            pe_map[code] = float(pe)
                        except (ValueError, TypeError):
                            pass
            except Exception:
                break

        if pe_map:
            self._save_cache(today, pe_map, "pe_dynamic")
        else:
            pe_map = self._load_cache(None, "pe_dynamic") or {}
        return pe_map

    # ─── ROE：从东方财富财务数据 API 批量获取 ───

    def fetch_roe_batch(self) -> dict[str, float]:
        """批量拉最新ROE（加权），返回 {stock_code: roe%}。"""
        today = date.today().isoformat()
        cached = self._load_cache(today, "roe")
        if cached:
            return cached

        roe_map = {}
        for page in range(1, 20):
            params = {
                "sortColumns": "NOTICE_DATE,SECURITY_CODE",
                "sortTypes": "-1,-1",
                "pageSize": "500",
                "pageNumber": str(page),
                "reportName": "RPT_LICO_FN_CPD",
                "columns": "SECURITY_CODE,WEIGHTAVG_ROE",
                "filter": "(REPORT_TYPE=\"年报\")",
            }
            try:
                resp = self._session.get(
                    "https://datacenter-web.eastmoney.com/api/data/v1/get",
                    params=params, headers=_HEADERS, timeout=20
                )
                data = resp.json()
                if not data.get("success") or not data.get("result"):
                    break
                items = data["result"].get("data", [])
                if not items:
                    break
                for item in items:
                    code = item.get("SECURITY_CODE", "")
                    roe = item.get("WEIGHTAVG_ROE")
                    if code and roe is not None:
                        try:
                            roe_map[code] = float(roe)
                        except (ValueError, TypeError):
                            pass
            except Exception:
                break

        if roe_map:
            self._save_cache(today, roe_map, "roe")
        else:
            roe_map = self._load_cache(None, "roe") or {}
        return roe_map

    # ─── 行业PE中位数 ───

    def get_industry_pe_median(self, pe_data: dict, industry_map: dict) -> dict[str, float]:
        """按行业计算PE中位数，返回 {industry: median_pe}。"""
        industry_pes: dict[str, list] = {}
        for code, pe in pe_data.items():
            if pe <= 0 or pe > 500:
                continue
            ind = industry_map.get(code, "")
            if ind:
                industry_pes.setdefault(ind, []).append(pe)

        return {
            ind: float(np.median(pes))
            for ind, pes in industry_pes.items()
            if len(pes) >= 5
        }

    # ─── 基本面硬过滤 ───

    def apply_fundamental_filter(
        self,
        df: pd.DataFrame,
        pe_data: dict,
        roe_data: dict,
        industry_pe_median: dict,
        industry_map: dict,
        min_roe: float = 8.0,
        pe_mult: float = 1.5,
    ) -> pd.DataFrame:
        """硬过滤：ROE < min_roe 或 PE > 行业中位数 * pe_mult 的票剔除。
        缺数据的放行（fail-open）。"""
        def should_keep(row):
            code = row.get("stock_code", "")
            roe = roe_data.get(code)
            pe = pe_data.get(code)
            industry = industry_map.get(code, "")
            median_pe = industry_pe_median.get(industry)

            if roe is not None and roe < min_roe:
                return False
            if pe is not None and pe > 0 and median_pe and median_pe > 0:
                if pe > median_pe * pe_mult:
                    return False
            return True

        mask = df.apply(should_keep, axis=1)
        return df[mask].reset_index(drop=True)

    # ─── 缓存读写 ───

    def _save_cache(self, cache_date: str, data: dict, field: str):
        conn = sqlite3.connect(self.db_path)
        rows = [(code, cache_date, val if field == "pe_dynamic" else None,
                 val if field == "roe" else None)
                for code, val in data.items()]
        conn.executemany(
            "INSERT OR REPLACE INTO fundamental_cache (stock_code, cache_date, pe_dynamic, roe) "
            "VALUES (?, ?, COALESCE(?, (SELECT pe_dynamic FROM fundamental_cache WHERE stock_code=? AND cache_date=?)), "
            "COALESCE(?, (SELECT roe FROM fundamental_cache WHERE stock_code=? AND cache_date=?)))",
            [(code, cache_date, val if field == "pe_dynamic" else None, code, cache_date,
              val if field == "roe" else None, code, cache_date)
             for code, val in data.items()]
        )
        conn.commit()
        conn.close()

    def _load_cache(self, cache_date: Optional[str], field: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        if cache_date:
            cur = conn.execute(
                f"SELECT stock_code, {field} FROM fundamental_cache WHERE cache_date=? AND {field} IS NOT NULL",
                (cache_date,)
            )
        else:
            cur = conn.execute(
                f"SELECT stock_code, {field} FROM fundamental_cache "
                f"WHERE {field} IS NOT NULL ORDER BY cache_date DESC LIMIT 6000"
            )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return None
        return {r[0]: r[1] for r in rows}
