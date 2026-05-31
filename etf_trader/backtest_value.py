"""价值选股回测 — 2021-2026 月度调仓
20万本金，等权买4只，对比沪深300
"""
import pymysql, numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root","database":"stock_recommendation","charset":"utf8mb4"}

def load_snapshot(target_date):
    """在target_date加载当时的因子数据"""
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 基础池（上市>3年 + 非ST）
    cur.execute("SELECT stock_code,stock_name,industry,list_date FROM stock_info")
    base = {}
    for r in cur.fetchall():
        c,n,i,ld = r['stock_code'],r['stock_name'],r['industry'] or '其他',r['list_date']
        if 'ST' in (n or ''): continue
        if ld:
            ld = ld if isinstance(ld,datetime) else datetime.strptime(str(ld)[:10],'%Y-%m-%d')
            if (target_date - ld).days < 1095: continue
        base[c] = {'name':n,'industry':i}
    
    # 市值（用target_date前1月均值）
    t_str = target_date.strftime('%Y-%m-%d')
    t_minus = (target_date - timedelta(days=60)).strftime('%Y-%m-%d')
    cur.execute(f"SELECT ts_code,AVG(total_mv) as mv FROM daily_basic WHERE trade_date<='{t_str}' AND trade_date>='{t_minus}' GROUP BY ts_code")
    mv = {r['ts_code']:float(r['mv']) for r in cur.fetchall() if r['mv']}
    
    # 流动性
    cur.execute(f"SELECT stock_code,AVG(close*volume) as amt FROM daily_bars WHERE trade_date<='{t_str}' AND trade_date>='{t_minus}' GROUP BY stock_code")
    liq = {r['stock_code']:float(r['amt']) for r in cur.fetchall() if r['amt']}
    
    pool = {c:base[c] for c in base if c in mv and mv[c]>=500000 and c in liq and liq[c]>=20000000}
    
    # 财务（target_date前最新4季）
    cur.execute(f"""
        SELECT ts_code,
               AVG(roe) as roe, AVG(gross_margin) as gm,
               AVG(debt_ratio) as debt,
               AVG(CASE WHEN profit_yoy>500 THEN 500 WHEN profit_yoy<-200 THEN -200 ELSE profit_yoy END) as py
        FROM (SELECT ts_code,roe,gross_margin,debt_ratio,profit_yoy,
                     ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC) rn
              FROM financials WHERE end_date<='{t_str}') t WHERE rn<=4
        GROUP BY ts_code
    """)
    fin = {}
    for r in cur.fetchall():
        if r['roe'] is None: continue
        fin[r['ts_code']] = {'roe':float(r['roe']),'gm':float(r['gm'] or 0),'debt':float(r['debt'] or 50),'py':float(r['py'] or 0)}
    
    # 估值
    cur.execute(f"SELECT ts_code,pe_ttm,pb FROM daily_basic WHERE trade_date<='{t_str}' AND trade_date=(SELECT MAX(trade_date) FROM daily_basic WHERE trade_date<='{t_str}' AND ts_code=daily_basic.ts_code)")
    val = {}
    for r in cur.fetchall():
        pe = float(r['pe_ttm']) if r['pe_ttm'] and float(r['pe_ttm'])>0 else None
        pb = float(r['pb']) if r['pb'] and float(r['pb'])>0 else None
        if pe or pb: val[r['ts_code']] = {'pe':pe,'pb':pb}
    
    # 动量（前3个月）
    cur.execute(f"""
        SELECT stock_code,
               MAX(CASE WHEN rn=1 THEN close END) c0,
               MAX(CASE WHEN rn=26 THEN close END) c1m,
               MAX(CASE WHEN rn=66 THEN close END) c3m
        FROM (SELECT stock_code,close,ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) rn 
              FROM daily_bars WHERE trade_date<='{t_str}') t
        WHERE rn IN (1,26,66) GROUP BY stock_code
    """)
    mom = {}
    for r in cur.fetchall():
        c0=float(r['c0']) if r['c0'] else 0
        c1=float(r['c1m']) if r['c1m'] else 0
        c3=float(r['c3m']) if r['c3m'] else 0
        if c0 and c1 and c3: mom[r['stock_code']] = {'m1':(c0/c1-1)*100,'m3':(c0/c3-1)*100}
    
    # 波动率
    cur.execute("DROP TEMPORARY TABLE IF EXISTS _bt_ret")
    cur.execute(f"CREATE TEMPORARY TABLE _bt_ret AS SELECT stock_code,close/LAG(close) OVER (PARTITION BY stock_code ORDER BY trade_date)-1 ret FROM daily_bars WHERE trade_date<='{t_str}' AND trade_date>='{t_minus}'")
    cur.execute("SELECT stock_code,STDDEV(ret) vol FROM _bt_ret WHERE ret IS NOT NULL GROUP BY stock_code HAVING COUNT(*)>=30")
    risk = {r['stock_code']:float(r['vol']) for r in cur.fetchall()}
    
    conn.close()
    
    # 计算得分
    stocks = []
    for code in pool:
        if code not in fin or code not in mom or code not in risk: continue
        f=fin[code];m=mom[code];v=val.get(code,{});r=risk[code]
        stocks.append({
            'code':code,'industry':pool[code]['industry'],
            'roe':f['roe'],'gm':f['gm'],'debt':f['debt'],'py':f['py'],
            'pe':v.get('pe'),'pb':v.get('pb'),
            'm1':m['m1'],'m3':m['m3'],'vol':r
        })
    
    # 简化评分（跳过行业中性以加速）
    vals = np.array([s['roe'] for s in stocks]); zroe = (vals-np.mean(vals))/np.std(vals) if np.std(vals)>0 else np.zeros(len(vals))
    vals = np.array([s['pe'] or 999 for s in stocks]); zpe = -(vals-np.mean(vals))/np.std(vals) if np.std(vals)>0 else np.zeros(len(vals))
    vals = np.array([s['debt'] for s in stocks]); zdebt = -(vals-np.mean(vals))/np.std(vals) if np.std(vals)>0 else np.zeros(len(vals))
    vals = np.array([s['py'] for s in stocks]); zpy = (vals-np.mean(vals))/np.std(vals) if np.std(vals)>0 else np.zeros(len(vals))
    vals = np.array([s['vol'] for s in stocks]); zvol = -(vals-np.mean(vals))/np.std(vals) if np.std(vals)>0 else np.zeros(len(vals))
    
    for i,s in enumerate(stocks):
        s['score'] = zroe[i]*0.3 + zpe[i]*0.25 + zdebt[i]*0.15 + zpy[i]*0.15 + zvol[i]*0.15
    
    stocks.sort(key=lambda x:x['score'],reverse=True)
    return stocks[:4]


def backtest():
    # 生成每月调仓日
    months = []
    d = datetime(2021,1,1)
    while d <= datetime(2026,5,1):
        months.append(d)
        if d.month == 12: d = d.replace(year=d.year+1, month=1)
        else: d = d.replace(month=d.month+1)
    months = months[:-1]  # 最后一个月不交易
    
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor()
    cur.execute("SELECT trade_date,close FROM index_daily WHERE trade_date>='2021-01-01' ORDER BY trade_date")
    idx = {str(r[0]):float(r[1]) for r in cur.fetchall()}
    
    # 价格
    cur.execute("SELECT stock_code,trade_date,close FROM daily_bars WHERE trade_date>='2021-01-01' ORDER BY trade_date")
    prices = defaultdict(dict)
    for r in cur.fetchall(): prices[r[0]][str(r[1])]=float(r[2])
    conn.close()
    
    equity = 200000
    peak = equity
    max_dd = 0
    h300_equity = 200000
    trades = 0
    
    print(f"回测 {len(months)}个月...")
    results = []
    
    for i, m in enumerate(months):
        m_str = m.strftime('%Y-%m-%d')
        # 找下个月末
        next_m = months[i+1] if i+1<len(months) else m
        next_str = next_m.strftime('%Y-%m-%d')
        
        picks = load_snapshot(m)
        if not picks: continue
        
        period_ret = 0
        for s in picks:
            code = s['code']
            if m_str in prices.get(code,{}) and next_str in prices.get(code,{}):
                ret = prices[code][next_str]/prices[code][m_str]-1
                period_ret += ret / 4
                trades += 1
        
        if period_ret != 0:
            equity *= (1+period_ret)
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity-peak)/peak)
            
            # HS300
            if m_str in idx and next_str in idx:
                h300_ret = idx[next_str]/idx[m_str]-1
                h300_equity *= (1+h300_ret)
            else:
                h300_ret = 0
            
            results.append((m_str, period_ret, h300_ret))
    
    years = len(months)/12
    cagr = (equity/200000)**(1/years)-1
    h300_cagr = (h300_equity/200000)**(1/years)-1
    alpha = cagr - h300_cagr
    
    print(f"\n{'='*55}")
    print(f"  价值选股回测 (2021-01 ~ 2026-05, {len(months)}月)")
    print(f"{'='*55}")
    print(f"  初始: 20万")
    print(f"  终值: {equity/10000:.1f}万  (HS300: {h300_equity/10000:.1f}万)")
    print(f"  年化: {cagr*100:+.1f}%  (HS300: {h300_cagr*100:+.1f}%)  Alpha: {alpha*100:+.1f}%")
    print(f"  最大回撤: {max_dd*100:.1f}%")
    print(f"  交易: {trades}笔")
    
    # 年度
    yr = defaultdict(lambda:[0,0])
    for d,r,h in results:
        y=d[:4];yr[y][0]+=r;yr[y][1]+=h
    print(f"\n  年度收益:")
    for y in sorted(yr):
        print(f"    {y}: 策略{yr[y][0]*100:+5.1f}%  HS300{yr[y][1]*100:+5.1f}%")

if __name__=="__main__":
    backtest()
