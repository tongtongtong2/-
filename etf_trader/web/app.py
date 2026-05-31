"""Flask Web — ETF布林带轮动平台"""
from flask import Flask, render_template, jsonify, request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # etf_trader/

app = Flask(__name__,
            template_folder=str(ROOT.parent / 'templates'),
            static_folder=str(ROOT.parent / 'static'))
app.config['SECRET_KEY'] = 'etf-bollinger-2026'

from web.etf_engine import ETFEngine


def engine():
    return ETFEngine()


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
