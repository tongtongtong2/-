# 每日股票推荐平台

基于 **Flask + MySQL + AkShare + APScheduler** 的 A 股每日量化推荐系统：每个交易日盘后自动选股 10 只、跟踪历史推荐表现、生成买卖信号、并提供 Web 界面。

> 仅供学习与研究使用，不构成任何投资建议。股市有风险，投资需谨慎。

## 功能

- **每日选股**：动量 (40%) + 成交量 (30%) + 突破 (30%) 三因子打分，每日 15:30 自动跑
- **表现跟踪**：每日 15:35 更新所有活跃推荐的当日数据，自动写入 `stock_daily_performance`
- **买卖信号**：止盈 +10% / 止损 -5% / 超期 / 均线死叉 / 量能萎缩 等多重规则
- **策略统计**：胜率、平均收益、最大盈亏、累计收益，每日 15:40 入库
- **Web 界面**：今日推荐、历史推荐筛选、活跃表现、统计图表（Chart.js）
- **手动触发**：页面按钮 / `POST /api/trigger_selection`、`/api/trigger_update`

## 技术栈

| 模块 | 选型 |
|------|------|
| 后端 | Flask 3.0 + Flask-SQLAlchemy 3.1 |
| 数据库 | MySQL 8.0+（PyMySQL 驱动） |
| 数据源 | AkShare 1.13（免费 A 股行情，无需 token） |
| 调度 | APScheduler 3.10（BackgroundScheduler，cron） |
| 前端 | Jinja2 + Bootstrap 5 + Chart.js（CDN） |

## 快速开始

```bash
# 1. 安装依赖（建议先创建 venv）
pip install -r requirements.txt

# 2. 拷贝并按需修改环境配置
cp .env.example .env

# 3. 初始化数据库（自动建库 + 建表）
python init_db.py

# 4. 启动应用（同时启动定时调度器）
python run.py
```

打开浏览器访问 http://localhost:5000。

## 目录结构

```
stock-recommendation-platform/
├── app/
│   ├── __init__.py            # Flask 应用工厂
│   ├── database.py            # SQLAlchemy 实例
│   ├── models.py              # 三张表的 ORM 模型
│   ├── utils.py               # 日志、交易日、重试装饰器
│   ├── data_fetcher.py        # AkShare 数据访问层
│   ├── stock_selector.py      # 多因子选股引擎
│   ├── signal_generator.py    # 买卖信号生成
│   ├── performance_tracker.py # 每日表现跟踪 + 平仓 + 统计
│   ├── scheduler.py           # APScheduler 任务
│   └── routes.py              # Web 路由 + JSON API
├── templates/                 # Jinja2 模板
├── static/                    # 静态资源（css/js）
├── tests/                     # pytest 测试
├── docs/superpowers/          # 设计文档与实现计划
├── config.py                  # 配置类（读取 .env）
├── init_db.py                 # 建库脚本
├── run.py                     # 入口脚本
└── requirements.txt
```

## 数据库表

- `stock_recommendations` — 推荐主表（持仓状态、平仓价、最终收益）
- `stock_daily_performance` — 每日表现明细 + 当日信号
- `strategy_statistics` — 按日策略统计快照

详见 `docs/superpowers/specs/2026-05-20-stock-recommendation-platform-design.md`。

## 路由

| 路径 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 今日推荐 |
| `/recommendations` | GET | 历史推荐（支持日期 + 状态筛选） |
| `/performance` | GET | 活跃推荐表现，按涨跌幅排序 |
| `/statistics` | GET | 策略统计 + Chart.js 曲线 |
| `/api/recommendations?date=YYYY-MM-DD` | GET | 推荐 JSON |
| `/api/stats_chart?days=60` | GET | 统计曲线数据 |
| `/api/trigger_selection` | POST | 手动选股 |
| `/api/trigger_update` | POST | 手动更新 + 重算统计 |

## 测试

```bash
pytest -q
```

## 注意

- AkShare 数据来自新浪、东财等公开接口，受网络与限频影响，长时间无响应属正常现象，重试装饰器会自动恢复。
- 默认排除 ST/退市/688 科创板/北交所代码，可在 `app/stock_selector.py::_prefilter` 调整。
- 如需在生产环境运行，建议改用 Gunicorn + supervisor，并将 `DEBUG=False`。
