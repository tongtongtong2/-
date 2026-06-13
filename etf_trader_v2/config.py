"""配置中心 — 从环境变量读取，提供安全默认值"""
import os
from pathlib import Path

# === 项目根目录 ===
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "etf.db"

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)

# === ETF Pool（19只，唯一权威来源）===
POOL: dict[str, str] = {
    '562500': '机器人ETF',   '513100': '纳指ETF',
    '159949': '创业板50',    '515700': '新能源车',
    '159755': '电池ETF',     '561700': '电力ETF',
    '515790': '光伏ETF华泰', '515880': '通信ETF',
    '159996': '家电ETF',     '516880': '光伏ETF银华',
    '513180': '恒生科技',    '159605': '中概互联广发',
    '159607': '中概互联嘉实','159751': '港股通科技',
    '159711': '港股通50华夏','159726': '港股高股息',
    '159792': '港股互联网',  '513050': '中概互联ETF',
}

# === 布林参数 ===
BOLL_OVERHEAT: float = 0.90
BOLL_OVERSOLD: float = 0.25

# === 策略参数 ===
MAX_HOLD: int = 6
STOP_LOSS: float = -0.08

# === 新浪API ===
SINA_API_URL: str = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData?symbol={market}{symbol}&scale=240&ma=no&datalen=5000"
)
FETCH_DELAY: float = float(os.getenv("FETCH_DELAY", "0.2"))
FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "30"))

# === Flask ===
DEBUG: bool = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
HOST: str = os.getenv("FLASK_HOST", "127.0.0.1")
PORT: int = int(os.getenv("FLASK_PORT", "5000"))
SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "etf-bollinger-v2-2026")
