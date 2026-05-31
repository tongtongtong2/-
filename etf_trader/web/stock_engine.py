"""个股引擎 — 从预计算缓存加载（启动快，不卡Flask）"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'stock_cache.json'

USER_WATCH = {
    '601985': '中国核电', '601288': '农业银行', '600900': '长江电力',
    '600519': '贵州茅台', '000858': '五粮液', '600036': '招商银行',
    '601088': '中国神华', '601857': '中国石油', '601398': '工商银行',
}

SKIP_KEYWORDS = ['银行', '证券', '保险']


class StockEngine:
    def __init__(self):
        if not CACHE.exists():
            raise FileNotFoundError(f'请先运行预计算: uv run python -m web.stock_engine --rebuild')
        data = json.loads(CACHE.read_text(encoding='utf-8'))
        self.stocks = data['stocks']
        self.total = data['total']
        self.date = data['date']

    def get_top(self, n=50, skip_financial=True):
        result = []
        for s in self.stocks:
            if skip_financial and any(kw in s.get('industry', '') for kw in SKIP_KEYWORDS):
                continue
            if len(result) >= n:
                break
            result.append(s)
        return result

    def get_watchlist(self):
        watch = []
        for code, name in USER_WATCH.items():
            found = next((s for s in self.stocks if s['code'] == code), None)
            if found:
                watch.append({**found, 'pct': round(found['rank']/self.total*100, 1)})
        return watch

    def get_summary(self):
        industries = defaultdict(int)
        for s in self.stocks[:100]:
            industries[s.get('industry', '其他')] += 1
        return {
            'total_stocks': self.total,
            'top_industries': sorted(industries.items(), key=lambda x: -x[1])[:8],
            'watchlist': self.get_watchlist(),
        }
