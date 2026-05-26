from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """初始化数据库连接"""
    db.init_app(app)

def get_db():
    """获取数据库会话"""
    return db.session
