import eventlet

eventlet.monkey_patch()

import threading
from app import create_app, socketio


# 🎓 JUNIOR NOTE: This is the only file you run directly.
#    `python run.py` starts the Flask-SocketIO server.
#    We use socketio.run() instead of app.run() because SocketIO
#    needs to wrap the server to handle WebSocket upgrades.

app = create_app()

# 🎓 WHY import socket_events HERE and not inside create_app()?
#    socket_events.py uses @socketio.on(...) decorators. Python runs
#    those decorators the moment the file is imported — that IS the
#    registration. No explicit "call" is needed.
#    But if we import it inside create_app(), there's a subtle risk:
#    the module might be cached by Python and NOT re-executed on the
#    second call. Importing it here, AFTER create_app(), guarantees
#    the app+socketio are fully initialised first, and the decorators
#    register against a live, ready socketio object.
import app.socket_events  # noqa — side-effect import (registers all @socketio.on handlers)


def preload_whisper():
    """
    🎓 WHY preload? Whisper is lazy-loaded (only downloads+initialises
       on first use). Without this, the FIRST time you press Start and
       speak, nothing happens for 20-30 seconds while the model loads.
       By loading it in a background thread at startup, it's ready
       before you ever press a button.
       'daemon=True' means this thread won't block the app from exiting.
    """
    print("[Startup] Pre-loading Whisper model in background...")
    try:
        from app.transcriber import get_whisper_model

        get_whisper_model()  # this triggers the download + load
        print("[Startup] ✓ Whisper model ready.")
    except Exception as e:
        print(f"[Startup] ✗ Whisper preload failed: {e}")
        print("[Startup]   Make sure faster-whisper is installed:")
        print("[Startup]   pip install faster-whisper")


if __name__ == "__main__":
    print("=" * 50)
    print("  🎙️  CallScribe starting...")
    print("  Open:  http://localhost:5000")
    print("  On your Android tablet, open:")
    print("  http://<your-pc-ip>:5000")
    print("=" * 50)

    # Start Whisper preload in background (non-blocking)
    threading.Thread(target=preload_whisper, daemon=True).start()

    socketio.run(
        app,
        host="0.0.0.0",  # 0.0.0.0 = accessible from other devices on LAN
        port=5000,
        debug=False,  # 🎓 debug=False avoids the reloader forking the process
        use_reloader=False,  # reloader conflicts with ML model loading
        allow_unsafe_werkzeug=True,
    )
