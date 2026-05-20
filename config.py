import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration class"""

    # MySQL Database Configuration
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    try:
        MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    except ValueError:
        raise ValueError("MYSQL_PORT must be a valid integer")
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'root')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'stock_recommendation')

    # SQLAlchemy Configuration
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@"
        f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # Flask Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

    # Stock Selection Parameters
    try:
        TOP_N_STOCKS = int(os.getenv('TOP_N_STOCKS', 10))
    except ValueError:
        raise ValueError("TOP_N_STOCKS must be a valid integer")
    try:
        MIN_VOLUME = int(os.getenv('MIN_VOLUME', 100000000))
    except ValueError:
        raise ValueError("MIN_VOLUME must be a valid integer")

    # Trading Parameters
    try:
        TAKE_PROFIT = float(os.getenv('TAKE_PROFIT', 0.10))
    except ValueError:
        raise ValueError("TAKE_PROFIT must be a valid float")
    try:
        STOP_LOSS = float(os.getenv('STOP_LOSS', -0.05))
    except ValueError:
        raise ValueError("STOP_LOSS must be a valid float")
    try:
        MAX_HOLD_DAYS = int(os.getenv('MAX_HOLD_DAYS', 20))
    except ValueError:
        raise ValueError("MAX_HOLD_DAYS must be a valid integer")

    # Scheduler Times (24-hour format)
    SELECTION_TIME = os.getenv('SELECTION_TIME', '15:30')
    UPDATE_TIME = os.getenv('UPDATE_TIME', '15:35')
    STATISTICS_TIME = os.getenv('STATISTICS_TIME', '15:40')

    # Logging Configuration
    LOG_DIR = os.getenv('LOG_DIR', 'logs')
    LOG_FILE = os.getenv('LOG_FILE', 'app.log')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    @classmethod
    def init_app(cls, app):
        """Initialize application with configuration"""
        # Create logs directory if it doesn't exist
        os.makedirs(cls.LOG_DIR, exist_ok=True)
