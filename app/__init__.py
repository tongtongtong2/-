from flask import Flask
from config import Config
from app.database import init_db


def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(Config)
    Config.init_app(app)

    init_db(app)

    from app import routes
    app.register_blueprint(routes.bp)

    return app
