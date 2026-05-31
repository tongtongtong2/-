"""个股引擎 — 封装quant_model的多因子选股逻辑"""
import sys, json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymysql
import numpy as np

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root",
         "database":"stock_recommendation","charset":"utf8mb4"}

USER_WATCH = {  # 用户自选+持仓
    '601985': '中国核电', '601288': '农业银行', '600900': '长江电力',
    '600519': '贵州茅台', '000858': '五粮液', '600036': '招商银行',
    '601088': '中国神华', '601857': '中国石油', '601398': '工商银行',
}

SKIP_KEYWORDS = ['银行', '证券', '保险']  # 金融股 PE/PB结构不同


class StockEngine:
    def __init__(self):
        self._cache = None
        self._cache_date = None

    def load(self, force=False):
        """加载+评分，结果缓存"""
        from datetime import date
        today = str(date.today())
        if self._cache and self._cache_date == today and not force:
            return self._cache

        from quant_model import load_universe, rank
        stocks = load_universe()
        stocks = rank(stocks)
        self._cache = stocks
        self._cache_date = today
        return stocks

    def get_top(self, n=50, skip_financial=True):
        stocks = self.load()
        result = []
        for i, s in enumerate(stocks):
            if skip_financial and any(kw in s.get('industry', '') for kw in SKIP_KEYWORDS):
                continue
            if len(result) >= n:
                break
            result.append(self._fmt(s, i + 1))
        return result

    def get_watchlist(self):
        """用户自选股排名"""
        stocks = self.load()
        total = len(stocks)
        result = []
        for code, name in USER_WATCH.items():
            found = next((s for s in stocks if s['code'] == code), None)
            if found:
                rank = next((i+1 for i, s in enumerate(stocks) if s['code'] == code), 0)
                result.append({
                    **self._fmt(found, rank),
                    'total': total, 'pct': round(rank/total*100, 1),
                })
        return result

    def _fmt(self, s, rank):
        return {
            'rank': rank,
            'code': s['code'],
            'name': s['name'],
            'industry': s.get('industry', '未分类'),
            'score': round(s.get('final', s.get('score', 0)), 2),
            'value': round(s.get('value', 0), 2),
            'quality': round(s.get('quality', 0), 2),
            'safety': round(s.get('safety', 0), 2),
            'momentum': round(s.get('momentum', 0), 2),
            'roe': round(s.get('roe', 0), 1),
            'pe': round(s.get('pe', 0), 1) if s.get('pe') else None,
            'pb': round(s.get('pb', 0), 2) if s.get('pb') else None,
            'debt': round(s.get('debt', 0), 1),
        }

    def get_summary(self):
        stocks = self.load()
        total = len(stocks)
        watch = self.get_watchlist()

        # 行业分布
        industries = defaultdict(int)
        for s in stocks[:100]:
            industries[s.get('industry', '其他')] += 1

        return {
            'total_stocks': total,
            'top_industries': sorted(industries.items(), key=lambda x: -x[1])[:8],
            'watchlist': watch,
        }
