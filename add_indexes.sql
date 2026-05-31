-- 股票模型 MySQL 索引优化
-- 数据库: stock_recommendation
-- 执行方式: mysql -u root -p stock_recommendation < add_indexes.sql

USE stock_recommendation;

-- ============================================================
-- 1. stock_recommendations: (status, recommend_date) 复合索引
--    覆盖查询："查所有 active 状态的推荐，按日期排列"
-- ============================================================
ALTER TABLE stock_recommendations
  ADD INDEX idx_status_date (status, recommend_date);

-- ============================================================
-- 2. stock_daily_performance: recommendation_id 独立索引
--    覆盖：JOIN 回 stock_recommendations、ON DELETE CASCADE 查找
--    （已有复合索引 idx_recommendation_trade，但独立 FK 索引仍有必要）
-- ============================================================
ALTER TABLE stock_daily_performance
  ADD INDEX idx_recommendation_id (recommendation_id);

-- ============================================================
-- 3. stock_daily_performance: signal 索引
--    覆盖查询："按信号类型筛选" / "统计 buy/hold/sell 比例"
-- ============================================================
ALTER TABLE stock_daily_performance
  ADD INDEX idx_signal (signal);

-- ============================================================
-- 验证
-- ============================================================
SHOW INDEX FROM stock_recommendations;
SHOW INDEX FROM stock_daily_performance;
SHOW INDEX FROM strategy_statistics;
