"""Flask应用工厂 — create_app模式"""
from pathlib import Path

from flask import Flask

from config import SECRET_KEY


def create_app() -> Flask:
    """创建并配置Flask应用

    Returns:
        配置好的Flask实例
    """
    root = Path(__file__).resolve().parent

    app = Flask(
        __name__,
        template_folder=str(root / 'templates'),
        static_folder=str(root / 'static'),
    )
    app.config['SECRET_KEY'] = SECRET_KEY

    # 注册路由
    from web.routes import register_routes
    register_routes(app)

    # 错误处理
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({'error': str(e.description) if e.description else 'Bad request'}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({'error': 'Internal server error'}), 500

    return app
