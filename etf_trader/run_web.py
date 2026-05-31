"""个人选股平台 Web — 启动入口
用法: uv run python run_web.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from web.app import app

if __name__ == '__main__':
    print("📊 个人选股平台")
    print("   http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
