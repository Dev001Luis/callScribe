from flask import Flask
from flask_socketio import SocketIO

#    This is the "App Factory" pattern.
#    Instead of creating `app = Flask(__name__)` at the top of a file
#    (which breaks testing and causes circular imports), we wrap it
#    in a function. Anyone who needs the app calls create_app().
#    SocketIO is created here too so it's shared across all files.

socketio = SocketIO()


def create_app():
    flask_app = Flask(
        __name__, template_folder="../templates", static_folder="../static"
    )

    # Load all config values from config.py
    from config import Config

    flask_app.config.from_object(Config)

    # Attach SocketIO to the app
    #    cors_allowed_origins="*" means ANY device on your network
    #    can connect — fine for a local personal tool, never do this
    #    in a production app facing the internet.
    socketio.init_app(
        flask_app,
        cors_allowed_origins="*",
        async_mode=flask_app.config["SOCKETIO_ASYNC_MODE"],
        max_http_buffer_size=10 * 1024 * 1024,  # Allow 10MB of data in the queue
        ping_timeout=120,  # Be VERY patient with the connection
        ping_interval=25,  # Check if phone is alive every 25s
        manage_session=False,  # Slightly lighter for the CPU
    )

    # Register routes (HTTP endpoints like / and /save)
    from app.routes import routes_bp

    flask_app.register_blueprint(routes_bp)

    # Inside create_app() in app/__init__.py
    from config import Config
    import os

    # Ensure recording directories exist on startup
    for path in [Config.AUDIO_DIR, Config.TRANS_DIR]:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            print(f"[*] Initialized directory: {path}")

    return flask_app
