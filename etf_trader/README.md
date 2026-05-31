A股选股+ETF监控系统

## 每日使用
```bash
uv run python quant_model.py    # 价值选股TOP30
uv run python friend_watch.py   # 监控朋友ETF
uv run python daily_pick.py     # 自选股推荐
```

## 安装
```bash
uv sync && uv pip install pymysql
```
