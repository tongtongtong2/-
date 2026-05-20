# 每日股票推荐平台设计文档

**日期：** 2026-05-20  
**项目路径：** F:/datax/stock-recommendation-platform  
**技术栈：** Python, Flask, MySQL, AkShare, APScheduler

## 1. 项目概述

### 1.1 目标
构建一个自动化的股票推荐平台，每天基于量化因子策略推荐 10 只 A 股股票，持续跟踪推荐股票的表现，并提供买卖信号建议。

### 1.2 核心功能
- 每日自动选股：基于量化因子策略筛选 10 只股票
- 表现跟踪：记录每只推荐股票从推荐日至今的涨跌幅
- 买卖信号：根据收益率和技术指标生成买入/持有/卖出建议
- 统计分析：计算策略的胜率、平均收益等指标
- Web 界面：可视化展示推荐、表现和信号

### 1.3 用户场景
- 每天早上查看今日推荐的 10 只股票
- 查看历史推荐股票的当前表现和买卖建议
- 查看策略的整体收益统计

## 2. 系统架构

### 2.1 技术选型

**后端框架：** Flask
- 轻量级，适合中小型项目
- 易于快速开发和部署

**数据源：** AkShare
- 免费开源的 Python 金融数据接口
- 提供 A 股实时和历史行情数据
- 无需注册和 token

**数据库：** MySQL 8.0+
- 关系型数据库，适合结构化数据存储
- 本地部署，账密均为 root

**定时任务：** APScheduler
- Python 原生定时任务库
- 支持 cron 表达式
- 可与 Flask 集成

**前端：** HTML + Bootstrap + Chart.js
- 简单直观的响应式界面
- Chart.js 用于收益曲线可视化

### 2.2 模块划分

```
stock-recommendation-platform/
├── app/
│   ├── __init__.py              # Flask 应用初始化
│   ├── models.py                # 数据库模型
│   ├── data_fetcher.py          # 数据获取模块
│   ├── stock_selector.py        # 选股引擎
│   ├── performance_tracker.py   # 表现跟踪模块
│   ├── signal_generator.py      # 买卖信号生成器
│   ├── scheduler.py             # 定时任务调度器
│   └── routes.py                # Web 路由
├── templates/
│   ├── index.html               # 首页
│   ├── recommendations.html     # 推荐列表
│   ├── performance.html         # 表现跟踪
│   └── statistics.html          # 统计分析
├── static/
│   ├── css/
│   └── js/
├── config.py                    # 配置文件
├── requirements.txt             # 依赖包
├── run.py                       # 启动脚本
└── docs/
    └── superpowers/
        └── specs/
```

## 3. 数据库设计

### 3.1 stock_recommendations（推荐记录表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PRIMARY KEY AUTO_INCREMENT | 主键 |
| stock_code | VARCHAR(10) NOT NULL | 股票代码（如 000001） |
| stock_name | VARCHAR(50) NOT NULL | 股票名称 |
| recommend_date | DATE NOT NULL | 推荐日期 |
| recommend_price | DECIMAL(10,2) NOT NULL | 推荐时价格 |
| recommend_reason | JSON | 推荐理由（各因子得分） |
| status | ENUM('active','closed') DEFAULT 'active' | 状态 |
| close_date | DATE | 平仓日期 |
| close_price | DECIMAL(10,2) | 平仓价格 |
| final_return | DECIMAL(10,4) | 最终收益率 |
| created_at | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | 创建时间 |

**索引：**
- idx_recommend_date: (recommend_date)
- idx_stock_code: (stock_code)
- idx_status: (status)

### 3.2 stock_daily_performance（每日表现表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PRIMARY KEY AUTO_INCREMENT | 主键 |
| recommendation_id | INT NOT NULL | 关联推荐记录 |
| trade_date | DATE NOT NULL | 交易日期 |
| current_price | DECIMAL(10,2) NOT NULL | 当日收盘价 |
| change_percent | DECIMAL(10,4) NOT NULL | 相对推荐价涨跌幅 |
| volume | BIGINT | 成交量 |
| turnover | DECIMAL(20,2) | 成交额 |
| signal | ENUM('buy','hold','sell') NOT NULL | 买卖信号 |
| signal_reason | VARCHAR(200) | 信号原因 |
| created_at | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | 创建时间 |

**索引：**
- idx_recommendation_trade: (recommendation_id, trade_date)
- idx_trade_date: (trade_date)

**外键：**
- FOREIGN KEY (recommendation_id) REFERENCES stock_recommendations(id)

### 3.3 strategy_statistics（策略统计表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PRIMARY KEY AUTO_INCREMENT | 主键 |
| stat_date | DATE NOT NULL UNIQUE | 统计日期 |
| total_recommendations | INT NOT NULL | 累计推荐数量 |
| active_positions | INT NOT NULL | 当前持仓数量 |
| closed_positions | INT NOT NULL | 已平仓数量 |
| win_count | INT NOT NULL | 盈利数量 |
| loss_count | INT NOT NULL | 亏损数量 |
| win_rate | DECIMAL(10,4) | 胜率 |
| avg_return | DECIMAL(10,4) | 平均收益率 |
| max_return | DECIMAL(10,4) | 最大收益 |
| max_loss | DECIMAL(10,4) | 最大亏损 |
| total_return | DECIMAL(10,4) | 累计收益率 |
| created_at | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | 创建时间 |

**索引：**
- idx_stat_date: (stat_date)

## 4. 核心模块设计

### 4.1 数据获取模块（data_fetcher.py）

**职责：** 封装 AkShare 接口，提供统一的数据获取方法。

**核心方法：**

```python
class DataFetcher:
    def get_stock_list() -> pd.DataFrame
        """获取 A 股股票列表"""
        
    def get_stock_daily(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame
        """获取股票历史日线数据"""
        
    def get_stock_realtime(stock_codes: List[str]) -> pd.DataFrame
        """获取股票实时行情"""
        
    def get_stock_indicator(stock_code: str, period: int) -> dict
        """计算技术指标（MACD, RSI, KDJ等）"""
```

**数据缓存：**
- 股票列表每天缓存一次
- 历史数据按日期缓存
- 实时数据不缓存

**错误处理：**
- 网络超时重试 3 次
- API 限流时等待后重试
- 数据异常时记录日志并跳过

### 4.2 选股引擎（stock_selector.py）

**职责：** 基于量化因子策略筛选股票。

**选股策略：**

1. **初筛条件：**
   - 剔除 ST、*ST 股票
   - 剔除停牌股票
   - 剔除上市不足 60 天的新股
   - 剔除成交额小于 1 亿的股票

2. **量化因子：**
   - **动量因子（40% 权重）：**
     - 5 日涨幅：15%
     - 10 日涨幅：15%
     - 20 日涨幅：10%
   
   - **成交量因子（30% 权重）：**
     - 5 日平均成交量 / 20 日平均成交量：20%
     - 成交额放大倍数：10%
   
   - **技术突破因子（30% 权重）：**
     - 突破 20 日高点：15%
     - 突破 60 日高点：15%

3. **评分与排序：**
   - 每个因子标准化到 0-100 分
   - 按权重加权求和
   - 选取综合得分前 10 名

**核心方法：**

```python
class StockSelector:
    def select_stocks(date: str, top_n: int = 10) -> List[dict]
        """执行选股，返回推荐列表"""
        
    def calculate_momentum_score(stock_data: pd.DataFrame) -> float
        """计算动量因子得分"""
        
    def calculate_volume_score(stock_data: pd.DataFrame) -> float
        """计算成交量因子得分"""
        
    def calculate_breakout_score(stock_data: pd.DataFrame) -> float
        """计算技术突破因子得分"""
```

### 4.3 表现跟踪模块（performance_tracker.py）

**职责：** 每日更新所有活跃推荐的表现数据。

**核心逻辑：**

1. 查询所有 status='active' 的推荐记录
2. 获取这些股票的最新价格
3. 计算相对推荐价的涨跌幅
4. 插入 stock_daily_performance 表
5. 如果触发平仓条件，更新 stock_recommendations 状态为 'closed'

**核心方法：**

```python
class PerformanceTracker:
    def update_daily_performance(trade_date: str) -> None
        """更新所有活跃推荐的每日表现"""
        
    def calculate_return(recommend_price: float, current_price: float) -> float
        """计算收益率"""
        
    def check_close_condition(recommendation: dict, current_data: dict) -> bool
        """检查是否触发平仓条件"""
```

**平仓条件：**
- 涨幅 ≥ +10%（止盈）
- 涨幅 ≤ -5%（止损）
- 推荐后持有超过 20 个交易日且收益为负

### 4.4 买卖信号生成器（signal_generator.py）

**职责：** 为每只股票生成买卖信号。

**信号规则：**

**买入信号（buy）：**
- 推荐当天自动标记为 buy

**持有信号（hold）：**
- 涨跌幅在 -5% 到 +10% 之间
- 且技术指标未恶化（5 日均线在 10 日均线之上）

**卖出信号（sell）：**
- 涨幅 ≥ +10%（止盈）
- 涨幅 ≤ -5%（止损）
- 5 日均线跌破 10 日均线且涨幅 < 3%
- 成交量萎缩（低于 20 日均量的 50%）且涨幅 < 5%

**核心方法：**

```python
class SignalGenerator:
    def generate_signal(recommendation: dict, current_data: dict, history_data: pd.DataFrame) -> tuple
        """生成买卖信号，返回 (signal, reason)"""
        
    def check_technical_deterioration(history_data: pd.DataFrame) -> bool
        """检查技术指标是否恶化"""
```

### 4.5 定时任务调度器（scheduler.py）

**职责：** 管理所有定时任务。

**任务列表：**

1. **每日选股任务：**
   - 执行时间：每个交易日 15:30（收盘后）
   - 任务内容：执行选股，插入推荐记录

2. **每日更新任务：**
   - 执行时间：每个交易日 15:35
   - 任务内容：更新所有活跃推荐的表现和信号

3. **统计任务：**
   - 执行时间：每个交易日 15:40
   - 任务内容：计算策略统计指标

4. **交易日判断：**
   - 使用 AkShare 的交易日历接口
   - 非交易日自动跳过

**核心方法：**

```python
class TaskScheduler:
    def start() -> None
        """启动调度器"""
        
    def daily_stock_selection() -> None
        """每日选股任务"""
        
    def daily_performance_update() -> None
        """每日更新任务"""
        
    def daily_statistics() -> None
        """每日统计任务"""
        
    def is_trading_day(date: str) -> bool
        """判断是否为交易日"""
```

## 5. Web 界面设计

### 5.1 路由设计

| 路由 | 方法 | 说明 |
|------|------|------|
| / | GET | 首页，展示今日推荐 |
| /recommendations | GET | 推荐列表（支持日期筛选） |
| /performance | GET | 表现跟踪（所有活跃推荐） |
| /statistics | GET | 策略统计 |
| /api/trigger_selection | POST | 手动触发选股 |
| /api/trigger_update | POST | 手动触发更新 |

### 5.2 页面功能

**首页（index.html）：**
- 展示今日推荐的 10 只股票
- 显示股票代码、名称、推荐价格、推荐理由
- 提供"手动触发选股"按钮

**推荐列表（recommendations.html）：**
- 按日期展示历史推荐
- 支持日期范围筛选
- 显示每只股票的当前状态（active/closed）和收益率

**表现跟踪（performance.html）：**
- 展示所有活跃推荐的实时表现
- 显示当前价格、涨跌幅、买卖信号
- 按收益率排序
- 高亮显示卖出信号

**策略统计（statistics.html）：**
- 展示策略的整体表现
- 胜率、平均收益、最大收益/亏损
- 累计收益曲线图（Chart.js）
- 按月/季度统计

## 6. 配置管理

### 6.1 配置文件（config.py）

```python
class Config:
    # 数据库配置
    MYSQL_HOST = 'localhost'
    MYSQL_PORT = 3306
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = 'root'
    MYSQL_DATABASE = 'stock_recommendation'
    
    # Flask 配置
    SECRET_KEY = 'your-secret-key'
    DEBUG = True
    
    # 选股参数
    TOP_N_STOCKS = 10
    MIN_MARKET_CAP = 100000000  # 最小市值 1 亿
    MIN_VOLUME = 100000000      # 最小成交额 1 亿
    
    # 止盈止损
    TAKE_PROFIT = 0.10   # 10%
    STOP_LOSS = -0.05    # -5%
    MAX_HOLD_DAYS = 20   # 最大持有天数
    
    # 定时任务
    SELECTION_TIME = '15:30'
    UPDATE_TIME = '15:35'
    STATISTICS_TIME = '15:40'
```

### 6.2 环境变量支持

支持通过环境变量覆盖配置：
- MYSQL_PASSWORD
- SECRET_KEY
- DEBUG

## 7. 数据流程

### 7.1 每日选股流程

```
1. 判断是否为交易日
   ↓
2. 获取所有 A 股列表
   ↓
3. 初筛（剔除 ST、停牌、新股等）
   ↓
4. 获取候选股票的历史数据（60 日）
   ↓
5. 计算各因子得分
   ↓
6. 综合评分排序
   ↓
7. 选取前 10 名
   ↓
8. 插入 stock_recommendations 表
   ↓
9. 插入初始 stock_daily_performance 记录（signal=buy）
```

### 7.2 每日更新流程

```
1. 查询所有 status='active' 的推荐
   ↓
2. 获取这些股票的最新价格和成交量
   ↓
3. 对每只股票：
   a. 计算涨跌幅
   b. 生成买卖信号
   c. 插入 stock_daily_performance 记录
   d. 如果信号为 sell，更新 stock_recommendations 状态为 closed
   ↓
4. 完成
```

### 7.3 统计计算流程

```
1. 查询所有推荐记录
   ↓
2. 计算：
   - 总推荐数
   - 活跃持仓数
   - 已平仓数
   - 盈利/亏损数量
   - 胜率
   - 平均收益率
   - 最大收益/亏损
   ↓
3. 插入 strategy_statistics 表
```

## 8. 错误处理

### 8.1 数据获取错误

- **网络超时：** 重试 3 次，间隔 5 秒
- **API 限流：** 等待 60 秒后重试
- **数据缺失：** 记录日志，跳过该股票
- **数据异常：** 记录日志，使用前一日数据

### 8.2 数据库错误

- **连接失败：** 重试 3 次，记录日志
- **插入冲突：** 忽略（ON DUPLICATE KEY UPDATE）
- **查询超时：** 记录日志，返回空结果

### 8.3 定时任务错误

- **任务执行失败：** 记录详细日志，发送通知（可选）
- **任务超时：** 设置 30 分钟超时，超时后强制终止

## 9. 日志记录

### 9.1 日志级别

- **DEBUG：** 详细的调试信息
- **INFO：** 关键操作（选股完成、更新完成）
- **WARNING：** 警告信息（数据缺失、API 限流）
- **ERROR：** 错误信息（网络失败、数据库错误）

### 9.2 日志格式

```
[2026-05-20 15:30:00] [INFO] [stock_selector] 选股完成，推荐 10 只股票
[2026-05-20 15:35:00] [INFO] [performance_tracker] 更新 25 只活跃推荐的表现
[2026-05-20 15:35:05] [WARNING] [data_fetcher] 股票 000001 数据获取失败，重试中
[2026-05-20 15:35:10] [ERROR] [data_fetcher] 股票 000001 数据获取失败，已跳过
```

### 9.3 日志存储

- 日志文件：`logs/app.log`
- 按日期轮转：每天一个文件
- 保留 30 天

## 10. 测试策略

### 10.1 单元测试

- 数据获取模块：模拟 AkShare 返回数据
- 选股引擎：使用历史数据验证选股结果
- 信号生成器：验证各种场景下的信号正确性

### 10.2 集成测试

- 完整流程测试：从选股到更新到统计
- 数据库操作测试：插入、查询、更新

### 10.3 回测

- 使用历史数据回测策略表现
- 验证胜率和收益率是否符合预期

## 11. 部署方案

### 11.1 本地部署

1. 安装 Python 3.8+
2. 安装依赖：`pip install -r requirements.txt`
3. 配置 MySQL 数据库
4. 初始化数据库：`python init_db.py`
5. 启动应用：`python run.py`
6. 访问：`http://localhost:5000`

### 11.2 生产部署（可选）

- 使用 Gunicorn 作为 WSGI 服务器
- 使用 Nginx 作为反向代理
- 使用 Supervisor 管理进程
- 配置 HTTPS

## 12. 未来扩展

### 12.1 功能扩展

- 邮件/微信通知：每日推荐和卖出信号推送
- 多策略支持：支持配置多种选股策略
- 回测系统：可视化回测不同参数的策略表现
- 实盘对接：对接券商 API 实现自动交易

### 12.2 性能优化

- 数据缓存：使用 Redis 缓存热点数据
- 异步任务：使用 Celery 处理耗时任务
- 数据库优化：分表、索引优化

## 13. 风险提示

**本系统仅供学习和研究使用，不构成投资建议。股市有风险，投资需谨慎。**

- 量化策略的历史表现不代表未来收益
- 市场环境变化可能导致策略失效
- 建议结合基本面分析和风险管理
- 不要投入超过承受能力的资金

## 14. 依赖包清单

```
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
PyMySQL==1.1.0
APScheduler==3.10.4
akshare==1.13.0
pandas==2.1.4
numpy==1.26.2
requests==2.31.0
python-dotenv==1.0.0
```

## 15. 总结

本设计文档详细描述了每日股票推荐平台的架构、模块、数据库、流程和实现细节。系统采用模块化设计，各模块职责清晰，易于维护和扩展。通过量化因子策略实现自动选股，通过定时任务实现自动化运行，通过 Web 界面提供友好的用户体验。
