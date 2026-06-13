"""HoldingsRepo — 持仓CRUD操作"""
from datetime import date
from typing import Optional

import db

# 允许更新的列白名单（防SQL注入）
_ALLOWED_FIELDS = {'buy_price', 'shares', 'buy_date', 'current_price'}


class HoldingsRepo:
    """持仓数据仓库 — 增删改查"""

    def list_all(self) -> list[dict]:
        """列出所有持仓"""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM holdings ORDER BY buy_date DESC"
            ).fetchall()

        result = []
        for r in rows:
            buy = float(r['buy_price'])
            cur_p = float(r['current_price']) if r['current_price'] else 0.0
            shares = int(r['shares'])
            cost = buy * shares
            market_val = cur_p * shares if cur_p else 0.0
            pnl = market_val - cost
            pnl_pct = ((cur_p / buy - 1) * 100) if buy > 0 and cur_p > 0 else 0.0

            result.append({
                'id': r['id'],
                'code': r['code'],
                'name': r['name'] or r['code'],
                'buy_price': buy,
                'shares': shares,
                'buy_date': str(r['buy_date']) if r['buy_date'] else '',
                'current_price': cur_p,
                'cost': round(cost, 2),
                'market_val': round(market_val, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 1),
                'updated_at': str(r['updated_at']) if r['updated_at'] else '',
            })
        return result

    def add(
        self,
        code: str,
        name: str,
        buy_price: float,
        shares: int,
        buy_date: Optional[str] = None,
    ) -> None:
        """添加持仓（或更新已有持仓）"""
        buy_date = buy_date or str(date.today())
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO holdings (code, name, buy_price, shares, buy_date)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(code) DO UPDATE SET
                       name=excluded.name,
                       buy_price=excluded.buy_price,
                       shares=excluded.shares,
                       buy_date=excluded.buy_date""",
                (code, name, buy_price, shares, buy_date),
            )
            conn.commit()

    def update(self, code: str, field: str, value: object) -> None:
        """更新持仓字段 — 白名单校验防SQL注入"""
        if field not in _ALLOWED_FIELDS:
            raise ValueError(f"不允许的字段: {field}")

        with db.connect() as conn:
            conn.execute(
                f"UPDATE holdings SET {field} = ? WHERE code = ?",
                (value, code),
            )
            conn.commit()

    def remove(self, code: str) -> None:
        """删除持仓"""
        with db.connect() as conn:
            conn.execute("DELETE FROM holdings WHERE code = ?", (code,))
            conn.commit()

    def refresh_prices(self) -> int:
        """从etf_quotes表拉最新价格刷新所有持仓"""
        holdings = self.list_all()
        if not holdings:
            return 0

        codes = [h['code'] for h in holdings]
        if not codes:
            return 0

        today = str(date.today())
        updated = 0

        with db.connect() as conn:
            ph = ','.join(['?'] * len(codes))

            # 批量查询最新价格
            rows = conn.execute(
                f"""SELECT q.code, q.close FROM etf_quotes q
                    INNER JOIN (
                        SELECT code, MAX(date) as max_date FROM etf_quotes
                        WHERE code IN ({ph}) GROUP BY code
                    ) q2 ON q.code = q2.code AND q.date = q2.max_date""",
                codes,
            ).fetchall()

            price_map = {r['code']: float(r['close']) for r in rows}

            # 批量更新
            for code_key in codes:
                price = price_map.get(code_key)
                if price is not None:
                    conn.execute(
                        "UPDATE holdings SET current_price = ?, updated_at = ? WHERE code = ?",
                        (price, today, code_key),
                    )
                    updated += 1

            conn.commit()

        return updated

    def summary(self) -> dict:
        """汇总统计"""
        holdings = self.list_all()
        total_cost = sum(h['cost'] for h in holdings)
        total_val = sum(h['market_val'] for h in holdings)
        total_pnl = sum(h['pnl'] for h in holdings)

        return {
            'count': len(holdings),
            'total_cost': round(total_cost, 2),
            'total_val': round(total_val, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round((total_val / total_cost - 1) * 100, 1) if total_cost > 0 else 0.0,
            'holdings': holdings,
        }
