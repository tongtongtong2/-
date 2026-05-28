"""直接用腾讯行情接口选股（绕过东方财富连接问题）。

流程：
1. 从腾讯拉全 A 股实时行情
2. 初筛（去 ST、去涨停、流动性过滤）
3. 基本面过滤（ROE + PE）
4. 从新浪拉日线做技术分析
5. 硬过滤 + 多因子打分（含个股资金流、北向资金、股东人数）
6. 输出 TOP 10
"""
import os
import sys
import time
from strategy_engine import StrategyEngine
import math
from datetime import date, datetime, timedelta
from config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_providers.fundamental import FundamentalDataProvider
from data_providers.capital_flow import CapitalFlowProvider
from data_providers.shareholder import ShareholderDataProvider

# ── 板块资金流（东方财富API）──


for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import numpy as np
import pandas as pd
import requests

from config import Config

# ============================================================
# 腾讯行情接口
# ============================================================
def fetch_tencent_spot_batch(codes: list[str], session: requests.Session) -> list[dict]:
    """批量拉腾讯实时行情，每次最多 50 只。"""
    results = []
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        query = ",".join(batch)
        try:
            r = session.get(f"http://qt.gtimg.cn/q={query}", timeout=10)
            if r.status_code != 200:
                continue
        except Exception:
            continue
        for line in r.text.strip().split("\n"):
            if "=" not in line or '~' not in line:
                continue
            parts = line.split("~")
            if len(parts) < 45:
                continue
            try:
                results.append({
                    "stock_code": parts[2],
                    "stock_name": parts[1],
                    "current_price": float(parts[3]) if parts[3] else 0,
                    "change_percent": float(parts[32]) if parts[32] else 0,
                    "turnover": float(parts[37]) * 10000 if parts[37] else 0,  # 万元 -> 元
                    "volume": float(parts[36]) * 100 if parts[36] else 0,  # 手 -> 股
                    "open": float(parts[5]) if parts[5] else 0,
                    "high": float(parts[33]) if parts[33] else 0,
                    "low": float(parts[34]) if parts[34] else 0,
                    "prev_close": float(parts[4]) if parts[4] else 0,
                    "volume_ratio": float(parts[38]) if parts[38] else 0,
                    "total_market_cap": float(parts[45]) * 1e8 if len(parts) > 45 and parts[45] else 0,
                    "float_market_cap": float(parts[44]) * 1e8 if len(parts) > 44 and parts[44] else 0,
                })
            except (ValueError, IndexError):
                continue
    return results


def get_all_a_codes() -> list[str]:
    """生成沪深 A 股代码列表（主板+创业板，不含科创/北交所）。"""
    codes = []
    # 上证主板 600000-605999
    for i in range(600000, 606000):
        codes.append(f"sh{i:06d}")
    # 深证主板 000001-003999
    for i in range(1, 4000):
        codes.append(f"sz{i:06d}")
    # 创业板 300000-301999
    for i in range(300000, 302000):
        codes.append(f"sz{i:06d}")
    return codes


# ============================================================
# 新浪日线接口
# ============================================================
PLACEHOLDER_CONTINUE = "CONTINUE"

def fetch_sina_daily(code: str, session: requests.Session, days: int = 120) -> pd.DataFrame:
    """从新浪拉日线数据。"""
    # 新浪格式: sh600519 或 sz000001
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{symbol}_{days}/CN_MarketDataService.getKLineData"
    params = {
        "symbol": symbol,
        "scale": "240",  # 日线
        "ma": "no",
        "datalen": str(days),
    }
    try:
        r = session.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    text = r.text
    # 解析 JSONP: var _xxx=([{...},...]);
    start = text.find("([")
    end = text.rfind("])")
    if start < 0 or end < 0:
        return pd.DataFrame()
    import json
    try:
        data = json.loads(text[start+1:end+1])
    except json.JSONDecodeError:
        return pd.DataFrame()

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df.rename(columns={"day": "trade_date", "close": "close", "open": "open",
                       "high": "high", "low": "low", "volume": "volume"}, inplace=True)
    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df


# ============================================================
# 技术指标 + 硬过滤 + 打分（复用 stock_selector 的逻辑）
# ============================================================
MIN_DAILY_BARS = 70
MAX_RET_5 = 0.10
MAX_RET_20 = 0.30
MAX_VOL_STD = 0.04


def compute_indicators(daily: pd.DataFrame):
    if daily is None or daily.empty or "close" not in daily.columns:
        return None
    df = daily.sort_values("trade_date").reset_index(drop=True)
    if len(df) < MIN_DAILY_BARS:
        return None

    closes = df["close"].astype(float).values
    vols = df["volume"].astype(float).values if "volume" in df.columns else None
    if vols is None or len(vols) < MIN_DAILY_BARS:
        return None

    last = float(closes[-1])
    ma5 = float(np.mean(closes[-5:]))
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))

    ret_5 = last / closes[-6] - 1 if len(closes) >= 6 else 0.0
    ret_10 = last / closes[-11] - 1 if len(closes) >= 11 else 0.0
    ret_20 = last / closes[-21] - 1 if len(closes) >= 21 else 0.0
    ret_60 = last / closes[-61] - 1 if len(closes) >= 61 else 0.0

    daily_ret_20 = np.diff(closes[-21:]) / closes[-21:-1]
    vol_std = float(np.std(daily_ret_20))
    peak = np.maximum.accumulate(closes[-20:])
    drawdown = (closes[-20:] / peak) - 1
    max_dd = float(np.min(drawdown))

    avg5 = float(np.mean(vols[-5:]))
    avg20 = float(np.mean(vols[-20:]))
    vol_ratio = avg5 / avg20 if avg20 > 0 else 0.0
    avg_turnover20 = avg20 * np.mean(closes[-20:])

    high60 = float(np.max(closes[-60:]))
    dist_high60 = (high60 - last) / high60 if high60 > 0 else 0.0

    # 20日高点距离
    high20 = float(np.max(closes[-20:]))
    dist_high20 = (high20 - last) / high20 if high20 > 0 else 0.0
    
    # MA5/MA10 金叉检测（最近几天内是否有上穿）
    ma5_cross_days = 99
    if len(closes) >= 12:
        ma5_arr = np.array([np.mean(closes[i-4:i+1]) if i >= 4 else np.mean(closes[:i+1]) for i in range(len(closes))])
        ma10_arr = np.array([np.mean(closes[i-9:i+1]) if i >= 9 else np.mean(closes[:i+1]) for i in range(len(closes))])
        for lookback in range(1, 6):  # 检查最近5天
            idx = -1 - lookback
            if abs(idx) <= len(ma5_arr) and abs(idx-1) <= len(ma5_arr):
                if ma5_arr[idx] > ma10_arr[idx] and ma5_arr[idx-1] <= ma10_arr[idx-1]:
                    ma5_cross_days = lookback
                    break
    
    # MACD 金叉检测
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    macd_golden = False
    if len(dif) >= 3:
        for lookback in range(1, 4):
            idx = -1 - lookback
            if abs(idx) < len(dif) and abs(idx-1) < len(dif):
                if dif[idx] > dea[idx] and dif[idx-1] <= dea[idx-1]:
                    macd_golden = True
                    break
    
    return {
        "last": last,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ret_5": float(ret_5), "ret_10": float(ret_10),
        "ret_20": float(ret_20), "ret_60": float(ret_60),
        "vol_std": vol_std, "max_dd": max_dd,
        "vol_ratio_5_20": vol_ratio,
        "avg_turnover_20": avg_turnover20,
        "dist_high60": dist_high60,
        "dist_high20": dist_high20,
        "ma5_cross_ma10_days": ma5_cross_days,
        "macd_golden_cross": macd_golden,
    }


def passes_hard_filter(ind):
    if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]):
        return False, "均线非多头"
    if ind["last"] <= ind["ma60"]:
        return False, "未站上MA60"
    if ind["ret_5"] >= MAX_RET_5:
        return False, "5日过热"
    if ind["ret_20"] >= MAX_RET_20:
        return False, "20日过热"
    if ind["vol_std"] >= MAX_VOL_STD:
        return False, "波动率高"
    if ind["dist_high60"] < 0.03:
        return False, "距高点过近"
    return True, ""


# ══════════════════════════════════════════════════════
# 板块资金流因子（东方财富 API）
# ══════════════════════════════════════════════════════

# stock_info_new 行业 → 东方财富板块名称映射
INDUSTRY_TO_SECTOR = {
    "电气设备": "电力设备", "元器件": "元件", "半导体": "半导体",
    "通信设备": "通信设备", "汽车配件": "汽车零部件", "汽车整车": "汽车整车",
    "专用机械": "通用设备", "工程机械": "通用设备", "机械基件": "通用设备",
    "机床制造": "通用设备", "轻工机械": "通用设备", "纺织机械": "通用设备",
    "化工原料": "基础化工", "化学制药": "医药生物", "生物制药": "医药生物",
    "医疗保健": "医药生物", "医药商业": "医药商业", "中成药": "中药",
    "软件服务": "软件开发", "互联网": "互联网服务", "IT设备": "计算机设备",
    "电器仪表": "计算机设备", "航空": "航天航空", "船舶": "船舶制造",
    "银行": "银行", "证券": "证券", "保险": "保险",
    "白酒": "酿酒行业", "啤酒": "酿酒行业", "红黄酒": "酿酒行业",
    "家用电器": "家电行业", "家居用品": "装修建材",
    "水泥": "水泥建材", "玻璃": "玻璃玻纤", "陶瓷": "装修建材",
    "其他建材": "装修建材", "装修装饰": "装修建材",
    "普钢": "钢铁行业", "特种钢": "钢铁行业", "钢加工": "钢铁行业",
    "火力发电": "电力行业", "水力发电": "电力行业", "新型电力": "电力行业",
    "供气供热": "公用事业", "水务": "公用事业", "环境保护": "环保行业",
    "煤炭开采": "煤炭行业", "焦炭加工": "煤炭行业",
    "小金属": "小金属", "黄金": "贵金属",
    "铜": "有色金属", "铝": "有色金属", "铅锌": "有色金属", "矿物制品": "非金属材料",
    "石油开采": "石油行业", "石油加工": "石油行业", "石油贸易": "石油行业",
    "食品": "食品饮料", "乳制品": "食品饮料", "软饮料": "食品饮料",
    "饲料": "农牧饲渔", "农业综合": "农牧饲渔", "种植业": "农牧饲渔",
    "渔业": "农牧饲渔", "农药化肥": "农药兽药", "日用化工": "化学制品",
    "塑料": "塑料制品", "橡胶": "橡胶制品", "化纤": "化纤行业",
    "服饰": "纺织服装", "纺织": "纺织服装",
    "全国地产": "房地产开发", "区域地产": "房地产开发", "房产服务": "房地产服务",
    "建筑工程": "工程建设", "批发业": "贸易行业", "商贸代理": "贸易行业",
    "仓储物流": "物流行业", "水运": "航运港口", "港口": "航运港口",
    "空运": "航空机场", "机场": "航空机场",
    "铁路": "铁路公路", "公路": "铁路公路", "路桥": "铁路公路",
    "公共交通": "铁路公路",
    "旅游景点": "旅游酒店", "旅游服务": "旅游酒店", "酒店餐饮": "旅游酒店",
    "出版业": "文化传媒", "影视音像": "文化传媒", "广告包装": "文化传媒",
    "文教休闲": "教育", "染料涂料": "化学制品",
    "造纸": "造纸印刷", "汽车服务": "汽车服务",
    "超市连锁": "商业百货", "百货": "商业百货", "商品城": "商业百货",
    "园区开发": "房地产开发",
    "综合类": "综合行业", "运输设备": "交运设备",
    "电信运营": "通信服务",
}

def fetch_eastmoney_sector_flow():
    """拉取东方财富概念板块资金流向，返回 {板块名: 主力净流入(万元)}"""
    import requests
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    
    params = {
        "pn": "1", "pz": "200", "po": "1", "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2", "invt": "2", "fid0": "f62",
        "fs": "m:90+t:2", "stat": "1",
        "fields": "f12,f14,f2,f3,f62",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
    }
    
    try:
        resp = session.get(
            "http://push2.eastmoney.com/api/qt/clist/get",
            params=params, headers=headers, timeout=15
        )
        data = resp.json()
        if data.get("rc") == 0 and data.get("data") and data["data"].get("diff"):
            flows = {}
            for item in data["data"]["diff"]:
                name = item.get("f14", "")
                inflow = float(item.get("f62", 0) or 0)
                flows[name] = inflow
            print(f"  板块资金流加载: {len(flows)} 个板块")
            return flows
        else:
            print(f"  板块资金流API异常 rc={data.get('rc')}")
            return {}
    except Exception as e:
        print(f"  板块资金流获取失败: {e}")
        return {}


def get_sector_flow_bonus(stock_code, sector_flows, industry_map):
    """根据股票行业，返回板块资金流加分（-10~+10）"""
    industry = industry_map.get(stock_code, "")
    if not industry:
        return 0
    
    sector = INDUSTRY_TO_SECTOR.get(industry, "")
    if not sector:
        # 尝试模糊匹配
        for sname in sector_flows:
            if industry in sname or sname in industry:
                sector = sname
                break
    
    if not sector or sector not in sector_flows:
        return 0
    
    inflow = sector_flows[sector]  # 元
    
    # 映射到 -10 ~ +10 加分（inflow 单位：元）
    if inflow > 1_000_000_000:      # >10亿 → 满分
        return 10
    elif inflow > 300_000_000:      # 3-10亿
        return 7
    elif inflow > 0:
        return 4
    elif inflow > -300_000_000:
        return -4
    elif inflow > -1_000_000_000:
        return -7
    else:
        return -10
def score_dataframe(factors: pd.DataFrame, history_freq: dict = None, sector_flows: dict = None,
                    industry_map: dict = None, individual_flow_scores: dict = None,
                    northbound_scores: dict = None, shareholder_scores: dict = None) -> pd.DataFrame:
    df = factors.copy()

    def zrank(s):
        return s.rank(method="average", pct=True) * 100

    def bell_score(value, low, high):
        half = (high - low) / 2
        center = (low + high) / 2
        dist = (value - center).abs()
        over = (dist - half).clip(lower=0)
        score = 100 * (1 - over / half)
        return score.clip(lower=0, upper=100)

    # ── 趋势强度 (W_TREND=20%) ──
    df["score_ret60"] = zrank(df["ret_60"])
    df["bias_ma20"] = (df["last"] / df["ma20"]) - 1
    df["score_bias"] = zrank(df["bias_ma20"])
    df["trend_strength"] = df["score_ret60"] * 0.6 + df["score_bias"] * 0.4

    # ── 趋势平滑 (W_SMOOTH=25%) ──
    df["score_smooth_std"] = zrank(-df["vol_std"])
    df["score_smooth_dd"] = zrank(df["max_dd"])
    df["trend_smooth"] = df["score_smooth_std"] * 0.6 + df["score_smooth_dd"] * 0.4

    # ── 量能配合 (W_VOLUME=12%) ──
    df["score_vol"] = bell_score(df["vol_ratio_5_20"], 1.0, 2.0)
    df["volume_factor"] = df["score_vol"]

    # ── 位置因子 (W_POSITION=10%) ──
    df["score_pos"] = bell_score(df["dist_high60"], 0.05, 0.20)
    df["position"] = df["score_pos"]

    # ── 流动性 (W_LIQUIDITY=5%) ──
    df["score_liq"] = zrank(df["avg_turnover_20"])
    df["liquidity"] = df["score_liq"]

    # ── 历史连续性 (W_HISTORY=8%) ──
    if history_freq:
        df["history_count"] = df["stock_code"].map(history_freq).fillna(0).astype(int)
        df["history_score"] = (df["history_count"].clip(upper=3) / 3) * 100
    else:
        df["history_score"] = 0
    df["history_factor"] = df["history_score"]

    # ── 板块资金流 (W_SECTOR_FLOW=5%) ──
    if sector_flows and industry_map:
        df["sector_flow_bonus"] = df["stock_code"].apply(
            lambda c: get_sector_flow_bonus(c, sector_flows, industry_map)
        )
    else:
        df["sector_flow_bonus"] = 0
    df["sector_flow_factor"] = (df["sector_flow_bonus"] + 10) / 20 * 100  # 归一化到 0-100

    # ── 个股资金流 (W_INDIVIDUAL_FLOW=8%) ──
    if individual_flow_scores:
        df["individual_flow_score"] = df["stock_code"].map(individual_flow_scores).fillna(50)
    else:
        df["individual_flow_score"] = 50.0

    # ── 北向资金 (W_NORTHBOUND=5%) ──
    if northbound_scores:
        df["northbound_score"] = df["stock_code"].map(northbound_scores).fillna(50)
    else:
        df["northbound_score"] = 50.0

    # ── 股东人数加分 (0~10 bonus) ──
    if shareholder_scores:
        df["shareholder_bonus"] = df["stock_code"].map(shareholder_scores).fillna(0)
    else:
        df["shareholder_bonus"] = 0.0

    # ── 回撤惩罚：60日最大回撤 > 15% 扣分 ──
    df["dd_penalty"] = df["max_dd"].apply(lambda x: max(0, abs(x) - 0.15) * 200)
    df["dd_penalty"] = df["dd_penalty"].clip(upper=15)


    # ── 板块资金流因子（5%）：优先资金流入板块 ──
    # (已在上面处理)

    # ── 多策略命中打分 ──
    engine = StrategyEngine()
    strategy_results = []
    for _, row in df.iterrows():
        stock_data = {
            "close": row.get("current_price", 0),
            "open": row.get("open", 0),
            "high": row.get("high", 0),
            "low": row.get("low", 0),
            "prev_close": row.get("prev_close", 0),
            "change_pct": row.get("change_percent", 0),
            "ma5": row.get("ma5", 0),
            "ma10": row.get("ma10", 0),
            "ma20": row.get("ma20", 0),
            "ma60": row.get("ma60", 0),
            "ma20_slope": (row.get("ma20", 0) / row.get("ma60", 1) - 1) if row.get("ma60", 0) > 0 else 0,
            "vol_ratio_5_20": row.get("vol_ratio_5_20", 1.0),
            "volume_ratio": row.get("volume_ratio", 1.0),
            "dist_from_high_60d": row.get("dist_high60", 0),
            "dist_from_high_20d": row.get("dist_high20", row.get("dist_high60", 0)),
            "ret_60": row.get("ret_60", 0),
            "ret_5": row.get("ret_5", 0),
            "ma5_cross_ma10_days": row.get("ma5_cross_ma10_days", 99),
            "macd_golden_cross": row.get("macd_golden_cross", False),
        }
        result = engine.evaluate(stock_data)
        strategy_results.append(result)

    df["strategy_hit_count"] = [r["hit_count"] for r in strategy_results]
    df["strategy_hits"] = [",".join(r["hit_strategies"]) if r["hit_strategies"] else "" for r in strategy_results]
    df["strategy_bonus"] = [r["total_bonus"] for r in strategy_results]  # 权重由 Config.W_STRATEGY 控制

    # ── 总分计算（使用 Config 权重） ──
    df["total_score"] = (
        df["trend_strength"] * Config.W_TREND +
        df["trend_smooth"] * Config.W_SMOOTH +
        df["volume_factor"] * Config.W_VOLUME +
        df["position"] * Config.W_POSITION +
        df["liquidity"] * Config.W_LIQUIDITY +
        df["history_factor"] * Config.W_HISTORY +
        df["sector_flow_factor"] * Config.W_SECTOR_FLOW +
        df["individual_flow_score"] * Config.W_INDIVIDUAL_FLOW +
        df["northbound_score"] * Config.W_NORTHBOUND +
        df["shareholder_bonus"] +
        df["strategy_bonus"] * Config.W_STRATEGY -
        df["dd_penalty"]
    )
    return df


# ============================================================
# 历史推荐频次（增强选股连续性，减少单日噪声）
# ============================================================
def get_history_frequency(lookback_days: int = 7):
    """查询近 N 天系统推荐记录，返回 {stock_code: count}。"""
    import pymysql
    from config import Config
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER, password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE, charset='utf8mb4',
            connect_timeout=5,
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT stock_code, COUNT(*) as cnt FROM stock_recommendations "
            "WHERE source='system' AND recommend_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY) "
            "GROUP BY stock_code", (lookback_days,)
        )
        freq = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        print(f"  历史推荐记录加载: {len(freq)} 只票 (近{lookback_days}天)" if freq else "  历史推荐记录为空 (首次运行?)")
        return freq
    except Exception as e:
        print(f"  历史推荐查询失败（将跳过历史因子）: {e}")
        return {}


# ============================================================
# 主流程
# ============================================================
def main():
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print("=" * 60)
    print(f"  A股量化选股  {date.today().isoformat()}  (腾讯行情 + 新浪日线)")
    print("=" * 60)

    # 1) 拉全 A 股实时行情
    print("\n[1/4] 拉取实时行情...")
    all_codes = get_all_a_codes()
    spot_data = fetch_tencent_spot_batch(all_codes, session)
    print(f"  获取到 {len(spot_data)} 只股票行情")

    if not spot_data:
        print("  行情为空，退出（可能非交易时段）")
        sys.exit(1)

    df = pd.DataFrame(spot_data)

    # 2) 初筛
    print("\n[2/4] 初筛...")
    # 去 ST
    df = df[~df["stock_name"].str.contains("ST|退", case=False, na=False)]
    # 价格 > 0
    df = df[df["current_price"] > 0]
    # 成交额 >= 1 亿
    df = df[df["turnover"] >= 1e8]
    # 流通市值 >= 50 亿
    df = df[df["float_market_cap"] >= 5e9]
    # 当日不涨停（主板 9.5%，创业板 19.5%），不跌停
    is_growth = df["stock_code"].str.startswith("30")
    limit_up = np.where(is_growth, 19.5, 9.5)
    limit_down = np.where(is_growth, -19.5, -9.5)
    df = df[(df["change_percent"] < limit_up) & (df["change_percent"] > limit_down)]
    # 日内跌幅 > 5% 排除（暴跌不追）
    df = df[df["change_percent"] > -5.0]

    df = df.sort_values("turnover", ascending=False).head(300).reset_index(drop=True)
    print(f"  初筛后 {len(df)} 只（取成交额前 300）")

    if df.empty:
        print("  初筛后无候选，退出")
        sys.exit(0)

    # 2.5) 基本面过滤（ROE + PE）
    if Config.FUNDAMENTAL_FILTER:
        print("\n[2.5/6] 基本面过滤...")
        try:
            fund_provider = FundamentalDataProvider()
            pe_data = fund_provider.fetch_pe_batch()
            roe_data = fund_provider.fetch_roe_batch()
            # 需要行业映射来计算行业PE中位数
            import sqlite3 as _sqlite3
            _db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "backtest", "data", "market_data.db")
            _industry_map_all = {}
            try:
                _conn = _sqlite3.connect(_db_path)
                _cur = _conn.cursor()
                _cur.execute("SELECT stock_code, industry FROM stock_info_new")
                for _r in _cur.fetchall():
                    _industry_map_all[_r[0]] = _r[1] or ""
                _conn.close()
            except Exception:
                pass
            industry_pe_median = fund_provider.get_industry_pe_median(pe_data, _industry_map_all)
            before_count = len(df)
            df = fund_provider.apply_fundamental_filter(
                df, pe_data, roe_data, industry_pe_median, _industry_map_all,
                min_roe=Config.MIN_ROE, pe_mult=Config.PE_MULT
            )
            print(f"  基本面过滤: {before_count} → {len(df)} 只（剔除 {before_count - len(df)} 只）")
        except Exception as e:
            print(f"  基本面过滤跳过（API失败）: {e}")

    # 3) 并发拉日线 + 硬过滤
    print(f"\n[3/6] 并发拉日线 + 技术分析（12线程）...")
    candidates = df.to_dict("records")
    rows = []
    rejected = {}

    def _has_recent_limit_up(daily, code, lookback=5):
        if daily is None or daily.empty or "close" not in daily.columns:
            return False
        df = daily.sort_values("trade_date").tail(lookback + 2)
        if len(df) < 3:
            return False
        closes = df["close"].astype(float).values
        for i in range(1, len(closes)):
            if closes[i-1] > 0:
                chg = (closes[i] - closes[i-1]) / closes[i-1]
                limit = 0.195 if (str(code).startswith("30") or str(code).startswith("68")) else 0.095
                if chg >= limit:
                    return True
        return False

    def process_one(rec):
        code = rec["stock_code"]
        daily = fetch_sina_daily(code, session, days=120)
        return code, rec, daily

    done = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(process_one, r) for r in candidates]
        for fut in as_completed(futures):
            done += 1
            code, rec, daily = fut.result()
            ind = compute_indicators(daily)
            if ind is None:
                rejected["数据不足"] = rejected.get("数据不足", 0) + 1
                continue
            ok, reason = passes_hard_filter(ind)
            if not ok:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            if _has_recent_limit_up(daily, code, lookback=5):
                rejected["近5日涨停"] = rejected.get("近5日涨停", 0) + 1
                continue
            rows.append({
                "stock_code": code,
                "stock_name": rec["stock_name"],
                "current_price": rec["current_price"],
                "turnover": rec["turnover"],
                "float_market_cap": rec["float_market_cap"],
                "change_percent": rec["change_percent"],
                "open": rec.get("open", 0),
                "high": rec.get("high", 0),
                "low": rec.get("low", 0),
                "prev_close": rec.get("prev_close", 0),
                "volume_ratio": rec.get("volume_ratio", 0),
                "dist_high20": ind.get("dist_high20", 0),
                "ma5_cross_ma10_days": ind.get("ma5_cross_ma10_days", 99),
                "macd_golden_cross": ind.get("macd_golden_cross", False),
                **ind,
            })
            if done % 50 == 0:
                print(f"  已处理 {done}/{len(candidates)}...")

    print(f"  硬过滤后剩 {len(rows)} 只")
    print(f"  淘汰原因: {rejected}")

    if not rows:
        print("\n  硬过滤后无候选，今日无推荐。")
        print("  （可能市场整体偏弱，不满足均线多头条件）")
        sys.exit(0)

    # 4) 打分排序（含历史连续性因子）

    # ── 获取板块资金流和行业映射 ──
    sector_flows = fetch_eastmoney_sector_flow()
    # 从 SQLite 获取候选股票的行业信息
    import sqlite3
    industry_map = {}
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "backtest", "data", "market_data.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        codes = [r["stock_code"] for r in rows]
        placeholders = ",".join(["?" for _ in codes])
        cur.execute("SELECT stock_code, industry FROM stock_info_new WHERE stock_code IN (" + placeholders + ")", codes)
        for row_ in cur.fetchall():
            industry_map[row_[0]] = row_[1] or ""
        conn.close()
        print(f"  行业映射加载: {len(industry_map)} 只")
    except Exception as e:
        print(f"  行业映射加载失败: {e}")

    # ── 获取个股资金流 ──
    print("\n[4/6] 获取个股资金流 + 北向资金 + 股东人数...")
    capital_provider = CapitalFlowProvider()
    individual_flow_scores = None
    northbound_scores = None
    shareholder_scores = None

    try:
        flow_data = capital_provider.fetch_individual_flow_batch()
        individual_flow_scores = capital_provider.score_individual_flow(flow_data, codes)
        print(f"  个股资金流: {len(flow_data)} 只数据")
    except Exception as e:
        print(f"  个股资金流获取失败（用缓存兜底）: {e}")

    try:
        nb_data = capital_provider.fetch_northbound_flow()
        northbound_scores = capital_provider.score_northbound(nb_data, codes)
        print(f"  北向资金: {len(nb_data)} 只数据")
    except Exception as e:
        print(f"  北向资金获取失败（用缓存兜底）: {e}")

    try:
        sh_provider = ShareholderDataProvider()
        holder_data = sh_provider.fetch_shareholder_data()
        shareholder_scores = sh_provider.compute_bonus(holder_data, codes)
        print(f"  股东人数: {len(holder_data)} 只数据")
    except Exception as e:
        print(f"  股东人数获取失败（用缓存兜底）: {e}")

    print(f"\n[5/6] 多因子打分（9因子+策略命中）...")
    history_freq = get_history_frequency(lookback_days=7)
    factors = pd.DataFrame(rows)
    scored = score_dataframe(
        factors, history_freq, sector_flows, industry_map,
        individual_flow_scores=individual_flow_scores,
        northbound_scores=northbound_scores,
        shareholder_scores=shareholder_scores,
    )
    scored = scored.sort_values("total_score", ascending=False)
    top = scored.head(Config.TOP_N_STOCKS)

    print(f"\n{'='*60}")
    print(f"  今日推荐 TOP {len(top)}")
    print(f"{'='*60}\n")

    # 初始化信号生成器用于计算价格目标
    from app.signal_generator import SignalGenerator
    from app.data_fetcher import get_default_fetcher
    sig_gen = SignalGenerator()
    fetcher = get_default_fetcher()

    for i, (_, row) in enumerate(top.iterrows(), 1):
        code = row["stock_code"]
        name = row["stock_name"]
        price = row["current_price"]
        total = row["total_score"]
        chg = row["change_percent"]
        r60 = row["ret_60"] * 100
        r5 = row["ret_5"] * 100
        vs = row["vol_std"] * 100
        vr = row["vol_ratio_5_20"]
        dd = row["max_dd"] * 100
        dist = row["dist_high60"] * 100
        mcap = row["float_market_cap"] / 1e8

        hcnt = int(row.get("history_count", 0))
        htag = f"【连续{hcnt}次】" if hcnt >= 2 else (f"【首次推荐】" if hcnt == 1 else "")
        shit = row.get("strategy_hit_count", 0)
        shits = row.get("strategy_hits", "")
        stag = f" 命中{shit}策略" if shit > 0 else ""

        # 新因子标签
        flow_s = row.get("individual_flow_score", 50)
        nb_s = row.get("northbound_score", 50)
        sh_b = row.get("shareholder_bonus", 0)
        flow_tag = "↑" if flow_s > 70 else ("↓" if flow_s < 30 else "→")
        nb_tag = "↑" if nb_s > 70 else ("↓" if nb_s < 30 else "→")
        sh_tag = f"+{sh_b:.0f}" if sh_b > 0 else ""

        # 计算止盈止损价格
        try:
            history = fetcher.get_recent_daily(code, days=40)
            targets = sig_gen.compute_price_targets(price, history)
        except Exception:
            targets = {}

        print(f"  {i:2d}. [{code}] {name}  {htag}{stag}")
        if shits:
            print(f"      策略: {shits}")
        print(f"      现价 {price:.2f} ({chg:+.2f}%)  流通市值 {mcap:.0f}亿  综合分 {total:.1f}")
        print(f"      60日涨 {r60:+.1f}% | 5日涨 {r5:+.1f}% | 波动率 {vs:.2f}% | 量比 {vr:.2f} | 回撤 {dd:.1f}% | 距高点 {dist:.1f}%")
        print(f"      资金流{flow_tag} | 北向{nb_tag} | 股东{sh_tag}")
        if targets:
            print(f"      >>> 止损价 {targets['stop_loss_price']:.2f} (-{targets['stop_loss_pct']:.1f}%) | 止盈价 {targets['take_profit_price']:.2f} (+{targets['take_profit_pct']:.1f}%) | 移动止盈触发 {targets['trail_trigger_price']:.2f} (+{targets['trail_trigger_pct']:.1f}%)")
        print()

    print(f"{'='*60}")
    print("  策略: 中长期稳健趋势（持有10-30天）")
    print("  选股逻辑: 均线多头 + 趋势平稳 + 温和放量 + 基本面过滤 + 资金流共振")
    print("  止盈 ATR动态 / 止损 ATR动态 / 最长持有 30 天")
    print(f"{'='*60}")

    # ── 自动保存到数据库（供历史连续性因子使用）──
    _save_to_database(top)
    return top


def _save_to_database(top: pd.DataFrame, top_n: int = 10):
    """将 TOP N 推荐写入 stock_recommendations 表（先清旧数据再插入）。"""
    import pymysql
    from config import Config
    today = date.today().isoformat()
    try:
        conn = pymysql.connect(
            host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER, password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE, charset='utf8mb4',
            connect_timeout=5,
        )
        cursor = conn.cursor()
        # 先清除今日旧推荐
        cursor.execute(
            "DELETE FROM stock_recommendations WHERE recommend_date=%s AND source='system'",
            (today,)
        )
        deleted = cursor.rowcount
        saved = 0
        for _, row in top.head(top_n).iterrows():
            code = row["stock_code"]
            name = row["stock_name"]
            price = float(row["current_price"])
            reason = {
                "total_score": float(row["total_score"]),
                "ret_60": float(row["ret_60"]),
                "ret_5": float(row["ret_5"]),
                "vol_std": float(row.get("vol_std", 0)),
                "vol_ratio_5_20": float(row.get("vol_ratio_5_20", 0)),
                "dist_high60": float(row.get("dist_high60", 0)),
                "trend_strength": float(row.get("trend_strength", 0)),
                "trend_smooth": float(row.get("trend_smooth", 0)),
                "volume_factor": float(row.get("volume_factor", 0)),
                "position": float(row.get("position", 0)),
                "history_count": int(row.get("history_count", 0)),
                "current_price": float(row["current_price"]),
                "change_percent": float(row["change_percent"]) / 100,  # 统一存小数
                "strategy_hit_count": int(row.get("strategy_hit_count", 0)),
                "strategy_hits": str(row.get("strategy_hits", "")),
            }
            import json
            reason_json = json.dumps(reason, ensure_ascii=False)
            # UPSERT: 同票同日同来源则更新
            cursor.execute(
                "INSERT INTO stock_recommendations "
                "(stock_code, stock_name, recommend_date, recommend_price, "
                " price_status, recommend_reason, status, source, is_watched) "
                "VALUES (%s,%s,%s,%s,'filled',%s,'active','system',0) "
                "ON DUPLICATE KEY UPDATE "
                "recommend_price=VALUES(recommend_price), "
                "recommend_reason=VALUES(recommend_reason)",
                (code, name, today, price, reason_json)
            )
            saved += 1
        conn.commit()
        print(f"  \u2705 已保存 {saved}/{top_n} 条推荐到数据库")
    except Exception as e:
        print(f"  \u26a0\ufe0f 数据库保存失败（不影响选股结果）: {e}")
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
