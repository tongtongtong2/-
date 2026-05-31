"""ETF引擎 — 封装数据库查询和信号计算，供Flask和CLI共用"""
import pymysql, json
from collections import defaultdict
import numpy as np

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root",
         "database":"etf_trader","charset":"utf8mb4"}

POOL = {
    '562500': '机器人ETF',   '513100': '纳指ETF',
    '159949': '创业板50',    '515700': '新能源车',
    '159755': '电池ETF',     '561700': '电力ETF',
    '515790': '光伏ETF华泰', '515880': '通信ETF',
    '159996': '家电ETF',     '516880': '光伏ETF银华',
    '513180': '恒生科技',    '159605': '中概互联广发',
    '159607': '中概互联嘉实','159751': '港股通科技',
    '159711': '港股通50华夏','159726': '港股高股息',
    '159792': '港股互联网',
}

BOLL_OVERHEAT = 0.90
BOLL_OVERSOLD = 0.25


class ETFEngine:
    def __init__(self):
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = pymysql.connect(**MYSQL)
        return self._conn

    def latest_date(self):
        cur = self.conn.cursor()
        cur.execute("SELECT MAX(date) FROM indicators")
        return str(cur.fetchone()[0])

    def get_market(self):
        """大盘状态"""
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        latest = self.latest_date()
        cur.execute("""
            SELECT close FROM market_index_quote
            WHERE index_code='000001' AND date >= DATE_SUB(%s, INTERVAL 60 DAY)
            ORDER BY date
        """, (latest,))
        closes = [float(r['close']) for r in cur.fetchall()]
        if len(closes) < 20:
            return {'state': 'unknown', 'trend': 0, 'current': closes[-1] if closes else 0}

        arr = np.array(closes)
        ma20 = float(np.mean(arr[-20:]))
        ma20_5d_ago = float(np.mean(arr[-25:-5])) if len(arr) >= 25 else ma20
        trend = (ma20 - ma20_5d_ago) / ma20_5d_ago * 100
        current = float(arr[-1])

        if trend > 1:
            state = 'bull'
        elif trend < -1:
            state = 'bear'
        else:
            state = 'range'

        return {'state': state, 'trend': round(trend, 1), 'current': current, 'ma20': round(ma20, 1)}

    def get_signals_raw(self):
        """获取原始信号数据"""
        latest = self.latest_date()
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        codes = list(POOL.keys())
        ph = ','.join(['%s']*len(codes))

        # indicators
        cur.execute(f"SELECT code, data FROM indicators WHERE code IN ({ph}) AND date=%s", codes + [latest])
        ind_map = {}
        for r in cur.fetchall():
            ind_map[r['code']] = json.loads(r['data'])

        # signals
        cur.execute(f"""
            SELECT code, CAST(JSON_EXTRACT(signal_meta,'$.score') AS DOUBLE) as sc
            FROM signals WHERE code IN ({ph}) AND `date`=%s
        """, codes + [latest])
        sig_map = {}
        for r in cur.fetchall():
            sig_map[r['code']] = r['sc'] or 0

        # quotes (close for bb position)
        cur.execute(f"""
            SELECT code, date, close FROM quote
            WHERE code IN ({ph}) AND date >= DATE_SUB(%s, INTERVAL 66 DAY)
            ORDER BY code, date
        """, codes + [latest])
        quotes = defaultdict(list)
        for r in cur.fetchall():
            quotes[r['code']].append(float(r['close']))

        result = []
        for code, name in POOL.items():
            ind = ind_map.get(code, {})
            sc = sig_map.get(code, 0)
            closes = quotes.get(code, [])
            if not ind or len(closes) < 5:
                result.append({'code': code, 'name': name, 'score': sc, 'action': 'NO_DATA',
                               'bb_pos': 0, 'close': closes[-1] if closes else 0,
                               'chg_5d': 0, 'chg_20d': 0, 'rsi': 0, 'trend': '?'})
                continue

            close = closes[-1]
            bb_l = ind.get('bb_lower', 0)
            bb_u = ind.get('bb_upper', 0)
            bb_m = ind.get('bb_mid', 0)
            bb_pos = (close - bb_l) / (bb_u - bb_l) if bb_u > bb_l else 0.5
            ma20 = ind.get('ma20', 0)
            ma60 = ind.get('ma60', 0)
            rsi = ind.get('rsi', 50)
            chg_5 = (closes[-1]/closes[-6]-1)*100 if len(closes)>=6 else 0
            chg_20 = (closes[-1]/closes[-21]-1)*100 if len(closes)>=21 else 0

            # 决策
            action, reason = self._decide(sc, bb_pos, rsi, ma20, ma60)

            result.append({
                'code': code, 'name': name,
                'score': round(sc, 1),
                'bb_pos': round(bb_pos*100, 1),
                'close': close,
                'ma20': ma20, 'ma60': ma60,
                'bb_lower': bb_l, 'bb_upper': bb_u,
                'rsi': round(rsi, 1),
                'chg_5d': round(chg_5, 1),
                'chg_20d': round(chg_20, 1),
                'trend': '↑' if ma20 > ma60 else '↓',
                'action': action,
                'reason': reason,
            })

        result.sort(key=lambda x: (0 if x['action']=='BUY' else 1 if x['action']=='WATCH' else 2, -x['score']))
        return result

    def get_signals(self):
        """获取分组后的信号"""
        raw = self.get_signals_raw()
        return {
            'buys': [r for r in raw if r['action'] == 'BUY'],
            'watches': [r for r in raw if r['action'] == 'WATCH'],
            'holds': [r for r in raw if r['action'] == 'HOLD'],
            'avoids': [r for r in raw if r['action'] in ('AVOID', 'SELL')],
            'no_data': [r for r in raw if r['action'] == 'NO_DATA'],
            'all': raw,
        }

    def _decide(self, score, bb_pos, rsi, ma20, ma60):
        """决策逻辑（与etf_bollinger.py一致）"""
        uptrend = ma20 > ma60

        if score >= 50:
            if bb_pos < BOLL_OVERSOLD:
                return 'BUY', f'超卖+强看多 (布林{bb_pos:.0%} 评分{score:.0f})'
            elif bb_pos < 0.50:
                return 'BUY', f'回调+强看多 (布林{bb_pos:.0%} 评分{score:.0f})'
            elif bb_pos > BOLL_OVERHEAT:
                return 'AVOID', f'冲顶不追 (布林{bb_pos:.0%} RSI{rsi:.0f})'
            else:
                return 'WATCH', f'强看多但偏高 (布林{bb_pos:.0%})'
        elif score >= 30:
            if bb_pos < BOLL_OVERSOLD:
                return 'WATCH', f'超卖+看多 (布林{bb_pos:.0%})'
            elif bb_pos < 0.50:
                return 'WATCH', f'中性偏低 评分{score:.0f}'
            elif bb_pos > BOLL_OVERHEAT:
                return 'AVOID', f'高位不追 (布林{bb_pos:.0%})'
            else:
                return 'HOLD', f'评分{score:.0f} 观望'
        elif score >= -30:
            if bb_pos < BOLL_OVERSOLD:
                return 'WATCH', f'超卖但评分中性({score:.0f})'
            elif bb_pos > BOLL_OVERHEAT:
                return 'AVOID', f'高位+弱评分'
            else:
                return 'AVOID', f'中性无信号'
        else:
            return 'AVOID', f'评分差({score:.0f})'

    def get_history(self, days=30):
        """获取历史信号"""
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        codes = list(POOL.keys())
        ph = ','.join(['%s']*len(codes))

        cur.execute(f"""
            SELECT date, COUNT(*) as total,
                   SUM(CASE WHEN CAST(JSON_EXTRACT(signal_meta,'$.score') AS DOUBLE) >= 50 THEN 1 ELSE 0 END) as buy_cnt,
                   AVG(CAST(JSON_EXTRACT(signal_meta,'$.score') AS DOUBLE)) as avg_score
            FROM signals WHERE code IN ({ph})
            AND date >= DATE_SUB((SELECT MAX(date) FROM signals), INTERVAL %s DAY)
            GROUP BY date ORDER BY date DESC
        """, codes + [days])
        return [{'date': str(r['date']), 'total': r['total'], 'buy_cnt': r['buy_cnt'],
                 'avg_score': round(float(r['avg_score']), 1)} for r in cur.fetchall()]

    def get_statistics(self):
        """策略统计摘要"""
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        latest = self.latest_date()

        raw = self.get_signals_raw()
        buys = [r for r in raw if r['action'] == 'BUY']
        watches = [r for r in raw if r['action'] == 'WATCH']
        strong_scores = sum(1 for r in raw if r['score'] >= 50)
        weak_scores = sum(1 for r in raw if r['score'] < -30)

        # 近30天信号趋势
        history = self.get_history(30)
        buy_trend = [h['buy_cnt'] for h in history]

        return {
            'date': latest,
            'total_etfs': len(raw),
            'buy_count': len(buys),
            'watch_count': len(watches),
            'strong_count': strong_scores,
            'weak_count': weak_scores,
            'avg_score': round(sum(r['score'] for r in raw) / len(raw), 1) if raw else 0,
            'history': history,
        }
