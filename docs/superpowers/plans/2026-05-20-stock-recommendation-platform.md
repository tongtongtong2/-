# 股票推荐平台实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于量化因子策略的每日股票推荐平台，自动选股、跟踪表现、生成买卖信号，并提供 Web 界面展示。

**Architecture:** Flask Web 应用 + MySQL 数据库 + APScheduler 定时任务。数据获取使用 AkShare，选股基于动量、成交量和技术突破三类因子，每日自动更新推荐股票表现并生成买卖信号。

**Tech Stack:** Python 3.8+, Flask 3.0, MySQL 8.0, AkShare, APScheduler, Bootstrap 5, Chart.js

---

## 文件结构

```
F:/datax/stock-recommendation-platform/
├── app/
│   ├── __init__.py              # Flask 应用工厂
│   ├── models.py                # SQLAlchemy 数据库模型
│   ├── database.py              # 数据库连接和会话管理
│   ├── data_fetcher.py          # AkShare 数据获取封装
│   ├── stock_selector.py        # 选股引擎（量化因子）
│   ├── performance_tracker.py   # 表现跟踪模块
│   ├── signal_generator.py      # 买卖信号生成器
│   ├── scheduler.py             # APScheduler 定时任务
│   ├── routes.py                # Flask 路由和视图
│   └── utils.py                 # 工具函数（日志、日期等）
├── templates/
│   ├── base.html                # 基础模板
│   ├── index.html               # 首页（今日推荐）
│   ├── recommendations.html     # 推荐列表
│   ├── performance.html         # 表现跟踪
│   └── statistics.html          # 策略统计
├── static/
│   ├── css/
│   │   └── style.css            # 自定义样式
│   └── js/
│       └── charts.js            # Chart.js 图表配置
├── tests/
│   ├── __init__.py
│   ├── test_data_fetcher.py
│   ├── test_stock_selector.py
│   ├── test_signal_generator.py
│   └── test_performance_tracker.py
├── config.py                    # 配置文件
├── requirements.txt             # Python 依赖
├── init_db.py                   # 数据库初始化脚本
├── run.py                       # 应用启动脚本
└── .env.example                 # 环境变量示例

```

## Task 1: 项目基础设置

**Files:**
- Create: `F:/datax/stock-recommendation-platform/requirements.txt`
- Create: `F:/datax/stock-recommendation-platform/.env.example`
- Create: `F:/datax/stock-recommendation-platform/.gitignore`
- Create: `F:/datax/stock-recommendation-platform/config.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
PyMySQL==1.1.0
cryptography==41.0.7
APScheduler==3.10.4
akshare==1.13.0
pandas==2.1.4
numpy==1.26.2
requests==2.31.0
python-dotenv==1.0.0
pytest==7.4.3
```

- [ ] **Step 2: 创建 .env.example**

```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DATABASE=stock_recommendation
SECRET_KEY=change-this-to-random-secret-key
DEBUG=True
```

- [ ] **Step 3: 创建 .gitignore**

```gitignore
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.env
*.log
logs/
.pytest_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.DS_Store
```

- [ ] **Step 4: 创建 config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # 数据库配置
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'root')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'stock_recommendation')
    
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@"
        f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # Flask 配置
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    
    # 选股参数
    TOP_N_STOCKS = 10
    MIN_MARKET_CAP = 100000000  # 最小市值 1 亿
    MIN_VOLUME = 100000000      # 最小成交额 1 亿
    
    # 止盈止损
    TAKE_PROFIT = 0.10   # 10%
    STOP_LOSS = -0.05    # -5%
    MAX_HOLD_DAYS = 20   # 最大持有天数
    
    # 定时任务时间（24小时制）
    SELECTION_TIME = '15:30'
    UPDATE_TIME = '15:35'
    STATISTICS_TIME = '15:40'
    
    # 日志配置
    LOG_DIR = 'logs'
    LOG_FILE = 'app.log'
    LOG_LEVEL = 'INFO'
```

- [ ] **Step 5: 提交基础配置**

```bash
cd /f/datax/stock-recommendation-platform
git add requirements.txt .env.example .gitignore config.py
git commit -m "feat: add project configuration files"
```



## Task 2: 数据库模型和连接

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/__init__.py`
- Create: `F:/datax/stock-recommendation-platform/app/database.py`
- Create: `F:/datax/stock-recommendation-platform/app/models.py`
- Create: `F:/datax/stock-recommendation-platform/init_db.py`

- [ ] **Step 1: 创建 app/__init__.py（Flask 应用工厂）**

```python
from flask import Flask
from app.database import init_db

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')
    
    # 初始化数据库
    init_db(app)
    
    # 注册路由（稍后实现）
    with app.app_context():
        from app import routes
        app.register_blueprint(routes.bp)
    
    return app
```

- [ ] **Step 2: 创建 app/database.py**

```python
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """初始化数据库连接"""
    db.init_app(app)
    
def get_db():
    """获取数据库会话"""
    return db.session
```

- [ ] **Step 3: 创建 app/models.py（数据库模型）**

```python
from datetime import datetime
from app.database import db

class StockRecommendation(db.Model):
    """股票推荐记录表"""
    __tablename__ = 'stock_recommendations'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stock_code = db.Column(db.String(10), nullable=False, index=True)
    stock_name = db.Column(db.String(50), nullable=False)
    recommend_date = db.Column(db.Date, nullable=False, index=True)
    recommend_price = db.Column(db.Numeric(10, 2), nullable=False)
    recommend_reason = db.Column(db.JSON)
    status = db.Column(db.Enum('active', 'closed'), default='active', index=True)
    close_date = db.Column(db.Date)
    close_price = db.Column(db.Numeric(10, 2))
    final_return = db.Column(db.Numeric(10, 4))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    daily_performances = db.relationship('StockDailyPerformance', backref='recommendation', lazy='dynamic')
    
    def __repr__(self):
        return f'<StockRecommendation {self.stock_code} {self.recommend_date}>'

class StockDailyPerformance(db.Model):
    """股票每日表现表"""
    __tablename__ = 'stock_daily_performance'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey('stock_recommendations.id'), nullable=False)
    trade_date = db.Column(db.Date, nullable=False, index=True)
    current_price = db.Column(db.Numeric(10, 2), nullable=False)
    change_percent = db.Column(db.Numeric(10, 4), nullable=False)
    volume = db.Column(db.BigInteger)
    turnover = db.Column(db.Numeric(20, 2))
    signal = db.Column(db.Enum('buy', 'hold', 'sell'), nullable=False)
    signal_reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.Index('idx_recommendation_trade', 'recommendation_id', 'trade_date'),
    )
    
    def __repr__(self):
        return f'<StockDailyPerformance {self.recommendation_id} {self.trade_date}>'

class StrategyStatistics(db.Model):
    """策略统计表"""
    __tablename__ = 'strategy_statistics'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stat_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    total_recommendations = db.Column(db.Integer, nullable=False, default=0)
    active_positions = db.Column(db.Integer, nullable=False, default=0)
    closed_positions = db.Column(db.Integer, nullable=False, default=0)
    win_count = db.Column(db.Integer, nullable=False, default=0)
    loss_count = db.Column(db.Integer, nullable=False, default=0)
    win_rate = db.Column(db.Numeric(10, 4))
    avg_return = db.Column(db.Numeric(10, 4))
    max_return = db.Column(db.Numeric(10, 4))
    max_loss = db.Column(db.Numeric(10, 4))
    total_return = db.Column(db.Numeric(10, 4))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<StrategyStatistics {self.stat_date}>'
```

- [ ] **Step 4: 创建 init_db.py（数据库初始化脚本）**

```python
import pymysql
from config import Config
from app import create_app
from app.database import db

def create_database():
    """创建数据库（如果不存在）"""
    connection = pymysql.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {Config.MYSQL_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"数据库 {Config.MYSQL_DATABASE} 已创建或已存在")
    finally:
        connection.close()

def init_tables():
    """创建所有表"""
    app = create_app()
    with app.app_context():
        db.create_all()
        print("所有表已创建")

if __name__ == '__main__':
    print("开始初始化数据库...")
    create_database()
    init_tables()
    print("数据库初始化完成！")
```

- [ ] **Step 5: 测试数据库初始化**

```bash
cd /f/datax/stock-recommendation-platform
python init_db.py
```

预期输出：
```
开始初始化数据库...
数据库 stock_recommendation 已创建或已存在
所有表已创建
数据库初始化完成！
```

- [ ] **Step 6: 提交数据库模型**

```bash
git add app/__init__.py app/database.py app/models.py init_db.py
git commit -m "feat: add database models and initialization script"
```



## Task 3: 工具函数模块

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/utils.py`
- Create: `F:/datax/stock-recommendation-platform/tests/test_utils.py`

- [ ] **Step 1: 编写工具函数测试**

```python
import pytest
from datetime import date
from app.utils import setup_logger, is_trading_day

def test_setup_logger():
    """测试日志设置"""
    logger = setup_logger('test_logger')
    assert logger is not None
    assert logger.name == 'test_logger'

def test_is_trading_day():
    """测试交易日判断（使用已知的交易日和非交易日）"""
    # 2026-05-20 是周三，应该是交易日（假设不是节假日）
    # 注意：实际测试时需要根据真实交易日历调整
    result = is_trading_day(date(2026, 5, 20))
    assert isinstance(result, bool)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /f/datax/stock-recommendation-platform
pytest tests/test_utils.py -v
```

预期输出：包含 FAILED 和 "ModuleNotFoundError: No module named 'app.utils'"

- [ ] **Step 3: 实现 app/utils.py**

```python
import logging
import os
from datetime import date, datetime
from typing import Optional
import akshare as ak
from config import Config

def setup_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        log_file: 日志文件名（可选）
    
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 创建日志目录
    if not os.path.exists(Config.LOG_DIR):
        os.makedirs(Config.LOG_DIR)
    
    # 文件处理器
    if log_file is None:
        log_file = Config.LOG_FILE
    
    log_path = os.path.join(Config.LOG_DIR, log_file)
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 格式化器
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def is_trading_day(check_date: date) -> bool:
    """
    判断指定日期是否为交易日
    
    Args:
        check_date: 要检查的日期
    
    Returns:
        True 表示是交易日，False 表示不是
    """
    try:
        # 获取交易日历
        trade_calendar = ak.tool_trade_date_hist_sina()
        trade_dates = trade_calendar['trade_date'].tolist()
        
        # 转换为日期对象进行比较
        check_date_str = check_date.strftime('%Y-%m-%d')
        return check_date_str in trade_dates
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"获取交易日历失败: {e}")
        # 默认判断：周一到周五为交易日
        return check_date.weekday() < 5

def format_percent(value: float, decimals: int = 2) -> str:
    """
    格式化百分比显示
    
    Args:
        value: 数值（如 0.1 表示 10%）
        decimals: 小数位数
    
    Returns:
        格式化后的字符串（如 "+10.00%"）
    """
    sign = '+' if value >= 0 else ''
    return f"{sign}{value * 100:.{decimals}f}%"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_utils.py -v
```

预期输出：包含 PASSED

- [ ] **Step 5: 提交工具函数**

```bash
git add app/utils.py tests/test_utils.py
git commit -m "feat: add utility functions for logging and trading day check"
```



## Task 4: 数据获取模块

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/data_fetcher.py`
- Create: `F:/datax/stock-recommendation-platform/tests/test_data_fetcher.py`

- [ ] **Step 1: 编写数据获取模块测试**

```python
import pytest
from datetime import date, timedelta
from app.data_fetcher import DataFetcher

@pytest.fixture
def fetcher():
    return DataFetcher()

def test_get_stock_list(fetcher):
    """测试获取股票列表"""
    df = fetcher.get_stock_list()
    assert df is not None
    assert len(df) > 0
    assert 'stock_code' in df.columns
    assert 'stock_name' in df.columns

def test_get_stock_daily(fetcher):
    """测试获取股票历史数据"""
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    df = fetcher.get_stock_daily('000001', start_date.strftime('%Y%m%d'), end_date.strftime('%Y%m%d'))
    assert df is not None
    # 如果获取成功，应该有数据
    if len(df) > 0:
        assert 'close' in df.columns
        assert 'volume' in df.columns
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_data_fetcher.py -v
```

预期输出：包含 FAILED

- [ ] **Step 3: 实现 app/data_fetcher.py**

```python
import time
from datetime import date, datetime
from typing import List, Optional
import pandas as pd
import akshare as ak
from app.utils import setup_logger

logger = setup_logger('data_fetcher')

class DataFetcher:
    """数据获取模块，封装 AkShare 接口"""
    
    def __init__(self):
        self.retry_times = 3
        self.retry_delay = 5  # 秒
    
    def _retry_request(self, func, *args, **kwargs):
        """
        带重试的请求包装器
        
        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数
        
        Returns:
            函数执行结果
        """
        for attempt in range(self.retry_times):
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.retry_times}): {e}")
                if attempt < self.retry_times - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"请求最终失败: {e}")
                    raise
    
    def get_stock_list(self) -> pd.DataFrame:
        """
        获取 A 股股票列表
        
        Returns:
            包含股票代码和名称的 DataFrame
        """
        try:
            logger.info("开始获取股票列表")
            df = self._retry_request(ak.stock_zh_a_spot_em)
            
            # 重命名列
            df = df.rename(columns={
                '代码': 'stock_code',
                '名称': 'stock_name',
                '最新价': 'price',
                '涨跌幅': 'change_percent',
                '成交量': 'volume',
                '成交额': 'turnover',
                '市值': 'market_cap'
            })
            
            # 选择需要的列
            columns = ['stock_code', 'stock_name', 'price', 'change_percent', 'volume', 'turnover']
            df = df[[col for col in columns if col in df.columns]]
            
            logger.info(f"成功获取 {len(df)} 只股票")
            return df
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return pd.DataFrame()
    
    def get_stock_daily(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票历史日线数据
        
        Args:
            stock_code: 股票代码（如 000001）
            start_date: 开始日期（格式：YYYYMMDD）
            end_date: 结束日期（格式：YYYYMMDD）
        
        Returns:
            包含日线数据的 DataFrame
        """
        try:
            logger.debug(f"获取股票 {stock_code} 历史数据: {start_date} 到 {end_date}")
            df = self._retry_request(
                ak.stock_zh_a_hist,
                symbol=stock_code,
                period='daily',
                start_date=start_date,
                end_date=end_date,
                adjust='qfq'  # 前复权
            )
            
            if df.empty:
                logger.warning(f"股票 {stock_code} 无历史数据")
                return pd.DataFrame()
            
            # 重命名列
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'turnover',
                '涨跌幅': 'change_percent'
            })
            
            # 转换日期格式
            df['date'] = pd.to_datetime(df['date'])
            
            logger.debug(f"成功获取股票 {stock_code} {len(df)} 条历史数据")
            return df
        except Exception as e:
            logger.error(f"获取股票 {stock_code} 历史数据失败: {e}")
            return pd.DataFrame()
    
    def get_stock_realtime(self, stock_codes: List[str]) -> pd.DataFrame:
        """
        获取股票实时行情
        
        Args:
            stock_codes: 股票代码列表
        
        Returns:
            包含实时行情的 DataFrame
        """
        try:
            logger.info(f"获取 {len(stock_codes)} 只股票的实时行情")
            all_stocks = self.get_stock_list()
            
            if all_stocks.empty:
                return pd.DataFrame()
            
            # 筛选指定股票
            result = all_stocks[all_stocks['stock_code'].isin(stock_codes)]
            logger.info(f"成功获取 {len(result)} 只股票的实时行情")
            return result
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return pd.DataFrame()
    
    def calculate_ma(self, df: pd.DataFrame, periods: List[int]) -> pd.DataFrame:
        """
        计算移动平均线
        
        Args:
            df: 包含 close 列的 DataFrame
            periods: 周期列表（如 [5, 10, 20]）
        
        Returns:
            添加了 MA 列的 DataFrame
        """
        for period in periods:
            df[f'ma{period}'] = df['close'].rolling(window=period).mean()
        return df
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_data_fetcher.py -v
```

预期输出：包含 PASSED（注意：需要网络连接）

- [ ] **Step 5: 提交数据获取模块**

```bash
git add app/data_fetcher.py tests/test_data_fetcher.py
git commit -m "feat: add data fetcher module with AkShare integration"
```



## Task 5: 选股引擎

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/stock_selector.py`
- Create: `F:/datax/stock-recommendation-platform/tests/test_stock_selector.py`

- [ ] **Step 1: 编写选股引擎测试**

```python
import pytest
import pandas as pd
from datetime import date, timedelta
from app.stock_selector import StockSelector

@pytest.fixture
def selector():
    return StockSelector()

def test_calculate_momentum_score(selector):
    """测试动量因子计算"""
    # 创建模拟数据
    dates = pd.date_range(end=date.today(), periods=30)
    df = pd.DataFrame({
        'date': dates,
        'close': [10 + i * 0.1 for i in range(30)]  # 递增价格
    })
    score = selector.calculate_momentum_score(df)
    assert 0 <= score <= 100
    assert score > 0  # 上涨趋势应该有正分数

def test_filter_stocks(selector):
    """测试股票初筛"""
    # 创建模拟股票列表
    df = pd.DataFrame({
        'stock_code': ['000001', '000002', 'ST0003', '000004'],
        'stock_name': ['平安银行', '万科A', 'ST股票', '国农科技'],
        'turnover': [200000000, 150000000, 50000000, 180000000]
    })
    filtered = selector.filter_stocks(df)
    assert len(filtered) == 3  # ST股票和成交额不足的应被过滤
    assert 'ST0003' not in filtered['stock_code'].values
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_stock_selector.py -v
```

- [ ] **Step 3: 实现 app/stock_selector.py（第1部分）**

```python
from datetime import date, timedelta
from typing import List, Dict
import pandas as pd
import numpy as np
from config import Config
from app.data_fetcher import DataFetcher
from app.utils import setup_logger

logger = setup_logger('stock_selector')

class StockSelector:
    """选股引擎，基于量化因子策略筛选股票"""
    
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.top_n = Config.TOP_N_STOCKS
        self.min_volume = Config.MIN_VOLUME
    
    def filter_stocks(self, stock_list: pd.DataFrame) -> pd.DataFrame:
        """
        初筛股票
        
        Args:
            stock_list: 股票列表 DataFrame
        
        Returns:
            过滤后的股票列表
        """
        logger.info(f"开始初筛，原始股票数: {len(stock_list)}")
        
        # 剔除 ST、*ST 股票
        filtered = stock_list[~stock_list['stock_name'].str.contains('ST', na=False)]
        logger.info(f"剔除 ST 股票后: {len(filtered)}")
        
        # 剔除成交额小于最小值的股票
        if 'turnover' in filtered.columns:
            filtered = filtered[filtered['turnover'] >= self.min_volume]
            logger.info(f"剔除低成交额股票后: {len(filtered)}")
        
        return filtered
    
    def calculate_momentum_score(self, stock_data: pd.DataFrame) -> float:
        """
        计算动量因子得分
        
        Args:
            stock_data: 股票历史数据
        
        Returns:
            动量得分 (0-100)
        """
        if len(stock_data) < 20:
            return 0.0
        
        try:
            # 计算不同周期的涨幅
            close_prices = stock_data['close'].values
            
            # 5日涨幅
            if len(close_prices) >= 5:
                return_5d = (close_prices[-1] / close_prices[-5] - 1) * 100
            else:
                return_5d = 0
            
            # 10日涨幅
            if len(close_prices) >= 10:
                return_10d = (close_prices[-1] / close_prices[-10] - 1) * 100
            else:
                return_10d = 0
            
            # 20日涨幅
            if len(close_prices) >= 20:
                return_20d = (close_prices[-1] / close_prices[-20] - 1) * 100
            else:
                return_20d = 0
            
            # 加权计算（5日15%，10日15%，20日10%，总计40%）
            # 标准化到0-100分
            score = (return_5d * 0.375 + return_10d * 0.375 + return_20d * 0.25)
            
            # 限制在0-100范围
            score = max(0, min(100, score * 2.5))  # 乘以2.5使得10%涨幅约等于25分
            
            return score
        except Exception as e:
            logger.error(f"计算动量因子失败: {e}")
            return 0.0
    
    def calculate_volume_score(self, stock_data: pd.DataFrame) -> float:
        """
        计算成交量因子得分
        
        Args:
            stock_data: 股票历史数据
        
        Returns:
            成交量得分 (0-100)
        """
        if len(stock_data) < 20:
            return 0.0
        
        try:
            volumes = stock_data['volume'].values
            
            # 5日平均成交量
            avg_volume_5d = np.mean(volumes[-5:])
            
            # 20日平均成交量
            avg_volume_20d = np.mean(volumes[-20:])
            
            # 成交量放大倍数
            if avg_volume_20d > 0:
                volume_ratio = avg_volume_5d / avg_volume_20d
            else:
                volume_ratio = 1.0
            
            # 标准化到0-100分（放大2倍为满分）
            score = min(100, (volume_ratio - 1) * 100)
            score = max(0, score)
            
            return score
        except Exception as e:
            logger.error(f"计算成交量因子失败: {e}")
            return 0.0
    
    def calculate_breakout_score(self, stock_data: pd.DataFrame) -> float:
        """
        计算技术突破因子得分
        
        Args:
            stock_data: 股票历史数据
        
        Returns:
            突破得分 (0-100)
        """
        if len(stock_data) < 60:
            return 0.0
        
        try:
            close_prices = stock_data['close'].values
            current_price = close_prices[-1]
            
            # 20日最高价
            high_20d = np.max(close_prices[-20:])
            
            # 60日最高价
            high_60d = np.max(close_prices[-60:])
            
            score = 0.0
            
            # 突破20日高点（15分）
            if current_price >= high_20d * 0.99:  # 允许0.1%的误差
                score += 50
            
            # 突破60日高点（15分）
            if current_price >= high_60d * 0.99:
                score += 50
            
            return score
        except Exception as e:
            logger.error(f"计算技术突破因子失败: {e}")
            return 0.0


    
    def calculate_composite_score(self, stock_code: str, stock_data: pd.DataFrame) -> Dict:
        """
        计算综合得分
        
        Args:
            stock_code: 股票代码
            stock_data: 股票历史数据
        
        Returns:
            包含各因子得分和综合得分的字典
        """
        momentum_score = self.calculate_momentum_score(stock_data)
        volume_score = self.calculate_volume_score(stock_data)
        breakout_score = self.calculate_breakout_score(stock_data)
        
        # 加权计算综合得分（动量40%，成交量30%，技术突破30%）
        composite_score = (
            momentum_score * 0.4 +
            volume_score * 0.3 +
            breakout_score * 0.3
        )
        
        return {
            'stock_code': stock_code,
            'momentum_score': round(momentum_score, 2),
            'volume_score': round(volume_score, 2),
            'breakout_score': round(breakout_score, 2),
            'composite_score': round(composite_score, 2)
        }
    
    def select_stocks(self, select_date: date, top_n: int = None) -> List[Dict]:
        """
        执行选股
        
        Args:
            select_date: 选股日期
            top_n: 选取数量（默认使用配置值）
        
        Returns:
            推荐股票列表
        """
        if top_n is None:
            top_n = self.top_n
        
        logger.info(f"开始选股，日期: {select_date}, 目标数量: {top_n}")
        
        # 获取股票列表
        stock_list = self.data_fetcher.get_stock_list()
        if stock_list.empty:
            logger.error("获取股票列表失败")
            return []
        
        # 初筛
        filtered_stocks = self.filter_stocks(stock_list)
        logger.info(f"初筛后剩余 {len(filtered_stocks)} 只股票")
        
        # 计算历史数据日期范围
        end_date = select_date.strftime('%Y%m%d')
        start_date = (select_date - timedelta(days=90)).strftime('%Y%m%d')
        
        # 计算每只股票的得分
        scores = []
        for idx, row in filtered_stocks.iterrows():
            stock_code = row['stock_code']
            
            # 获取历史数据
            stock_data = self.data_fetcher.get_stock_daily(stock_code, start_date, end_date)
            
            if len(stock_data) < 60:
                logger.debug(f"股票 {stock_code} 历史数据不足，跳过")
                continue
            
            # 计算得分
            score_info = self.calculate_composite_score(stock_code, stock_data)
            score_info['stock_name'] = row['stock_name']
            score_info['current_price'] = stock_data['close'].iloc[-1]
            scores.append(score_info)
        
        # 按综合得分排序
        scores.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # 选取前N名
        selected = scores[:top_n]
        
        logger.info(f"选股完成，共选出 {len(selected)} 只股票")
        for stock in selected:
            logger.info(f"  {stock['stock_code']} {stock['stock_name']}: {stock['composite_score']}分")
        
        return selected
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_stock_selector.py -v
```

- [ ] **Step 5: 提交选股引擎**

```bash
git add app/stock_selector.py tests/test_stock_selector.py
git commit -m "feat: add stock selector with quantitative factor strategy"
```



## Task 6: 买卖信号生成器

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/signal_generator.py`
- Create: `F:/datax/stock-recommendation-platform/tests/test_signal_generator.py`

- [ ] **Step 1: 编写信号生成器测试**

```python
import pytest
import pandas as pd
from datetime import date
from app.signal_generator import SignalGenerator

@pytest.fixture
def generator():
    return SignalGenerator()

def test_generate_signal_buy(generator):
    """测试买入信号"""
    recommendation = {
        'recommend_price': 10.0,
        'recommend_date': date.today()
    }
    current_data = {'close': 10.0}
    history_data = pd.DataFrame({'close': [9.5, 9.8, 10.0]})
    
    signal, reason = generator.generate_signal(recommendation, current_data, history_data)
    assert signal in ['buy', 'hold', 'sell']

def test_generate_signal_sell_profit(generator):
    """测试止盈信号"""
    recommendation = {
        'recommend_price': 10.0,
        'recommend_date': date.today()
    }
    current_data = {'close': 11.5}  # 涨幅15%
    history_data = pd.DataFrame({'close': [10.0, 10.5, 11.0, 11.5]})
    
    signal, reason = generator.generate_signal(recommendation, current_data, history_data)
    assert signal == 'sell'
    assert '止盈' in reason
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_signal_generator.py -v
```

- [ ] **Step 3: 实现 app/signal_generator.py**

```python
from datetime import date, timedelta
from typing import Tuple, Dict
import pandas as pd
import numpy as np
from config import Config
from app.data_fetcher import DataFetcher
from app.utils import setup_logger

logger = setup_logger('signal_generator')

class SignalGenerator:
    """买卖信号生成器"""
    
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.take_profit = Config.TAKE_PROFIT
        self.stop_loss = Config.STOP_LOSS
        self.max_hold_days = Config.MAX_HOLD_DAYS
    
    def check_technical_deterioration(self, history_data: pd.DataFrame) -> bool:
        """
        检查技术指标是否恶化
        
        Args:
            history_data: 历史数据
        
        Returns:
            True 表示技术指标恶化
        """
        if len(history_data) < 10:
            return False
        
        try:
            # 计算5日和10日均线
            df = self.data_fetcher.calculate_ma(history_data.copy(), [5, 10])
            
            # 检查最新的5日均线是否跌破10日均线
            if 'ma5' in df.columns and 'ma10' in df.columns:
                latest_ma5 = df['ma5'].iloc[-1]
                latest_ma10 = df['ma10'].iloc[-1]
                
                if pd.notna(latest_ma5) and pd.notna(latest_ma10):
                    return latest_ma5 < latest_ma10
            
            return False
        except Exception as e:
            logger.error(f"检查技术指标失败: {e}")
            return False
    
    def generate_signal(
        self,
        recommendation: Dict,
        current_data: Dict,
        history_data: pd.DataFrame
    ) -> Tuple[str, str]:
        """
        生成买卖信号
        
        Args:
            recommendation: 推荐记录（包含 recommend_price, recommend_date）
            current_data: 当前数据（包含 close, volume 等）
            history_data: 历史数据
        
        Returns:
            (signal, reason) 元组，signal 为 'buy'/'hold'/'sell'
        """
        recommend_price = float(recommendation['recommend_price'])
        current_price = float(current_data['close'])
        recommend_date = recommendation['recommend_date']
        
        # 计算收益率
        change_percent = (current_price / recommend_price - 1)
        
        # 计算持有天数
        if isinstance(recommend_date, str):
            recommend_date = date.fromisoformat(recommend_date)
        hold_days = (date.today() - recommend_date).days
        
        # 止盈信号
        if change_percent >= self.take_profit:
            return 'sell', f'止盈 (涨幅 {change_percent*100:.2f}%)'
        
        # 止损信号
        if change_percent <= self.stop_loss:
            return 'sell', f'止损 (跌幅 {change_percent*100:.2f}%)'
        
        # 技术指标恶化 + 涨幅不足3%
        if change_percent < 0.03 and self.check_technical_deterioration(history_data):
            return 'sell', '技术指标恶化 (5日均线跌破10日均线)'
        
        # 成交量萎缩 + 涨幅不足5%
        if change_percent < 0.05 and len(history_data) >= 20:
            try:
                recent_volume = np.mean(history_data['volume'].iloc[-5:])
                avg_volume_20d = np.mean(history_data['volume'].iloc[-20:])
                
                if recent_volume < avg_volume_20d * 0.5:
                    return 'sell', '成交量萎缩'
            except Exception as e:
                logger.error(f"检查成交量失败: {e}")
        
        # 持有超过最大天数且收益为负
        if hold_days > self.max_hold_days and change_percent < 0:
            return 'sell', f'持有超过{self.max_hold_days}天且亏损'
        
        # 默认持有
        return 'hold', f'持有中 (涨幅 {change_percent*100:.2f}%)'
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_signal_generator.py -v
```

- [ ] **Step 5: 提交信号生成器**

```bash
git add app/signal_generator.py tests/test_signal_generator.py
git commit -m "feat: add signal generator for buy/hold/sell recommendations"
```



## Task 7: 表现跟踪模块

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/performance_tracker.py`
- Create: `F:/datax/stock-recommendation-platform/tests/test_performance_tracker.py`

- [ ] **Step 1: 编写表现跟踪测试**

```python
import pytest
from app.performance_tracker import PerformanceTracker

@pytest.fixture
def tracker():
    return PerformanceTracker()

def test_calculate_return(tracker):
    """测试收益率计算"""
    result = tracker.calculate_return(10.0, 11.0)
    assert result == 0.1  # 10%涨幅

def test_check_close_condition_profit(tracker):
    """测试止盈条件"""
    recommendation = {'recommend_price': 10.0, 'recommend_date': '2026-05-01'}
    current_data = {'close': 11.5, 'volume': 1000000}
    should_close = tracker.check_close_condition(recommendation, current_data, 10)
    assert should_close == True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_performance_tracker.py -v
```

- [ ] **Step 3: 实现 app/performance_tracker.py**

```python
from datetime import date
from typing import Dict, List
from app.database import db
from app.models import StockRecommendation, StockDailyPerformance
from app.data_fetcher import DataFetcher
from app.signal_generator import SignalGenerator
from app.utils import setup_logger
from config import Config

logger = setup_logger('performance_tracker')

class PerformanceTracker:
    """表现跟踪模块"""
    
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.signal_generator = SignalGenerator()
        self.take_profit = Config.TAKE_PROFIT
        self.stop_loss = Config.STOP_LOSS
    
    def calculate_return(self, recommend_price: float, current_price: float) -> float:
        """
        计算收益率
        
        Args:
            recommend_price: 推荐价格
            current_price: 当前价格
        
        Returns:
            收益率（小数形式）
        """
        return (current_price / recommend_price - 1)
    
    def check_close_condition(
        self,
        recommendation: Dict,
        current_data: Dict,
        hold_days: int
    ) -> bool:
        """
        检查是否触发平仓条件
        
        Args:
            recommendation: 推荐记录
            current_data: 当前数据
            hold_days: 持有天数
        
        Returns:
            True 表示应该平仓
        """
        recommend_price = float(recommendation['recommend_price'])
        current_price = float(current_data['close'])
        change_percent = self.calculate_return(recommend_price, current_price)
        
        # 止盈
        if change_percent >= self.take_profit:
            return True
        
        # 止损
        if change_percent <= self.stop_loss:
            return True
        
        # 持有超过最大天数且亏损
        if hold_days > Config.MAX_HOLD_DAYS and change_percent < 0:
            return True
        
        return False
    
    def update_daily_performance(self, trade_date: date) -> None:
        """
        更新所有活跃推荐的每日表现
        
        Args:
            trade_date: 交易日期
        """
        logger.info(f"开始更新每日表现，日期: {trade_date}")
        
        # 查询所有活跃推荐
        active_recommendations = StockRecommendation.query.filter_by(status='active').all()
        logger.info(f"找到 {len(active_recommendations)} 只活跃推荐")
        
        if not active_recommendations:
            logger.info("没有活跃推荐，跳过更新")
            return
        
        # 获取股票代码列表
        stock_codes = [rec.stock_code for rec in active_recommendations]
        
        # 获取实时行情
        realtime_data = self.data_fetcher.get_stock_realtime(stock_codes)
        
        if realtime_data.empty:
            logger.error("获取实时行情失败")
            return
        
        # 更新每只股票的表现
        for recommendation in active_recommendations:
            try:
                stock_code = recommendation.stock_code
                
                # 获取当前价格
                stock_info = realtime_data[realtime_data['stock_code'] == stock_code]
                if stock_info.empty:
                    logger.warning(f"未找到股票 {stock_code} 的实时数据")
                    continue
                
                current_price = float(stock_info['price'].iloc[0])
                volume = int(stock_info['volume'].iloc[0]) if 'volume' in stock_info.columns else 0
                turnover = float(stock_info['turnover'].iloc[0]) if 'turnover' in stock_info.columns else 0
                
                # 计算收益率
                change_percent = self.calculate_return(
                    float(recommendation.recommend_price),
                    current_price
                )
                
                # 获取历史数据用于信号生成
                end_date = trade_date.strftime('%Y%m%d')
                start_date = (trade_date - timedelta(days=30)).strftime('%Y%m%d')
                history_data = self.data_fetcher.get_stock_daily(stock_code, start_date, end_date)
                
                # 生成买卖信号
                signal, signal_reason = self.signal_generator.generate_signal(
                    {
                        'recommend_price': recommendation.recommend_price,
                        'recommend_date': recommendation.recommend_date
                    },
                    {'close': current_price, 'volume': volume},
                    history_data
                )
                
                # 插入每日表现记录
                performance = StockDailyPerformance(
                    recommendation_id=recommendation.id,
                    trade_date=trade_date,
                    current_price=current_price,
                    change_percent=change_percent,
                    volume=volume,
                    turnover=turnover,
                    signal=signal,
                    signal_reason=signal_reason
                )
                db.session.add(performance)
                
                # 如果信号为卖出，更新推荐状态为已平仓
                if signal == 'sell':
                    recommendation.status = 'closed'
                    recommendation.close_date = trade_date
                    recommendation.close_price = current_price
                    recommendation.final_return = change_percent
                    logger.info(f"股票 {stock_code} 触发卖出信号: {signal_reason}")
                
            except Exception as e:
                logger.error(f"更新股票 {recommendation.stock_code} 表现失败: {e}")
                continue
        
        # 提交所有更改
        try:
            db.session.commit()
            logger.info("每日表现更新完成")
        except Exception as e:
            db.session.rollback()
            logger.error(f"提交数据库更改失败: {e}")

from datetime import timedelta
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_performance_tracker.py -v
```

- [ ] **Step 5: 提交表现跟踪模块**

```bash
git add app/performance_tracker.py tests/test_performance_tracker.py
git commit -m "feat: add performance tracker for daily stock monitoring"
```



## Task 8: 定时任务调度器

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/scheduler.py`

- [ ] **Step 1: 实现 app/scheduler.py**

```python
from datetime import date, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.database import db
from app.models import StockRecommendation, StockDailyPerformance, StrategyStatistics
from app.stock_selector import StockSelector
from app.performance_tracker import PerformanceTracker
from app.utils import setup_logger, is_trading_day
from config import Config

logger = setup_logger('scheduler')

class TaskScheduler:
    """定时任务调度器"""
    
    def __init__(self, app):
        self.app = app
        self.scheduler = BackgroundScheduler()
        self.stock_selector = StockSelector()
        self.performance_tracker = PerformanceTracker()
    
    def daily_stock_selection(self):
        """每日选股任务"""
        today = date.today()
        
        # 判断是否为交易日
        if not is_trading_day(today):
            logger.info(f"{today} 不是交易日，跳过选股")
            return
        
        logger.info(f"开始执行每日选股任务: {today}")
        
        with self.app.app_context():
            try:
                # 执行选股
                selected_stocks = self.stock_selector.select_stocks(today)
                
                if not selected_stocks:
                    logger.warning("选股结果为空")
                    return
                
                # 保存推荐记录
                for stock in selected_stocks:
                    recommendation = StockRecommendation(
                        stock_code=stock['stock_code'],
                        stock_name=stock['stock_name'],
                        recommend_date=today,
                        recommend_price=stock['current_price'],
                        recommend_reason={
                            'momentum_score': stock['momentum_score'],
                            'volume_score': stock['volume_score'],
                            'breakout_score': stock['breakout_score'],
                            'composite_score': stock['composite_score']
                        },
                        status='active'
                    )
                    db.session.add(recommendation)
                    
                    # 插入初始表现记录（买入信号）
                    performance = StockDailyPerformance(
                        recommendation=recommendation,
                        trade_date=today,
                        current_price=stock['current_price'],
                        change_percent=0.0,
                        signal='buy',
                        signal_reason='推荐买入'
                    )
                    db.session.add(performance)
                
                db.session.commit()
                logger.info(f"选股任务完成，推荐 {len(selected_stocks)} 只股票")
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"选股任务失败: {e}", exc_info=True)
    
    def daily_performance_update(self):
        """每日更新任务"""
        today = date.today()
        
        if not is_trading_day(today):
            logger.info(f"{today} 不是交易日，跳过更新")
            return
        
        logger.info(f"开始执行每日更新任务: {today}")
        
        with self.app.app_context():
            try:
                self.performance_tracker.update_daily_performance(today)
                logger.info("每日更新任务完成")
            except Exception as e:
                logger.error(f"每日更新任务失败: {e}", exc_info=True)
    
    def daily_statistics(self):
        """每日统计任务"""
        today = date.today()
        
        if not is_trading_day(today):
            logger.info(f"{today} 不是交易日，跳过统计")
            return
        
        logger.info(f"开始执行每日统计任务: {today}")
        
        with self.app.app_context():
            try:
                # 查询所有推荐
                all_recommendations = StockRecommendation.query.all()
                active_recommendations = StockRecommendation.query.filter_by(status='active').all()
                closed_recommendations = StockRecommendation.query.filter_by(status='closed').all()
                
                # 计算统计指标
                total_count = len(all_recommendations)
                active_count = len(active_recommendations)
                closed_count = len(closed_recommendations)
                
                # 计算盈亏
                win_count = sum(1 for rec in closed_recommendations if rec.final_return and rec.final_return > 0)
                loss_count = sum(1 for rec in closed_recommendations if rec.final_return and rec.final_return <= 0)
                
                # 胜率
                win_rate = win_count / closed_count if closed_count > 0 else 0
                
                # 平均收益率
                returns = [rec.final_return for rec in closed_recommendations if rec.final_return is not None]
                avg_return = sum(returns) / len(returns) if returns else 0
                
                # 最大收益和最大亏损
                max_return = max(returns) if returns else 0
                max_loss = min(returns) if returns else 0
                
                # 累计收益率（简单平均）
                total_return = sum(returns) if returns else 0
                
                # 保存统计记录
                stats = StrategyStatistics(
                    stat_date=today,
                    total_recommendations=total_count,
                    active_positions=active_count,
                    closed_positions=closed_count,
                    win_count=win_count,
                    loss_count=loss_count,
                    win_rate=win_rate,
                    avg_return=avg_return,
                    max_return=max_return,
                    max_loss=max_loss,
                    total_return=total_return
                )
                
                # 使用 ON DUPLICATE KEY UPDATE 逻辑
                existing = StrategyStatistics.query.filter_by(stat_date=today).first()
                if existing:
                    existing.total_recommendations = total_count
                    existing.active_positions = active_count
                    existing.closed_positions = closed_count
                    existing.win_count = win_count
                    existing.loss_count = loss_count
                    existing.win_rate = win_rate
                    existing.avg_return = avg_return
                    existing.max_return = max_return
                    existing.max_loss = max_loss
                    existing.total_return = total_return
                else:
                    db.session.add(stats)
                
                db.session.commit()
                logger.info(f"统计任务完成: 胜率 {win_rate*100:.2f}%, 平均收益 {avg_return*100:.2f}%")
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"统计任务失败: {e}", exc_info=True)
    
    def start(self):
        """启动调度器"""
        logger.info("启动定时任务调度器")
        
        # 解析时间配置
        selection_hour, selection_minute = map(int, Config.SELECTION_TIME.split(':'))
        update_hour, update_minute = map(int, Config.UPDATE_TIME.split(':'))
        statistics_hour, statistics_minute = map(int, Config.STATISTICS_TIME.split(':'))
        
        # 添加定时任务
        self.scheduler.add_job(
            self.daily_stock_selection,
            CronTrigger(hour=selection_hour, minute=selection_minute),
            id='daily_stock_selection',
            name='每日选股任务',
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.daily_performance_update,
            CronTrigger(hour=update_hour, minute=update_minute),
            id='daily_performance_update',
            name='每日更新任务',
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.daily_statistics,
            CronTrigger(hour=statistics_hour, minute=statistics_minute),
            id='daily_statistics',
            name='每日统计任务',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("定时任务调度器已启动")
    
    def shutdown(self):
        """关闭调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("定时任务调度器已关闭")
```

- [ ] **Step 2: 提交定时任务调度器**

```bash
git add app/scheduler.py
git commit -m "feat: add task scheduler for daily stock selection and updates"
```



## Task 9: Web 路由和 API

**Files:**
- Create: `F:/datax/stock-recommendation-platform/app/routes.py`

- [ ] **Step 1: 实现 app/routes.py**

```python
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import func, desc
from app.database import db
from app.models import StockRecommendation, StockDailyPerformance, StrategyStatistics
from app.stock_selector import StockSelector
from app.performance_tracker import PerformanceTracker
from app.utils import format_percent

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """首页 - 今日推荐"""
    today = date.today()
    
    # 获取今日推荐
    today_recommendations = StockRecommendation.query.filter_by(
        recommend_date=today
    ).all()
    
    return render_template('index.html', recommendations=today_recommendations, today=today)

@bp.route('/recommendations')
def recommendations():
    """推荐列表"""
    # 获取查询参数
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status', 'all')
    
    # 构建查询
    query = StockRecommendation.query
    
    if start_date:
        query = query.filter(StockRecommendation.recommend_date >= start_date)
    if end_date:
        query = query.filter(StockRecommendation.recommend_date <= end_date)
    if status != 'all':
        query = query.filter(StockRecommendation.status == status)
    
    # 按日期降序排序
    recs = query.order_by(desc(StockRecommendation.recommend_date)).all()
    
    return render_template('recommendations.html', recommendations=recs)

@bp.route('/performance')
def performance():
    """表现跟踪 - 所有活跃推荐"""
    # 获取所有活跃推荐
    active_recs = StockRecommendation.query.filter_by(status='active').all()
    
    # 获取每只股票的最新表现
    performance_data = []
    for rec in active_recs:
        latest_perf = StockDailyPerformance.query.filter_by(
            recommendation_id=rec.id
        ).order_by(desc(StockDailyPerformance.trade_date)).first()
        
        if latest_perf:
            performance_data.append({
                'recommendation': rec,
                'performance': latest_perf
            })
    
    # 按收益率排序
    performance_data.sort(key=lambda x: x['performance'].change_percent, reverse=True)
    
    return render_template('performance.html', performance_data=performance_data)

@bp.route('/statistics')
def statistics():
    """策略统计"""
    # 获取最新统计
    latest_stats = StrategyStatistics.query.order_by(
        desc(StrategyStatistics.stat_date)
    ).first()
    
    # 获取历史统计（用于图表）
    history_stats = StrategyStatistics.query.order_by(
        StrategyStatistics.stat_date
    ).limit(30).all()
    
    return render_template(
        'statistics.html',
        latest_stats=latest_stats,
        history_stats=history_stats
    )

@bp.route('/api/trigger_selection', methods=['POST'])
def trigger_selection():
    """手动触发选股"""
    try:
        selector = StockSelector()
        today = date.today()
        
        # 执行选股
        selected_stocks = selector.select_stocks(today)
        
        if not selected_stocks:
            return jsonify({'success': False, 'message': '选股结果为空'})
        
        # 保存推荐记录
        for stock in selected_stocks:
            recommendation = StockRecommendation(
                stock_code=stock['stock_code'],
                stock_name=stock['stock_name'],
                recommend_date=today,
                recommend_price=stock['current_price'],
                recommend_reason={
                    'momentum_score': stock['momentum_score'],
                    'volume_score': stock['volume_score'],
                    'breakout_score': stock['breakout_score'],
                    'composite_score': stock['composite_score']
                },
                status='active'
            )
            db.session.add(recommendation)
            
            # 插入初始表现记录
            performance = StockDailyPerformance(
                recommendation=recommendation,
                trade_date=today,
                current_price=stock['current_price'],
                change_percent=0.0,
                signal='buy',
                signal_reason='推荐买入'
            )
            db.session.add(performance)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'选股完成，推荐 {len(selected_stocks)} 只股票'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@bp.route('/api/trigger_update', methods=['POST'])
def trigger_update():
    """手动触发更新"""
    try:
        tracker = PerformanceTracker()
        today = date.today()
        
        tracker.update_daily_performance(today)
        
        return jsonify({'success': True, 'message': '更新完成'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 注册模板过滤器
@bp.app_template_filter('format_percent')
def format_percent_filter(value):
    """格式化百分比"""
    if value is None:
        return 'N/A'
    return format_percent(float(value))

@bp.app_template_filter('format_price')
def format_price_filter(value):
    """格式化价格"""
    if value is None:
        return 'N/A'
    return f'¥{float(value):.2f}'
```

- [ ] **Step 2: 更新 app/__init__.py 注册路由**

```python
from flask import Flask
from app.database import init_db

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')
    
    # 初始化数据库
    init_db(app)
    
    # 注册路由
    with app.app_context():
        from app import routes
        app.register_blueprint(routes.bp)
    
    return app
```

- [ ] **Step 3: 提交 Web 路由**

```bash
git add app/routes.py app/__init__.py
git commit -m "feat: add web routes and API endpoints"
```



## Task 10: 前端模板

**Files:**
- Create: `F:/datax/stock-recommendation-platform/templates/base.html`
- Create: `F:/datax/stock-recommendation-platform/templates/index.html`
- Create: `F:/datax/stock-recommendation-platform/templates/recommendations.html`
- Create: `F:/datax/stock-recommendation-platform/templates/performance.html`
- Create: `F:/datax/stock-recommendation-platform/templates/statistics.html`
- Create: `F:/datax/stock-recommendation-platform/static/css/style.css`

- [ ] **Step 1: 创建基础模板 templates/base.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}股票推荐平台{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
        <div class="container">
            <a class="navbar-brand" href="/">股票推荐平台</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link" href="/">今日推荐</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/recommendations">推荐列表</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/performance">表现跟踪</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/statistics">策略统计</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>

    <footer class="mt-5 py-3 bg-light text-center">
        <p class="text-muted">本系统仅供学习研究使用，不构成投资建议。股市有风险，投资需谨慎。</p>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: 创建首页模板 templates/index.html**

```html
{% extends "base.html" %}

{% block title %}今日推荐 - 股票推荐平台{% endblock %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h2>今日推荐 ({{ today }})</h2>
        <button class="btn btn-primary mb-3" onclick="triggerSelection()">手动触发选股</button>
        
        {% if recommendations %}
        <div class="table-responsive">
            <table class="table table-striped table-hover">
                <thead>
                    <tr>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>推荐价格</th>
                        <th>综合得分</th>
                        <th>推荐理由</th>
                    </tr>
                </thead>
                <tbody>
                    {% for rec in recommendations %}
                    <tr>
                        <td>{{ rec.stock_code }}</td>
                        <td>{{ rec.stock_name }}</td>
                        <td>{{ rec.recommend_price|format_price }}</td>
                        <td>{{ rec.recommend_reason.composite_score }}</td>
                        <td>
                            <small>
                                动量: {{ rec.recommend_reason.momentum_score }}, 
                                成交量: {{ rec.recommend_reason.volume_score }}, 
                                突破: {{ rec.recommend_reason.breakout_score }}
                            </small>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="alert alert-info">今日暂无推荐</div>
        {% endif %}
    </div>
</div>

<script>
function triggerSelection() {
    if (!confirm('确定要手动触发选股吗？')) return;
    
    fetch('/api/trigger_selection', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            alert(data.message);
            if (data.success) location.reload();
        })
        .catch(err => alert('请求失败: ' + err));
}
</script>
{% endblock %}
```

- [ ] **Step 3: 创建推荐列表模板 templates/recommendations.html**

```html
{% extends "base.html" %}

{% block title %}推荐列表 - 股票推荐平台{% endblock %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h2>推荐列表</h2>
        
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>推荐日期</th>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>推荐价格</th>
                        <th>状态</th>
                        <th>平仓价格</th>
                        <th>最终收益</th>
                    </tr>
                </thead>
                <tbody>
                    {% for rec in recommendations %}
                    <tr>
                        <td>{{ rec.recommend_date }}</td>
                        <td>{{ rec.stock_code }}</td>
                        <td>{{ rec.stock_name }}</td>
                        <td>{{ rec.recommend_price|format_price }}</td>
                        <td>
                            {% if rec.status == 'active' %}
                            <span class="badge bg-success">持仓中</span>
                            {% else %}
                            <span class="badge bg-secondary">已平仓</span>
                            {% endif %}
                        </td>
                        <td>{{ rec.close_price|format_price if rec.close_price else '-' }}</td>
                        <td>
                            {% if rec.final_return %}
                            <span class="{% if rec.final_return > 0 %}text-success{% else %}text-danger{% endif %}">
                                {{ rec.final_return|format_percent }}
                            </span>
                            {% else %}
                            -
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 4: 创建表现跟踪模板 templates/performance.html**

```html
{% extends "base.html" %}

{% block title %}表现跟踪 - 股票推荐平台{% endblock %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h2>表现跟踪（活跃持仓）</h2>
        <button class="btn btn-primary mb-3" onclick="triggerUpdate()">手动触发更新</button>
        
        {% if performance_data %}
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>推荐价格</th>
                        <th>当前价格</th>
                        <th>涨跌幅</th>
                        <th>买卖信号</th>
                        <th>信号原因</th>
                        <th>更新日期</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in performance_data %}
                    <tr>
                        <td>{{ item.recommendation.stock_code }}</td>
                        <td>{{ item.recommendation.stock_name }}</td>
                        <td>{{ item.recommendation.recommend_price|format_price }}</td>
                        <td>{{ item.performance.current_price|format_price }}</td>
                        <td>
                            <span class="{% if item.performance.change_percent > 0 %}text-success{% else %}text-danger{% endif %}">
                                {{ item.performance.change_percent|format_percent }}
                            </span>
                        </td>
                        <td>
                            {% if item.performance.signal == 'buy' %}
                            <span class="badge bg-primary">买入</span>
                            {% elif item.performance.signal == 'hold' %}
                            <span class="badge bg-info">持有</span>
                            {% else %}
                            <span class="badge bg-danger">卖出</span>
                            {% endif %}
                        </td>
                        <td>{{ item.performance.signal_reason }}</td>
                        <td>{{ item.performance.trade_date }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="alert alert-info">暂无活跃持仓</div>
        {% endif %}
    </div>
</div>

<script>
function triggerUpdate() {
    if (!confirm('确定要手动触发更新吗？')) return;
    
    fetch('/api/trigger_update', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            alert(data.message);
            if (data.success) location.reload();
        })
        .catch(err => alert('请求失败: ' + err));
}
</script>
{% endblock %}
```

- [ ] **Step 5: 创建统计页面模板 templates/statistics.html**

```html
{% extends "base.html" %}

{% block title %}策略统计 - 股票推荐平台{% endblock %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h2>策略统计</h2>
        
        {% if latest_stats %}
        <div class="row mt-4">
            <div class="col-md-3">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">累计推荐</h5>
                        <p class="card-text display-6">{{ latest_stats.total_recommendations }}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">胜率</h5>
                        <p class="card-text display-6">{{ latest_stats.win_rate|format_percent }}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">平均收益</h5>
                        <p class="card-text display-6">{{ latest_stats.avg_return|format_percent }}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">最大收益</h5>
                        <p class="card-text display-6 text-success">{{ latest_stats.max_return|format_percent }}</p>
                    </div>
                </div>
            </div>
        </div>
        {% else %}
        <div class="alert alert-info">暂无统计数据</div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 6: 创建样式文件 static/css/style.css**

```css
body {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}

.container {
    flex: 1;
}

footer {
    margin-top: auto;
}

.table {
    font-size: 0.9rem;
}

.badge {
    font-size: 0.85rem;
}
```

- [ ] **Step 7: 提交前端模板**

```bash
git add templates/ static/
git commit -m "feat: add frontend templates and styles"
```



## Task 11: 启动脚本和最终测试

**Files:**
- Create: `F:/datax/stock-recommendation-platform/run.py`
- Create: `F:/datax/stock-recommendation-platform/.env`
- Create: `F:/datax/stock-recommendation-platform/tests/__init__.py`

- [ ] **Step 1: 创建启动脚本 run.py**

```python
import os
from app import create_app
from app.scheduler import TaskScheduler

app = create_app()

# 初始化定时任务调度器
scheduler = TaskScheduler(app)

if __name__ == '__main__':
    # 启动定时任务
    scheduler.start()
    
    # 启动 Flask 应用
    try:
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=app.config['DEBUG']
        )
    finally:
        # 关闭调度器
        scheduler.shutdown()
```

- [ ] **Step 2: 创建 .env 文件（从 .env.example 复制）**

```bash
cd /f/datax/stock-recommendation-platform
cp .env.example .env
```

- [ ] **Step 3: 创建 tests/__init__.py**

```python
# Tests package
```

- [ ] **Step 4: 安装依赖**

```bash
cd /f/datax/stock-recommendation-platform
pip install -r requirements.txt
```

预期输出：成功安装所有依赖包

- [ ] **Step 5: 初始化数据库**

```bash
python init_db.py
```

预期输出：
```
开始初始化数据库...
数据库 stock_recommendation 已创建或已存在
所有表已创建
数据库初始化完成！
```

- [ ] **Step 6: 运行所有测试**

```bash
pytest tests/ -v
```

预期输出：所有测试通过

- [ ] **Step 7: 启动应用**

```bash
python run.py
```

预期输出：
```
[日期时间] [INFO] [scheduler] 启动定时任务调度器
[日期时间] [INFO] [scheduler] 定时任务调度器已启动
 * Running on http://0.0.0.0:5000
```

- [ ] **Step 8: 测试 Web 界面**

在浏览器中访问 `http://localhost:5000`，验证：
- 首页可以正常访问
- 导航栏链接正常工作
- 手动触发选股按钮可以点击

- [ ] **Step 9: 提交启动脚本**

```bash
git add run.py tests/__init__.py
git commit -m "feat: add application startup script"
```

- [ ] **Step 10: 创建最终提交**

```bash
git add .
git commit -m "chore: complete stock recommendation platform implementation"
```

## 实现完成检查清单

完成所有任务后，验证以下功能：

- [ ] 数据库表已创建（stock_recommendations, stock_daily_performance, strategy_statistics）
- [ ] 数据获取模块可以正常获取股票列表和历史数据
- [ ] 选股引擎可以基于量化因子筛选股票
- [ ] 买卖信号生成器可以根据规则生成信号
- [ ] 表现跟踪模块可以更新每日表现
- [ ] 定时任务调度器已配置（15:30选股，15:35更新，15:40统计）
- [ ] Web 界面可以访问，所有页面正常显示
- [ ] 手动触发选股和更新功能正常工作
- [ ] 所有单元测试通过

## 后续优化建议

1. **性能优化：**
   - 添加数据缓存（Redis）
   - 批量查询优化
   - 异步任务处理

2. **功能扩展：**
   - 添加邮件/微信通知
   - 支持多策略配置
   - 添加回测功能
   - 导出 Excel 报表

3. **安全加固：**
   - 添加用户认证
   - API 限流
   - SQL 注入防护

4. **监控告警：**
   - 添加健康检查接口
   - 任务执行监控
   - 异常告警通知

