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
            db_name = Config.MYSQL_DATABASE.replace('`', '``')
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
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
