"""多因子价值选股 v2 — GPT-5.5评审后优化版
价值40% + 质量30% + 安全20% + 动量10%
"""
import pymysql, numpy as np
from datetime import datetime
from collections import defaultdict

MYSQL = {"host":"127.0.0.1","port":3306,"user":"root","password":"root","database":"stock_recommendation","charset":"utf8mb4"}

def winsorize(arr, pct=0.02):
    arr=np.array(arr,dtype=float)
    mask=~np.isnan(arr); v=arr[mask]
    if len(v)<10: return np.zeros(len(arr))
    lo,hi=np.percentile(v,[pct*100,(1-pct)*100])
    result=arr.copy();result[mask]=np.clip(v,lo,hi)
    return result

def zscore(arr):
    arr=np.array(arr,dtype=float);mask=~np.isnan(arr);v=arr[mask]
    if len(v)<5: return np.zeros(len(arr))
    m=np.nanmean(v);s=np.nanstd(v)
    if s==0: return np.zeros(len(arr))
    result=np.zeros(len(arr));result[mask]=(v-m)/s
    return result

def sigmoid(arr, k=0.1):
    """S形变换：正负都有分，极端值不线性放大"""
    arr=np.array(arr,dtype=float)
    return 2/(1+np.exp(-k*arr))-1  # 映射到[-1,1]

def load_universe():
    conn=pymysql.connect(**MYSQL);cur=conn.cursor(pymysql.cursors.DictCursor)
    
    # 股票基础
    cur.execute("SELECT stock_code,stock_name,industry,list_date FROM stock_info")
    base={}
    for r in cur.fetchall():
        c,n,i,ld=r['stock_code'],r['stock_name'],r['industry'] or '未分类',r['list_date']
        if 'ST' in (n or ''): continue
        if ld:
            ld=ld if isinstance(ld,datetime) else datetime.strptime(str(ld)[:10],'%Y-%m-%d')
            if (datetime.now()-ld).days<1095: continue
        base[c]={'name':n,'industry':i}
    
    # 市值+流动性
    cur.execute("SELECT ts_code,AVG(total_mv) as mv FROM daily_basic WHERE trade_date>='2026-05-01' GROUP BY ts_code")
    mv={r['ts_code']:float(r['mv']) for r in cur.fetchall() if r['mv']}
    cur.execute("SELECT stock_code,AVG(close*volume) as amt FROM daily_bars WHERE trade_date>='2026-04-01' GROUP BY stock_code")
    liq={r['stock_code']:float(r['amt']) for r in cur.fetchall() if r['amt']}
    
    pool={c:base[c] for c in base if c in mv and mv[c]>=500000 and c in liq and liq[c]>=20000000}
    
    # 财务 (最近4季度均值，利润增速封顶防非经常性损益)
    cur.execute("""
        SELECT ts_code,
               AVG(roe) as roe, AVG(gross_margin) as gm, AVG(net_margin) as nm,
               AVG(debt_ratio) as debt,
               AVG(CASE WHEN rev_yoy>500 THEN 500 WHEN rev_yoy<-200 THEN -200 ELSE rev_yoy END) as rev,
               AVG(CASE WHEN profit_yoy>500 THEN 500 WHEN profit_yoy<-200 THEN -200 ELSE profit_yoy END) as py
        FROM (SELECT ts_code,roe,gross_margin,net_margin,debt_ratio,rev_yoy,profit_yoy,
                     ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC) rn
              FROM financials) t WHERE rn<=4
        GROUP BY ts_code
    """)
    fin={}
    for r in cur.fetchall():
        d={};f=r
        for k,nk in [('roe','roe'),('gross_margin','gm'),('net_margin','nm'),
                      ('debt_ratio','debt'),('rev_yoy','rev'),('profit_yoy','py')]:
            v=f[nk];d[k]=float(v) if v else None
        fin[f['ts_code']]=d
    
    # 估值+股息
    cur.execute("SELECT ts_code,pe_ttm,pb FROM daily_basic WHERE trade_date=(SELECT MAX(trade_date) FROM daily_basic)")
    val={}
    for r in cur.fetchall():
        pe=float(r['pe_ttm']) if r['pe_ttm'] and float(r['pe_ttm'])>0 else None
        pb=float(r['pb']) if r['pb'] and float(r['pb'])>0 else None
        if pe or pb: val[r['ts_code']]={'pe':pe,'pb':pb}
    
    # 动量
    cur.execute("""
        SELECT stock_code,MAX(CASE WHEN rn=1 THEN close END) c0,
               MAX(CASE WHEN rn=26 THEN close END) c1m,
               MAX(CASE WHEN rn=66 THEN close END) c3m
        FROM (SELECT stock_code,close,ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) rn FROM daily_bars WHERE trade_date>='2025-01-01') t
        WHERE rn IN (1,26,66) GROUP BY stock_code
    """)
    mom={}
    for r in cur.fetchall():
        c0=float(r['c0']) if r['c0'] else 0
        c1=float(r['c1m']) if r['c1m'] else 0
        c3=float(r['c3m']) if r['c3m'] else 0
        if c0 and c1 and c3:
            mom[r['stock_code']]={'mom1m':(c0/c1-1)*100,'mom3m':(c0/c3-1)*100}
    
    # 波动率
    cur.execute("CREATE TEMPORARY TABLE IF NOT EXISTS _ret AS SELECT stock_code,close/LAG(close) OVER (PARTITION BY stock_code ORDER BY trade_date)-1 ret FROM daily_bars WHERE trade_date>='2025-01-01'")
    cur.execute("SELECT stock_code,STDDEV(ret) vol FROM _ret WHERE ret IS NOT NULL GROUP BY stock_code HAVING COUNT(*)>=60")
    risk={r['stock_code']:float(r['vol']) for r in cur.fetchall()}
    
    # 股息率（用PE和ROE近似——有分红记录但无直接数据，设为可选）
    div={}  # dividend data not available in our schema, skip
    
    conn.close()
    
    # 合并
    stocks=[]
    for code in pool:
        if code not in fin or code not in mom or code not in risk: continue
        f=fin[code];m=mom[code];v=val.get(code,{});r=risk[code]
        # 硬过滤
        if f['roe'] and f['roe']<5 and (f['profit_yoy'] or 0)<-20: continue
        
        stocks.append({
            'code':code,'name':pool[code]['name'],'industry':pool[code]['industry'],
            'roe':f['roe'] or 0,'gross_margin':f['gross_margin'] or 0,
            'debt':f['debt_ratio'] or 50,'profit_yoy':f['profit_yoy'] or 0,
            'pe':v.get('pe'),'pb':v.get('pb'),
            'mom1m':m['mom1m'],'mom3m':m['mom3m'],'vol':r
        })
    return stocks


def rank(stocks):
    n=len(stocks)
    
    def gf(key,rev=False):
        vals=np.array([s.get(key) or 0 for s in stocks],dtype=float)
        vals=winsorize(vals);z=zscore(vals)
        if rev: z=-z
        return z
    
    # 价值40%
    pe=gf('pe',True)*0.625
    pb=gf('pb',True)*0.25
    div_val=np.zeros(n)  # no dividend data, skip
    value=pe+pb+div_val*0.125
    
    # 质量30%
    roe=np.clip(gf('roe'),-3,3)*0.50
    profit_g=gf('profit_yoy')*0.333
    margin=gf('gross_margin')*0.167
    quality=roe+profit_g+margin
    
    # 安全20%
    vol=gf('vol',True)*0.60
    debt=gf('debt',True)*0.40
    safety=vol+debt
    
    # 动量10% (sigmoid)
    mom1=sigmoid(gf('mom1m'))*0.40
    mom3=sigmoid(gf('mom3m'))*0.60
    momentum=(mom1+mom3)*0.5  # sigmoid already [-1,1] range
    
    composite=value*0.40+quality*0.30+safety*0.20+momentum*0.10
    
    for i,s in enumerate(stocks):
        s['value']=value[i];s['quality']=quality[i];s['safety']=safety[i]
        s['momentum']=momentum[i];s['score']=composite[i]
    
    # 行业中性
    ind=defaultdict(list)
    for s in stocks: ind[s['industry']].append(s)
    for k,g in ind.items():
        ss=np.array([s['score'] for s in g])
        zs=zscore(ss)
        for i,s in enumerate(g): s['final']=zs[i]
    
    stocks.sort(key=lambda x:x['final'] if not np.isnan(x['final']) else -999,reverse=True)
    return stocks


def main():
    print("加载数据...")
    stocks=load_universe()
    print(f"池: {len(stocks)}只")
    stocks=rank(stocks)
    
    print(f"\n{'='*90}")
    print(f"  价值选股 v2 — GPT-5.5优化版 (价值40+质量30+安全20+动量10)")
    print(f"{'='*90}")
    print(f"{'排名':<4} {'代码':<10} {'名称':<10} {'行业':<8} {'总':>6} {'值':>6} {'质':>6} {'安':>6} {'动':>6}")
    print(f"{'-'*70}")
    
    for i,s in enumerate(stocks[:30]):
        icon='⭐' if i<5 else '  '
        print(f"{icon}{i+1:<3} {s['code']:<10} {s['name']:<10} {s['industry']:<8} "
              f"{s['final']:+5.2f} {s['value']:+5.2f} {s['quality']:+5.2f} "
              f"{s['safety']:+5.2f} {s['momentum']:+5.2f}")
    
    # 用户持仓
    print(f"\n{'='*90}")
    print(f"  持仓排名 (共{len(stocks)}只)")
    print(f"{'='*90}")
    for code in ['601985','601288','600900','600519','000858']:
        found=next((s for s in stocks if s['code']==code),None)
        if found:
            rank_pos=next((i+1 for i,s in enumerate(stocks) if s['code']==code),0)
            print(f"  {code} {found['name']:<10} #{rank_pos}/{len(stocks)}(前{rank_pos/len(stocks)*100:.0f}%) "
                  f"值:{found['value']:+.2f} 质:{found['quality']:+.2f} 安:{found['safety']:+.2f} 动:{found['momentum']:+.2f}")

if __name__=="__main__":
    main()
