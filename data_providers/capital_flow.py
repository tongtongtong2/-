"""资金流数据提供者：个股主力资金流 + 北向资金。

数据源：东方财富 API
缓存：SQLite (backtest/data/market_data.db)
容错：API 失败时读缓存兜底
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


class CapitalFlowProvider:
    def __init__(self, cache_db: str = None):
        self.db_path = cache_db or _DEFAULT_DB
        self._ensure_table()
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.proxies = {"http": None, "https": None}

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capital_flow_cache (
                stock_code TEXT NOT NULL,
                cache_date TEXT NOT NULL,
                net_inflow_today REAL,
                net_inflow_pct REAL,
                PRIMARY KEY (stock_code, cache_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS northbound_cache (
                stock_code TEXT NOT NULL,
                cache_date TEXT NOT NULL,
                hold_shares_change REAL,
                hold_ratio_change REAL,
                PRIMARY KEY (stock_code, cache_date)
            )
        """)
        conn.commit()
        conn.close()

    # ─── 个股主力资金流（东方财富批量接口）───

    def fetch_individual_flow_batch(self) -> dict[str, dict]:
        """批量拉全市场个股主力净流入，返回 {code: {net_inflow, net_inflow_pct}}。
        f62=主力净流入(元), f184=主力净流入占比(%)"""
        today = date.today().isoformat()
        cached = self._load_flow_cache(today)
        if cached:
            return cached

        flow_map = {}
        for page in range(1, 30):
            params = {
                "pn": str(page), "pz": "500", "po": "1", "np": "1",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "fltt": "2", "invt": "2", "fid": "f62",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f12,f62,f184",
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
                    inflow = item.get("f62")
                    pct = item.get("f184")
                    if code and inflow is not None:
                        try:
                            flow_map[code] = {
                                "net_inflow": float(inflow),
                                "net_inflow_pct": float(pct) if pct else 0.0,
                            }
                        except (ValueError, TypeError):
                            pass
            except Exception:
                break

        if flow_map:
            self._save_flow_cache(today, flow_map)
        else:
            flow_map = self._load_flow_cache(None) or {}
        return flow_map

    # ─── 北向资金个股持仓变化 ───

    def fetch_northbound_flow(self) -> dict[str, dict]:
        """拉取沪深股通个股持仓变化（近1日增持股数/占比变化）。
        使用东方财富沪深股通持股明细 API。"""
        today = date.today().isoformat()
        cached = self._load_nb_cache(today)
        if cached:
            return cached

        nb_map = {}
        for market in ["001", "003"]:  # 001=沪股通, 003=深股通
            for page in range(1, 10):
                params = {
                    "sortColumns": "ADD_SHARES_AMP",
                    "sortTypes": "-1",
                    "pageSize": "200",
                    "pageNumber": str(page),
                    "reportName": "RPT_MUTUAL_STOCK_NORTHSTA",
                    "columns": "SECURITY_CODE,ADD_SHARES_AMP,HOLD_SHARES_RATIO,CLOSE_PRICE",
                    "filter": f"(MARKET_CODE=\"{market}\")",
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
                        change = item.get("ADD_SHARES_AMP")
                        ratio = item.get("HOLD_SHARES_RATIO")
                        if code and change is not None:
                            try:
                                nb_map[code] = {
                                    "hold_change_pct": float(change),
                                    "hold_ratio": float(ratio) if ratio else 0.0,
                                }
                            except (ValueError, TypeError):
                                pass
                except Exception:
                    break

        if nb_map:
            self._save_nb_cache(today, nb_map)
        else:
            nb_map = self._load_nb_cache(None) or {}
        return nb_map

    # ─── 评分逻辑 ───

    def score_individual_flow(self, flow_data: dict, candidates: list[str]) -> dict[str, float]:
        """对候选股的个股资金流打分 0-100。
        逻辑：主力净流入占比排名 → 百分位分数。"""
        if not flow_data:
            return {c: 50.0 for c in candidates}

        scores = {}
        pcts = []
        for code in candidates:
            info = flow_data.get(code)
            pct = info["net_inflow_pct"] if info else 0.0
            pcts.append((code, pct))

        if not pcts:
            return {c: 50.0 for c in candidates}

        pcts.sort(key=lambda x: x[1])
        n = len(pcts)
        for rank, (code, _) in enumerate(pcts):
            scores[code] = (rank / max(n - 1, 1)) * 100.0

        return scores

    def score_northbound(self, nb_data: dict, candidates: list[str]) -> dict[str, float]:
        """对候选股的北向资金打分 0-100。
        逻辑：持仓增幅排名 → 百分位分数。有北向持仓的加分，无持仓给中性分。"""
        if not nb_data:
            return {c: 50.0 for c in candidates}

        items = []
        for code in candidates:
            info = nb_data.get(code)
            change = info["hold_change_pct"] if info else -999
            items.append((code, change))

        items.sort(key=lambda x: x[1])
        n = len(items)
        scores = {}
        for rank, (code, change) in enumerate(items):
            if change == -999:
                scores[code] = 40.0  # 无北向持仓，略低于中性
            else:
                scores[code] = (rank / max(n - 1, 1)) * 100.0

        return scores

    # ─── 缓存读写 ───

    def _save_flow_cache(self, cache_date: str, data: dict):
        conn = sqlite3.connect(self.db_path)
        rows = [(code, cache_date, info["net_inflow"], info["net_inflow_pct"])
                for code, info in data.items()]
        conn.executemany(
            "INSERT OR REPLACE INTO capital_flow_cache VALUES (?, ?, ?, ?)", rows
        )
        conn.commit()
        conn.close()

    def _load_flow_cache(self, cache_date: Optional[str]) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        if cache_date:
            cur = conn.execute(
                "SELECT stock_code, net_inflow_today, net_inflow_pct FROM capital_flow_cache WHERE cache_date=?",
                (cache_date,)
            )
        else:
            cur = conn.execute(
                "SELECT stock_code, net_inflow_today, net_inflow_pct FROM capital_flow_cache "
                "ORDER BY cache_date DESC LIMIT 6000"
            )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return None
        return {r[0]: {"net_inflow": r[1], "net_inflow_pct": r[2]} for r in rows}

    def _save_nb_cache(self, cache_date: str, data: dict):
        conn = sqlite3.connect(self.db_path)
        rows = [(code, cache_date, info["hold_change_pct"], info["hold_ratio"])
                for code, info in data.items()]
        conn.executemany(
            "INSERT OR REPLACE INTO northbound_cache VALUES (?, ?, ?, ?)", rows
        )
        conn.commit()
        conn.close()

    def _load_nb_cache(self, cache_date: Optional[str]) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        if cache_date:
            cur = conn.execute(
                "SELECT stock_code, hold_shares_change, hold_ratio_change FROM northbound_cache WHERE cache_date=?",
                (cache_date,)
            )
        else:
            cur = conn.execute(
                "SELECT stock_code, hold_shares_change, hold_ratio_change FROM northbound_cache "
                "ORDER BY cache_date DESC LIMIT 3000"
            )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return None
        return {r[0]: {"hold_change_pct": r[1], "hold_ratio": r[2]} for r in rows}
