"""
数据获取层
使用 AKShare 获取A股数据（免费、无需token）

功能：
1. 大盘指数数据（沪深300/上证指数）
2. 个股日线数据
3. 板块数据
4. 缓存机制（避免重复请求）
"""
import os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# 缓存目录
CACHE_DIR = Path(__file__).parent.parent.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


class DataLoader:
    """
    数据加载器，支持 AKShare
    """
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
    
    def load_index(self, symbol: str = "000300", start_date: str = "2023-01-01",
                   end_date: str = None) -> pd.DataFrame:
        """
        加载指数数据
        symbol: "000300"(沪深300) / "000001"(上证指数) / "399006"(创业板)
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        cache_file = self.cache_dir / f"index_{symbol}_{start_date}_{end_date}.parquet"
        
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            print(f"  [缓存] 指数 {symbol}: {len(df)} 条")
            return df
        
        try:
            import akshare as ak
            
            # AKShare 指数日线
            df = ak.stock_zh_index_daily(symbol=f"sh{symbol}" if symbol.startswith("0") else f"sz{symbol}")
            df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                                   "low": "low", "close": "close", "volume": "volume"})
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
            df = df.sort_values("date").reset_index(drop=True)
            
            df.to_parquet(cache_file)
            print(f"  [下载] 指数 {symbol}: {len(df)} 条")
            return df
            
        except Exception as e:
            print(f"  [错误] 加载指数 {symbol} 失败: {e}")
            return self._generate_synthetic_index(start_date, end_date)
    
    def load_stocks(self, codes: List[str] = None, start_date: str = "2023-01-01",
                    end_date: str = None, top_n: int = 100) -> Dict[str, pd.DataFrame]:
        """
        加载个股数据
        codes: 股票代码列表，None则自动选取活跃股
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        if codes is None:
            codes = self._get_active_stocks(top_n)
        
        result = {}
        for code in codes:
            df = self._load_single_stock(code, start_date, end_date)
            if df is not None and len(df) >= 60:
                result[code] = df
        
        print(f"  共加载 {len(result)} 只股票数据")
        return result
    
    def _load_single_stock(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """加载单只股票"""
        cache_file = self.cache_dir / f"stock_{code}_{start_date}_{end_date}.parquet"
        
        if cache_file.exists():
            return pd.read_parquet(cache_file)
        
        try:
            import akshare as ak
            
            # 转换代码格式
            if code.startswith("6"):
                ak_code = f"{code}"
            else:
                ak_code = f"{code}"
            
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                    start_date=start_date.replace("-", ""),
                                    end_date=end_date.replace("-", ""),
                                    adjust="qfq")
            
            if df is None or len(df) == 0:
                return None
            
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "最高": "high",
                "最低": "low", "收盘": "close", "成交量": "volume",
                "成交额": "amount"
            })
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df["code"] = code
            df = df.sort_values("date").reset_index(drop=True)
            
            df.to_parquet(cache_file)
            return df
            
        except Exception as e:
            return None
    
    def _get_active_stocks(self, top_n: int = 100) -> List[str]:
        """获取活跃股票列表（按成交额排序）"""
        cache_file = self.cache_dir / "active_stocks.txt"
        
        if cache_file.exists():
            # 缓存1天
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - mtime < timedelta(days=1):
                return cache_file.read_text().strip().split("\n")[:top_n]
        
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            # 过滤ST、新股、停牌
            df = df[~df["名称"].str.contains("ST|退|N", na=False)]
            df = df[df["成交额"] > 0]
            df = df.sort_values("成交额", ascending=False)
            codes = df["代码"].head(top_n * 2).tolist()
            
            cache_file.write_text("\n".join(codes))
            return codes[:top_n]
            
        except Exception:
            # 回退：用一些常见的大盘股
            return self._default_stock_pool()[:top_n]
    
    def _default_stock_pool(self) -> List[str]:
        """默认股票池（沪深300成分股的一部分）"""
        return [
            "600519", "601318", "600036", "000858", "601166",
            "600276", "601398", "600030", "000333", "002415",
            "600900", "601888", "600809", "000568", "002304",
            "601012", "600585", "000001", "600000", "601688",
            "300750", "002475", "600887", "601899", "000651",
            "600048", "601985", "300059", "002594", "600104",
            "601601", "600031", "000725", "601225", "002352",
            "600690", "601668", "000002", "600016", "601138",
            "002714", "300015", "600436", "601816", "002142",
            "600196", "601766", "300124", "002027", "600050",
        ]
    
    def _generate_synthetic_index(self, start_date: str, end_date: str) -> pd.DataFrame:
        """生成模拟指数数据（AKShare不可用时的回退）"""
        dates = pd.date_range(start_date, end_date, freq="B")
        n = len(dates)
        
        # 模拟一个有牛熊震荡的走势
        np.random.seed(42)
        returns = np.random.normal(0.0003, 0.012, n)
        
        # 加入趋势：前1/3牛市，中间1/3熊市，后1/3震荡
        third = n // 3
        returns[:third] += 0.002       # 牛市偏移
        returns[third:2*third] -= 0.002  # 熊市偏移
        # 后1/3保持随机（震荡）
        
        prices = 3500 * np.cumprod(1 + returns)
        
        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": prices * (1 + np.random.uniform(-0.005, 0.005, n)),
            "high": prices * (1 + np.abs(np.random.normal(0, 0.01, n))),
            "low": prices * (1 - np.abs(np.random.normal(0, 0.01, n))),
            "close": prices,
            "volume": np.random.uniform(1e9, 5e9, n),
        })
        
        print(f"  [模拟] 生成合成指数数据: {len(df)} 条")
        return df
    
    def generate_synthetic_stocks(self, n_stocks: int = 50, 
                                  start_date: str = "2023-01-01",
                                  end_date: str = "2026-05-29") -> Dict[str, pd.DataFrame]:
        """
        生成模拟个股数据（用于无网络环境测试）
        模拟不同类型的股票：动量股、防御股、震荡股
        """
        dates = pd.date_range(start_date, end_date, freq="B")
        n_days = len(dates)
        result = {}
        
        np.random.seed(123)
        
        for i in range(n_stocks):
            code = f"{600000 + i:06d}"
            
            # 不同类型的股票
            if i < n_stocks // 3:
                # 动量股：高波动、高收益
                mu = 0.001
                sigma = 0.025
            elif i < 2 * n_stocks // 3:
                # 防御股：低波动、稳定
                mu = 0.0003
                sigma = 0.012
            else:
                # 震荡股：均值回归
                mu = 0.0001
                sigma = 0.018
            
            returns = np.random.normal(mu, sigma, n_days)
            # 加入一些趋势变化
            trend_shift = np.random.randint(n_days // 4, 3 * n_days // 4)
            returns[trend_shift:] += np.random.uniform(-0.003, 0.003)
            
            base_price = np.random.uniform(5, 80)
            prices = base_price * np.cumprod(1 + returns)
            
            volume = np.random.uniform(1e6, 1e8, n_days) * (1 + np.abs(returns) * 20)
            
            df = pd.DataFrame({
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "code": code,
                "open": prices * (1 + np.random.uniform(-0.01, 0.01, n_days)),
                "high": prices * (1 + np.abs(np.random.normal(0, 0.015, n_days))),
                "low": prices * (1 - np.abs(np.random.normal(0, 0.015, n_days))),
                "close": prices,
                "volume": volume,
                "amount": prices * volume,
            })
            
            result[code] = df
        
        print(f"  [模拟] 生成 {n_stocks} 只合成股票数据")
        return result
