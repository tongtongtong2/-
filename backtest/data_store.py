"""本地历史数据存储（SQLite）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).parent / "data" / "market_data.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_bars (
            stock_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (stock_code, trade_date)
        );
        CREATE TABLE IF NOT EXISTS stock_info (
            stock_code TEXT PRIMARY KEY,
            stock_name TEXT,
            board TEXT
        );
        CREATE TABLE IF NOT EXISTS index_daily (
            trade_date TEXT PRIMARY KEY,
            close REAL
        );
    """)
    conn.close()


class DataStore:
    def __init__(self):
        init_db()
        self._conn = get_conn()

    def close(self):
        self._conn.close()

    def insert_daily_bars(self, df: pd.DataFrame):
        if df.empty:
            return
        df.to_sql("daily_bars", self._conn, if_exists="append", index=False,
                  method="multi", chunksize=500)

    def upsert_daily_bars(self, df: pd.DataFrame):
        if df.empty:
            return
        cur = self._conn.cursor()
        for _, row in df.iterrows():
            cur.execute("""
                INSERT OR REPLACE INTO daily_bars
                (stock_code, trade_date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (row["stock_code"], row["trade_date"],
                  row.get("open"), row.get("high"), row.get("low"),
                  row.get("close"), row.get("volume")))
        self._conn.commit()

    def upsert_stock_info(self, code: str, name: str, board: str = ""):
        self._conn.execute("""
            INSERT OR REPLACE INTO stock_info (stock_code, stock_name, board)
            VALUES (?, ?, ?)
        """, (code, name, board))
        self._conn.commit()

    def upsert_index_daily(self, df: pd.DataFrame):
        if df.empty:
            return
        cur = self._conn.cursor()
        for _, row in df.iterrows():
            cur.execute("""
                INSERT OR REPLACE INTO index_daily (trade_date, close)
                VALUES (?, ?)
            """, (row["trade_date"], row["close"]))
        self._conn.commit()

    def get_daily(self, code: str, end_date: str, days: int = 120) -> pd.DataFrame:
        df = pd.read_sql_query("""
            SELECT * FROM daily_bars
            WHERE stock_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, self._conn, params=(code, end_date, days))
        if df.empty:
            return df
        return df.sort_values("trade_date").reset_index(drop=True)

    def get_all_codes(self) -> list[str]:
        cur = self._conn.execute("SELECT DISTINCT stock_code FROM daily_bars")
        return [r[0] for r in cur.fetchall()]

    def get_trade_dates(self, start: str, end: str) -> list[str]:
        cur = self._conn.execute("""
            SELECT DISTINCT trade_date FROM daily_bars
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """, (start, end))
        return [r[0] for r in cur.fetchall()]

    def get_spot_on_date(self, trade_date: str) -> pd.DataFrame:
        """用日线数据模拟当日 spot 行情。"""
        df = pd.read_sql_query("""
            SELECT stock_code, trade_date, open, high, low, close, volume
            FROM daily_bars WHERE trade_date = ?
        """, self._conn, params=(trade_date,))
        if df.empty:
            return df
        # 需要前一日收盘价算涨跌幅
        prev_date = self._get_prev_trade_date(trade_date)
        if prev_date:
            prev = pd.read_sql_query("""
                SELECT stock_code, close as prev_close
                FROM daily_bars WHERE trade_date = ?
            """, self._conn, params=(prev_date,))
            df = df.merge(prev, on="stock_code", how="left")
            df["change_percent"] = ((df["close"] - df["prev_close"]) / df["prev_close"] * 100).fillna(0)
        else:
            df["change_percent"] = 0.0
        df["turnover"] = df["close"] * df["volume"]
        # 加股票名称
        info = pd.read_sql_query("SELECT stock_code, stock_name FROM stock_info", self._conn)
        df = df.merge(info, on="stock_code", how="left")
        df["stock_name"] = df["stock_name"].fillna("")
        return df

    def get_index_daily(self, start: str, end: str) -> pd.DataFrame:
        return pd.read_sql_query("""
            SELECT * FROM index_daily
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """, self._conn, params=(start, end))

    def get_bar(self, code: str, trade_date: str) -> Optional[dict]:
        cur = self._conn.execute("""
            SELECT open, high, low, close, volume FROM daily_bars
            WHERE stock_code = ? AND trade_date = ?
        """, (code, trade_date))
        row = cur.fetchone()
        if row is None:
            return None
        return {"open": row[0], "high": row[1], "low": row[2],
                "close": row[3], "volume": row[4]}

    def _get_prev_trade_date(self, trade_date: str) -> Optional[str]:
        cur = self._conn.execute("""
            SELECT trade_date FROM daily_bars
            WHERE trade_date < ?
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT 1
        """, (trade_date,))
        row = cur.fetchone()
        return row[0] if row else None

    def get_moneyflow(self, code: str, end_date: str, days: int = 5):
        """Get recent moneyflow data for a stock."""
        try:
            df = pd.read_sql_query(
                """SELECT net_mf_amount FROM moneyflow
                   WHERE ts_code LIKE ? AND trade_date <= ?
                   ORDER BY trade_date DESC LIMIT ?""",
                self._conn, params=(f"{code}.%", end_date, days))
            return df
        except:
            return None

    def count_bars(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM daily_bars")
        return cur.fetchone()[0]

    def count_stocks(self) -> int:
        cur = self._conn.execute("SELECT COUNT(DISTINCT stock_code) FROM daily_bars")
        return cur.fetchone()[0]
    def get_industry(self, code: str) -> str:
        """Get industry classification for a stock."""
        try:
            cur = self._conn.execute(
                "SELECT industry FROM stock_info_new WHERE stock_code=?",
                (code,))
            row = cur.fetchone()
            return row[0] if row else ""
        except:
            return ""
