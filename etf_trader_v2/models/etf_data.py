"""ETFDataRepo — 所有ETF数据相关的数据库查询"""
from collections import defaultdict
from typing import Optional

import numpy as np

import db
from config import POOL


class ETFDataRepo:
    """ETF数据仓库 — 封装所有数据库查询"""

    def latest_date(self) -> Optional[str]:
        """获取最新数据日期"""
        with db.connect() as conn:
            row = conn.execute("SELECT MAX(date) FROM etf_quotes").fetchone()
            if row and row[0]:
                return str(row[0])
            return None

    def get_quotes(self, code: str, lookback: int = 100) -> list[dict]:
        """获取单只ETF的OHLCV数据

        Args:
            code: ETF代码
            lookback: 回看天数

        Returns:
            [{'date', 'open', 'high', 'low', 'close', 'volume'}, ...]
        """
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT date, open, high, low, close, volume
                   FROM etf_quotes
                   WHERE code = ?
                   ORDER BY date DESC
                   LIMIT ?""",
                (code, lookback),
            ).fetchall()

        # 按日期升序返回
        result = [
            {
                'date': r['date'],
                'open': float(r['open']),
                'high': float(r['high']),
                'low': float(r['low']),
                'close': float(r['close']),
                'volume': float(r['volume']),
            }
            for r in reversed(rows)
        ]
        return result

    def get_all_quotes(self, lookback: int = 66) -> dict[str, list[dict]]:
        """获取所有ETF的行情数据

        Args:
            lookback: 回看天数

        Returns:
            {code: [{...}, ...], ...}
        """
        codes = list(POOL.keys())
        if not codes:
            return {}

        with db.connect() as conn:
            ph = ','.join(['?'] * len(codes))

            # 先获取最新日期
            latest_row = conn.execute("SELECT MAX(date) FROM etf_quotes").fetchone()
            if not latest_row or not latest_row[0]:
                return {}

            latest = latest_row[0]

            rows = conn.execute(
                f"""SELECT code, date, high, low, close, volume
                    FROM etf_quotes
                    WHERE code IN ({ph})
                    AND date >= date(?, '-{lookback + 10} days')
                    ORDER BY code, date""",
                codes + [latest],
            ).fetchall()

        quotes = defaultdict(list)
        for r in rows:
            quotes[r['code']].append({
                'date': r['date'],
                'high': float(r['high']),
                'low': float(r['low']),
                'close': float(r['close']),
                'volume': float(r['volume']),
            })

        return dict(quotes)

    def get_quotes_for_codes(self, codes: list[str], lookback: int = 66) -> dict[str, list[dict]]:
        """获取指定ETF列表的行情数据"""
        if not codes:
            return {}

        with db.connect() as conn:
            ph = ','.join(['?'] * len(codes))
            latest_row = conn.execute("SELECT MAX(date) FROM etf_quotes").fetchone()
            if not latest_row or not latest_row[0]:
                return {}

            latest = latest_row[0]

            rows = conn.execute(
                f"""SELECT code, date, high, low, close, volume
                    FROM etf_quotes
                    WHERE code IN ({ph})
                    AND date >= date(?, '-{lookback + 10} days')
                    ORDER BY code, date""",
                codes + [latest],
            ).fetchall()

        quotes = defaultdict(list)
        for r in rows:
            quotes[r['code']].append({
                'date': r['date'],
                'high': float(r['high']),
                'low': float(r['low']),
                'close': float(r['close']),
                'volume': float(r['volume']),
            })

        return dict(quotes)

    def compute_metrics(self, quotes: dict[str, list[dict]]) -> dict[str, dict]:
        """从high/low/close计算ATR、涨跌幅、成交量等指标

        Args:
            quotes: {code: [{...}, ...], ...}

        Returns:
            {code: {'close', 'chg_5d', 'chg_20d', 'atr_pct', 'vol_ratio', 'lowest_20d'}, ...}
        """
        from engine.indicators import atr, chg_pct, vol_ratio, ma

        result = {}
        for code, rows in quotes.items():
            if len(rows) < 21:
                continue

            closes = np.array([r['close'] for r in rows])
            highs = np.array([r['high'] for r in rows])
            lows = np.array([r['low'] for r in rows])
            volumes = np.array([r['volume'] for r in rows])

            current = float(closes[-1])
            chg_5d_val = chg_pct(closes, 5)
            chg_20d_val = chg_pct(closes, 20)
            atr_pct_val = (atr(highs, lows, closes) / current * 100) if current > 0 else 0.0
            vr = vol_ratio(volumes)
            lowest_20d = float(np.min(lows[-20:])) if len(lows) >= 20 else float(np.min(lows))

            result[code] = {
                'close': current,
                'chg_5d': float(chg_5d_val),
                'chg_20d': float(chg_20d_val),
                'atr_pct': float(atr_pct_val),
                'vol_ratio': float(vr),
                'lowest_20d': float(lowest_20d),
            }
        return result

    def get_signals(self, date_str: Optional[str] = None) -> list[dict]:
        """获取最新信号数据

        Args:
            date_str: 指定日期，默认最新

        Returns:
            [{code, name, score, action, bb_pos, rsi, ...}, ...]
        """
        if date_str is None:
            date_str = self.latest_date()
        if not date_str:
            return []

        codes = list(POOL.keys())
        if not codes:
            return []

        with db.connect() as conn:
            ph = ','.join(['?'] * len(codes))
            rows = conn.execute(
                f"""SELECT code, date, score, action, reason, bb_pos, rsi,
                           ma20, ma60, close, chg_5d, chg_20d, atr_pct, trend
                    FROM etf_signals
                    WHERE code IN ({ph}) AND date = ?""",
                codes + [date_str],
            ).fetchall()

        result = []
        for r in rows:
            result.append({
                'code': r['code'],
                'name': POOL.get(r['code'], r['code']),
                'date': r['date'],
                'score': float(r['score']),
                'action': r['action'],
                'reason': r['reason'],
                'bb_pos': float(r['bb_pos']),
                'rsi': float(r['rsi']),
                'ma20': float(r['ma20']),
                'ma60': float(r['ma60']),
                'close': float(r['close']),
                'chg_5d': float(r['chg_5d']),
                'chg_20d': float(r['chg_20d']),
                'atr_pct': float(r['atr_pct']),
                'trend': r['trend'],
            })
        return result

    def save_signals(self, signals: list[dict]) -> int:
        """批量保存信号到数据库

        Args:
            signals: 信号列表

        Returns:
            保存数量
        """
        if not signals:
            return 0

        with db.connect() as conn:
            count = 0
            for s in signals:
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO etf_signals
                           (code, date, score, action, reason, bb_pos, rsi,
                            ma20, ma60, close, chg_5d, chg_20d, atr_pct, trend)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            s['code'],
                            s['date'],
                            s['score'],
                            s['action'],
                            s['reason'],
                            s['bb_pos'],
                            s['rsi'],
                            s['ma20'],
                            s['ma60'],
                            s['close'],
                            s['chg_5d'],
                            s['chg_20d'],
                            s['atr_pct'],
                            s['trend'],
                        ),
                    )
                    count += 1
                except Exception:
                    continue
            conn.commit()
        return count

    def get_market(self) -> dict:
        """获取最新市场状态"""
        with db.connect() as conn:
            row = conn.execute(
                "SELECT date, close, ma20, state, trend FROM market_index ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if row:
                return {
                    'date': row['date'],
                    'close': float(row['close']),
                    'ma20': float(row['ma20']),
                    'state': row['state'],
                    'trend': float(row['trend']),
                }
            return {'date': '', 'close': 0.0, 'ma20': 0.0, 'state': 'unknown', 'trend': 0.0}

    def save_market(self, market: dict) -> None:
        """保存市场状态"""
        with db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO market_index (date, close, ma20, state, trend)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    market.get('date', ''),
                    market.get('close', 0.0),
                    market.get('ma20', 0.0),
                    market.get('state', 'unknown'),
                    market.get('trend', 0.0),
                ),
            )
            conn.commit()

    def get_signals_history(self, days: int = 30) -> list[dict]:
        """获取历史信号统计

        Args:
            days: 回看天数

        Returns:
            [{date, total, buy_cnt, avg_score}, ...]
        """
        codes = list(POOL.keys())
        if not codes:
            return []

        with db.connect() as conn:
            ph = ','.join(['?'] * len(codes))
            latest_row = conn.execute("SELECT MAX(date) FROM etf_signals").fetchone()
            if not latest_row or not latest_row[0]:
                return []

            latest = latest_row[0]

            rows = conn.execute(
                f"""SELECT date,
                           COUNT(*) as total,
                           SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buy_cnt,
                           AVG(score) as avg_score
                    FROM etf_signals
                    WHERE code IN ({ph})
                    AND date >= date(?, '-{days} days')
                    GROUP BY date
                    ORDER BY date DESC""",
                codes + [latest],
            ).fetchall()

        return [
            {
                'date': str(r['date']),
                'total': r['total'],
                'buy_cnt': r['buy_cnt'],
                'avg_score': round(float(r['avg_score']), 1),
            }
            for r in rows
        ]

    def get_backtest_results(self, run_id: Optional[str] = None) -> list[dict]:
        """获取回测结果"""
        with db.connect() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM backtest_results WHERE run_id = ? ORDER BY date",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM backtest_results ORDER BY date"
                ).fetchall()

        return [dict(r) for r in rows]
