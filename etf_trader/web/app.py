"""Flask Web — ETF布林带轮动平台"""
from flask import Flask, render_template, jsonify, request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # etf_trader/

app = Flask(__name__,
            template_folder=str(ROOT.parent / 'templates'),
            static_folder=str(ROOT.parent / 'static'))
app.config['SECRET_KEY'] = 'etf-bollinger-2026'

from web.etf_engine import ETFEngine
from web.stock_engine import StockEngine
from web.portfolio_engine import PortfolioEngine


def engine():
    return ETFEngine()

def stock_engine():
    return StockEngine()

def port_engine():
    return PortfolioEngine()


@app.route('/')
def index():
    eng = engine()
    latest = eng.latest_date()
    signals = eng.get_signals()
    market = eng.get_market()
    return render_template('etf_home.html', nav='etf_home',
                           latest=latest, signals=signals, market=market)


@app.route('/signals')
def signals_page():
    eng = engine()
    return render_template('etf_signals.html', nav='etf_signals',
                           latest=eng.latest_date(), signals=eng.get_signals())


@app.route('/history')
def history_page():
    eng = engine()
    days = request.args.get('days', 30, type=int)
    return render_template('etf_history.html', nav='etf_history',
                           history=eng.get_history(days), days=days)


@app.route('/statistics')
def statistics_page():
    eng = engine()
    return render_template('etf_stats.html', nav='etf_stats', stats=eng.get_statistics())


@app.route('/api/signals')
def api_signals():
    eng = engine()
    return jsonify({'date': eng.latest_date(), 'signals': eng.get_signals_raw(),
                    'market': eng.get_market()})


# === 个股 ===
@app.route('/stocks')
def stocks_page():
    eng = stock_engine()
    top = eng.get_top(50)
    summary = eng.get_summary()
    return render_template('stock_home.html', nav='stocks',
                           top=top, summary=summary)

@app.route('/stocks/watchlist')
def stocks_watchlist():
    eng = stock_engine()
    watch = eng.get_watchlist()
    return render_template('stock_watchlist.html', nav='stocks',
                           watch=watch, total=eng.get_summary()['total_stocks'])

@app.route('/api/stocks')
def api_stocks():
    eng = stock_engine()
    return jsonify({'top': eng.get_top(30), 'watchlist': eng.get_watchlist()})


# === 持仓管理 ===
@app.route('/portfolio')
def portfolio_page():
    eng = port_engine()
    eng.refresh_prices()
    summary = eng.summary()
    return render_template('portfolio.html', nav='portfolio', summary=summary)


@app.route('/api/portfolio')
def api_portfolio():
    eng = port_engine()
    eng.refresh_prices()
    return jsonify(eng.summary())


@app.route('/api/portfolio/add', methods=['POST'])
def api_portfolio_add():
    data = request.get_json()
    eng = port_engine()
    eng.add(data['code'], data.get('name', data['code']),
             float(data['buy_price']), int(data['shares']),
             data.get('buy_date'))
    eng.refresh_prices()
    return jsonify({'ok': True, 'summary': eng.summary()})


@app.route('/api/portfolio/update', methods=['POST'])
def api_portfolio_update():
    data = request.get_json()
    eng = port_engine()
    eng.update(data['code'], data['field'], data['value'])
    return jsonify({'ok': True})


@app.route('/api/portfolio/remove', methods=['POST'])
def api_portfolio_remove():
    data = request.get_json()
    eng = port_engine()
    eng.remove(data['code'])
    return jsonify({'ok': True, 'summary': eng.summary()})


@app.route('/api/portfolio/refresh', methods=['POST'])
def api_portfolio_refresh():
    eng = port_engine()
    n = eng.refresh_prices()
    return jsonify({'ok': True, 'updated': n, 'summary': eng.summary()})
