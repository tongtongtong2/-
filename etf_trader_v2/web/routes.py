"""所有路由 — 带输入验证，JSON错误响应"""
from datetime import date

from flask import Blueprint, render_template, jsonify, request, abort

from config import POOL
from models.etf_data import ETFDataRepo
from models.holdings import HoldingsRepo
from engine.decision import decide
from engine.indicators import bollinger_bands, rsi, atr, ma, chg_pct, vol_ratio
from engine.scoring import composite_score


def _require_json():
    """校验请求是有效JSON"""
    data = request.get_json(silent=True)
    if data is None:
        abort(400, description='请求体必须是有效JSON')
    return data


def _require_fields(data: dict, *fields: str):
    """校验必填字段存在且非空"""
    for f in fields:
        if f not in data or data[f] is None or data[f] == '':
            abort(400, description=f'缺少必填字段: {f}')


def _require_positive(data: dict, *fields: str):
    """校验数值字段 > 0"""
    for f in fields:
        try:
            v = float(data[f])
            if v <= 0:
                abort(400, description=f'{f} 必须大于0')
        except (ValueError, TypeError):
            abort(400, description=f'{f} 必须是有效数字')


def _repo() -> ETFDataRepo:
    return ETFDataRepo()


def _holdings_repo() -> HoldingsRepo:
    return HoldingsRepo()


def _compute_all_signals() -> list[dict]:
    """计算所有ETF的信号（使用唯一决策引擎）"""
    import numpy as np

    repo = _repo()
    quotes = repo.get_all_quotes(lookback=66)
    metrics = repo.compute_metrics(quotes)
    market = repo.get_market()

    results = []
    today = str(date.today())

    for code, name in POOL.items():
        rows = quotes.get(code, [])

        if not rows or len(rows) < 21 or code not in metrics:
            results.append({
                'code': code,
                'name': name,
                'date': today,
                'score': 0.0,
                'action': 'NO_DATA',
                'reason': '缺少指标或行情数据',
                'bb_pos': 0.5,
                'rsi': 50.0,
                'ma20': 0.0,
                'ma60': 0.0,
                'close': 0.0,
                'chg_5d': 0.0,
                'chg_20d': 0.0,
                'atr_pct': 0.0,
                'trend': '?',
            })
            continue

        closes = np.array([r['close'] for r in rows])
        highs = np.array([r['high'] for r in rows])
        lows = np.array([r['low'] for r in rows])
        volumes = np.array([r['volume'] for r in rows])

        met = metrics[code]

        # 计算指标
        _, _, _, bb_pos = bollinger_bands(closes)
        rsi_val = rsi(closes)
        ma20_val = ma(closes, 20)
        ma60_val = ma(closes, 60)

        # 综合评分
        sc, _ = composite_score(closes, highs, lows, volumes)

        # 持仓检查
        holdings_repo = _holdings_repo()
        all_holdings = holdings_repo.list_all()
        held = any(h['code'] == code for h in all_holdings)
        entry_pnl = 0.0
        if held:
            h = next(h for h in all_holdings if h['code'] == code)
            if h['buy_price'] > 0:
                entry_pnl = (met['close'] - h['buy_price']) / h['buy_price']

        # 决策
        d = decide(
            code=code,
            score=sc,
            bb_pos=bb_pos,
            rsi_val=rsi_val,
            ma20=ma20_val,
            ma60=ma60_val,
            close=met['close'],
            chg_5d=met['chg_5d'],
            chg_20d=met['chg_20d'],
            atr_pct=met['atr_pct'],
            vol_ratio=met['vol_ratio'],
            market_state=market.get('state', 'unknown'),
            held=held,
            entry_pnl=entry_pnl,
        )

        results.append({
            'code': code,
            'name': name,
            'date': today,
            'score': round(d['score'], 1),
            'action': d['action'],
            'reason': d['reason'],
            'bb_pos': round(d['bb_pos'], 3),
            'rsi': round(d['rsi'], 1),
            'ma20': round(d['ma20'], 3),
            'ma60': round(d['ma60'], 3),
            'close': round(d['close'], 3),
            'chg_5d': round(d['chg_5d'], 1),
            'chg_20d': round(d['chg_20d'], 1),
            'atr_pct': round(d['atr_pct'], 2),
            'trend': d.get('trend', '?'),
        })

    return results


def register_routes(app):
    """注册所有路由到Flask应用"""

    # === 页面路由 ===

    @app.route('/')
    def home():
        signals = _compute_all_signals()
        market = _repo().get_market()
        buys = [s for s in signals if s['action'] == 'BUY']
        watches = [s for s in signals if s['action'] == 'WATCH']
        holds = [s for s in signals if s['action'] == 'HOLD']
        avoids = [s for s in signals if s['action'] in ('AVOID', 'SELL', 'TAKE_PROFIT', 'STOP')]
        no_data = [s for s in signals if s['action'] == 'NO_DATA']

        return render_template('home.html', nav='home',
                               buys=buys, watches=watches, holds=holds,
                               avoids=avoids, no_data=no_data,
                               market=market, latest=date.today())

    @app.route('/signals')
    def signals_page():
        signals = _compute_all_signals()
        buys = [s for s in signals if s['action'] == 'BUY']
        watches = [s for s in signals if s['action'] == 'WATCH']
        return render_template('signals.html', nav='signals',
                               buys=buys, watches=watches,
                               all_signals=signals, latest=date.today())

    @app.route('/history')
    def history_page():
        days = request.args.get('days', 30, type=int)
        days = max(1, min(365, days))  # 限制1-365天
        history = _repo().get_signals_history(days)
        return render_template('history.html', nav='history',
                               history=history, days=days)

    @app.route('/stats')
    def stats_page():
        signals = _compute_all_signals()
        market = _repo().get_market()
        history = _repo().get_signals_history(30)

        total = len([s for s in signals if s['action'] != 'NO_DATA'])
        buy_count = len([s for s in signals if s['action'] == 'BUY'])
        watch_count = len([s for s in signals if s['action'] == 'WATCH'])
        strong = len([s for s in signals if s['score'] >= 50])
        weak = len([s for s in signals if s['score'] < -30])
        avg_sc = round(sum(s['score'] for s in signals if s['action'] != 'NO_DATA') / total, 1) if total > 0 else 0.0

        stats = {
            'date': str(date.today()),
            'total_etfs': len(signals),
            'buy_count': buy_count,
            'watch_count': watch_count,
            'strong_count': strong,
            'weak_count': weak,
            'avg_score': avg_sc,
            'market': market,
            'history': history,
        }
        return render_template('stats.html', nav='stats', stats=stats)

    @app.route('/stocks')
    def stocks_page():
        """个股精选页面 — 使用ETF池+评分排名展示"""
        signals = _compute_all_signals()
        # 按评分排序，过滤无数据
        ranked = [s for s in signals if s['action'] != 'NO_DATA']
        ranked.sort(key=lambda x: -x['score'])

        top50 = ranked[:50]
        summary = {
            'total': len(POOL),
            'with_data': len(ranked),
            'avg_score': round(sum(s['score'] for s in ranked) / len(ranked), 1) if ranked else 0.0,
        }
        return render_template('stocks.html', nav='stocks',
                               top=top50, summary=summary)

    @app.route('/portfolio')
    def portfolio_page():
        repo = _holdings_repo()
        repo.refresh_prices()
        summary = repo.summary()
        return render_template('portfolio.html', nav='portfolio',
                               summary=summary)

    # === API路由 ===

    @app.route('/api/signals')
    def api_signals():
        signals = _compute_all_signals()
        market = _repo().get_market()
        return jsonify({
            'date': str(date.today()),
            'signals': signals,
            'market': market,
        })

    @app.route('/api/portfolio')
    def api_portfolio():
        repo = _holdings_repo()
        repo.refresh_prices()
        return jsonify(repo.summary())

    @app.route('/api/portfolio/add', methods=['POST'])
    def api_portfolio_add():
        data = _require_json()
        _require_fields(data, 'code', 'buy_price', 'shares')
        _require_positive(data, 'buy_price', 'shares')
        repo = _holdings_repo()
        repo.add(
            data['code'],
            data.get('name', data['code']),
            float(data['buy_price']),
            int(data['shares']),
            data.get('buy_date'),
        )
        repo.refresh_prices()
        return jsonify({'ok': True, 'summary': repo.summary()})

    @app.route('/api/portfolio/update', methods=['POST'])
    def api_portfolio_update():
        data = _require_json()
        _require_fields(data, 'code', 'field', 'value')
        repo = _holdings_repo()
        try:
            repo.update(data['code'], data['field'], data['value'])
        except ValueError as e:
            abort(400, description=str(e))
        return jsonify({'ok': True})

    @app.route('/api/portfolio/remove', methods=['POST'])
    def api_portfolio_remove():
        data = _require_json()
        _require_fields(data, 'code')
        repo = _holdings_repo()
        repo.remove(data['code'])
        return jsonify({'ok': True, 'summary': repo.summary()})

    @app.route('/api/portfolio/refresh', methods=['POST'])
    def api_portfolio_refresh():
        repo = _holdings_repo()
        n = repo.refresh_prices()
        return jsonify({'ok': True, 'updated': n, 'summary': repo.summary()})

    @app.route('/api/history')
    def api_history():
        days = request.args.get('days', 30, type=int)
        days = max(1, min(365, days))
        history = _repo().get_signals_history(days)
        return jsonify({'history': history, 'days': days})

    @app.route('/api/run_signal')
    def api_run_signal():
        """运行信号计算并保存"""
        signals = _compute_all_signals()
        count = _repo().save_signals(signals)
        return jsonify({'ok': True, 'saved': count, 'signals': signals})
