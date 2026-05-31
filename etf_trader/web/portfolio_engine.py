"""持仓引擎 — 用户自选持仓的增删改查+每日价格刷新"""
import pymysql
from datetime import date

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root",
         "database":"etf_trader","charset":"utf8mb4"}


class PortfolioEngine:
    def __init__(self):
        self.conn = pymysql.connect(**MYSQL)

    def list_all(self):
        """列出所有持仓"""
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM user_holdings ORDER BY buy_date DESC")
        rows = cur.fetchall()
        result = []
        for r in rows:
            buy = float(r['buy_price'])
            cur_p = float(r['current_price']) if r['current_price'] else 0
            shares = int(r['shares'])
            cost = buy * shares
            market_val = cur_p * shares if cur_p else 0
            pnl = market_val - cost
            pnl_pct = ((cur_p / buy - 1) * 100) if buy > 0 and cur_p > 0 else 0
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

    def add(self, code, name, buy_price, shares, buy_date=None):
        """添加持仓"""
        cur = self.conn.cursor()
        buy_date = buy_date or str(date.today())
        cur.execute("""
            INSERT INTO user_holdings (code, name, buy_price, shares, buy_date)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE name=%s, buy_price=%s, shares=%s, buy_date=%s
        """, (code, name, buy_price, shares, buy_date, name, buy_price, shares, buy_date))
        self.conn.commit()

    def update(self, code, field, value):
        """修改价格/股数"""
        cur = self.conn.cursor()
        cur.execute(f"UPDATE user_holdings SET {field}=%s WHERE code=%s", (value, code))
        self.conn.commit()

    def remove(self, code):
        """卖出移出"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM user_holdings WHERE code=%s", (code,))
        self.conn.commit()

    def refresh_prices(self):
        """从quote表拉最新价格刷新持仓"""
        holdings = self.list_all()
        if not holdings:
            return 0

        cur = self.conn.cursor()
        updated = 0
        today = str(date.today())

        for h in holdings:
            code = h['code']
            # 优先从etf_trader.quote查
            cur.execute("SELECT close FROM quote WHERE code=%s ORDER BY date DESC LIMIT 1", (code,))
            r = cur.fetchone()
            if r:
                price = float(r[0])
                cur.execute("UPDATE user_holdings SET current_price=%s, updated_at=%s WHERE code=%s",
                            (price, today, code))
                updated += 1
                continue

            # ETF没有的话，查个股 daily_bars
            cur2 = self.conn.cursor()
            cur2.execute("SELECT close FROM stock_recommendation.daily_bars WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 1", (code,))
            r2 = cur2.fetchone()
            if r2:
                price = float(r2[0])
                cur.execute("UPDATE user_holdings SET current_price=%s, updated_at=%s WHERE code=%s",
                            (price, today, code))
                updated += 1

        self.conn.commit()
        return updated

    def summary(self):
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
            'total_pnl_pct': round((total_val/total_cost - 1)*100, 1) if total_cost > 0 else 0,
            'holdings': holdings,
        }
