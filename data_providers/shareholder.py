"""股东人数数据提供者：筹码集中度信号。

数据源：东方财富股东人数 API
缓存：SQLite (backtest/data/market_data.db)
容错：API 失败时读缓存兜底
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from typing import Optional

import requests


_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backtest", "data", "market_data.db"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


class ShareholderDataProvider:
    def __init__(self, cache_db: str = None):
        self.db_path = cache_db or _DEFAULT_DB
        self._ensure_table()
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.proxies = {"http": None, "https": None}

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shareholder_cache (
                stock_code TEXT NOT NULL,
                cache_date TEXT NOT NULL,
                holder_num INTEGER,
                holder_change_pct REAL,
                consecutive_decrease INTEGER DEFAULT 0,
                PRIMARY KEY (stock_code, cache_date)
            )
        """)
        conn.commit()
        conn.close()

    def fetch_shareholder_data(self) -> dict[str, dict]:
        """批量拉取股东人数变化数据，返回 {code: {holder_num, change_pct, consecutive_decrease}}。"""
        today = date.today().isoformat()
        cached = self._load_cache(today)
        if cached:
            return cached

        holder_map = {}
        for page in range(1, 20):
            params = {
                "sortColumns": "HOLDER_NUM",
                "sortTypes": "1",
                "pageSize": "500",
                "pageNumber": str(page),
                "reportName": "RPT_HOLDERNUM_DET",
                "columns": "SECURITY_CODE,HOLDER_NUM,HOLDER_NUM_CHANGE_RATE,HOLDER_NUM_CHANGE",
                "filter": "",
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
                    num = item.get("HOLDER_NUM")
                    change_rate = item.get("HOLDER_NUM_CHANGE_RATE")
                    if code and num is not None:
                        try:
                            holder_map[code] = {
                                "holder_num": int(num),
                                "change_pct": float(change_rate) if change_rate else 0.0,
                            }
                        except (ValueError, TypeError):
                            pass
            except Exception:
                break

        # 计算连续减少期数（基于变化率符号）
        for code, info in holder_map.items():
            if info["change_pct"] < 0:
                prev = self._get_prev_consecutive(code)
                info["consecutive_decrease"] = prev + 1
            else:
                info["consecutive_decrease"] = 0

        if holder_map:
            self._save_cache(today, holder_map)
        else:
            holder_map = self._load_cache(None) or {}
        return holder_map

    def compute_bonus(self, holder_data: dict, candidates: list[str]) -> dict[str, float]:
        """计算股东人数加分，返回 {code: bonus_points}。
        连续1期减少: +3, 2期: +6, 3期+: +10"""
        if not holder_data:
            return {c: 0.0 for c in candidates}

        scores = {}
        for code in candidates:
            info = holder_data.get(code)
            if not info:
                scores[code] = 0.0
                continue
            consec = info.get("consecutive_decrease", 0)
            if consec >= 3:
                scores[code] = 10.0
            elif consec == 2:
                scores[code] = 6.0
            elif consec == 1:
                scores[code] = 3.0
            else:
                scores[code] = 0.0
        return scores

    # ─── 缓存读写 ───

    def _get_prev_consecutive(self, code: str) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT consecutive_decrease FROM shareholder_cache "
            "WHERE stock_code=? ORDER BY cache_date DESC LIMIT 1",
            (code,)
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 0

    def _save_cache(self, cache_date: str, data: dict):
        conn = sqlite3.connect(self.db_path)
        rows = [(code, cache_date, info["holder_num"], info["change_pct"],
                 info.get("consecutive_decrease", 0))
                for code, info in data.items()]
        conn.executemany(
            "INSERT OR REPLACE INTO shareholder_cache VALUES (?, ?, ?, ?, ?)", rows
        )
        conn.commit()
        conn.close()

    def _load_cache(self, cache_date: Optional[str]) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        if cache_date:
            cur = conn.execute(
                "SELECT stock_code, holder_num, holder_change_pct, consecutive_decrease "
                "FROM shareholder_cache WHERE cache_date=?",
                (cache_date,)
            )
        else:
            cur = conn.execute(
                "SELECT stock_code, holder_num, holder_change_pct, consecutive_decrease "
                "FROM shareholder_cache ORDER BY cache_date DESC LIMIT 6000"
            )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return None
        return {
            r[0]: {"holder_num": r[1], "change_pct": r[2], "consecutive_decrease": r[3]}
            for r in rows
        }
