"""项目启动入口：创建 Flask app + 启动定时调度器。"""
from __future__ import annotations

import os

# 在导入任何会发起 HTTP 的模块（akshare/requests）之前，先清掉代理环境变量。
# 东方财富等行情接口都是国内站点，走代理（Clash 等）反而会断连。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from app import create_app
from app.scheduler import TaskScheduler
from app.utils import setup_logger


def main() -> None:
    setup_logger()
    app = create_app()

    scheduler = TaskScheduler(app)
    scheduler.start()

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=app.debug, use_reloader=False)


if __name__ == "__main__":
    main()
