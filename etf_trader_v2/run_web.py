#!/usr/bin/env python3
"""Web入口 — 启动Flask开发服务器

用法:
    python run_web.py                     # 默认 127.0.0.1:5000
    FLASK_HOST=0.0.0.0 python run_web.py  # 监听所有接口
    FLASK_PORT=8080 python run_web.py      # 自定义端口
"""
from config import HOST, PORT, DEBUG
from web.app import create_app

if __name__ == '__main__':
    app = create_app()
    print(f"\n{'='*50}")
    print(f"  ETF Trader V2 Web 平台")
    print(f"  地址: http://{HOST}:{PORT}")
    print(f"  调试: {'ON' if DEBUG else 'OFF'}")
    print(f"{'='*50}\n")
    app.run(host=HOST, port=PORT, debug=DEBUG)
