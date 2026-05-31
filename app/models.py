from app.database import db

class StockRecommendation(db.Model):
    """股票推荐记录表"""
    __tablename__ = 'stock_recommendations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stock_code = db.Column(db.String(10), nullable=False, index=True)
    stock_name = db.Column(db.String(50), nullable=False)
    recommend_date = db.Column(db.Date, nullable=False, index=True)
    # 推荐价 = 次日开盘价（盘前还没拉到时为 NULL）
    recommend_price = db.Column(db.Numeric(10, 2), nullable=True)
    # pending=等次日开盘回填；filled=已回填；void=次日停牌/节假日，作废
    price_status = db.Column(
        db.Enum('pending', 'filled', 'void'),
        nullable=False, default='filled', server_default='filled', index=True,
    )
    recommend_reason = db.Column(db.JSON)
    status = db.Column(db.Enum('active', 'closed'), default='active', index=True)
    close_date = db.Column(db.Date)
    close_price = db.Column(db.Numeric(10, 2))
    final_return = db.Column(db.Numeric(10, 4))
    is_watched = db.Column(db.Boolean, nullable=False, default=False, index=True)
    watched_at = db.Column(db.DateTime)
    # 来源：system=系统每日选股；user=用户手动加的
    source = db.Column(
        db.Enum('system', 'user'),
        nullable=False, default='system', server_default='system', index=True,
    )
    # 持仓股数（用户手动填写，用于计算实际盈亏金额）
    shares = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        # 同一只票同一天 + 同来源 唯一（允许用户手动加 + 系统选都有的情况）
        db.UniqueConstraint('stock_code', 'recommend_date', 'source', name='uk_code_date_src'),
        # 高频查询：查所有 active 状态的推荐按日期排序
        db.Index('idx_status_date', 'status', 'recommend_date'),
    )

    # 关系
    daily_performances = db.relationship('StockDailyPerformance', backref='recommendation', lazy='dynamic')

    def __repr__(self):
        return f'<StockRecommendation {self.stock_code} {self.recommend_date}>'

class StockDailyPerformance(db.Model):
    """股票每日表现表"""
    __tablename__ = 'stock_daily_performance'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey('stock_recommendations.id'), nullable=False, index=True)
    trade_date = db.Column(db.Date, nullable=False, index=True)
    current_price = db.Column(db.Numeric(10, 2), nullable=False)
    change_percent = db.Column(db.Numeric(10, 4), nullable=False)
    volume = db.Column(db.BigInteger)
    turnover = db.Column(db.Numeric(20, 2))
    signal = db.Column(db.Enum('buy', 'hold', 'sell'), nullable=False, index=True)
    signal_reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

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
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f'<StrategyStatistics {self.stat_date}>'
