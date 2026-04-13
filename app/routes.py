import os
from flask import Blueprint, render_template, jsonify, send_from_directory
from config import Config

# 🎓 JUNIOR NOTE: A Blueprint is Flask's way of organising routes into
#    modules. Instead of dumping every route in one giant file, we group
#    related routes. Here we have the "dashboard" blueprint.
#    It gets registered onto the main app in app/__init__.py.

routes_bp = Blueprint("routes", __name__)


@routes_bp.route("/")
def dashboard():
    """Serve the main dashboard page."""
    return render_template("dashboard.html")


@routes_bp.route("/api/sessions")
def list_sessions():
    """
    Return a JSON list of saved sessions (files on disk).
    The frontend calls this to populate the history panel.
    """
    sessions = []
    try:
        audio_files = set(os.listdir(Config.AUDIO_DIR))
        trans_files = set(os.listdir(Config.TRANS_DIR))

        for fname in sorted(audio_files, reverse=True):   # newest first
            if not fname.endswith(".wav"):
                continue
            base = fname[:-4]  # strip .wav
            sessions.append({
                "name":       base,
                "audio":      fname,
                "transcript": f"{base}.txt" if f"{base}.txt" in trans_files else None,
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(sessions)


@routes_bp.route("/api/transcript/<filename>")
def get_transcript(filename):
    """Return the text content of a saved transcript."""
    # Security: only allow .txt files, no path traversal
    if not filename.endswith(".txt") or ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400

    path = os.path.join(Config.TRANS_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"content": content})


@routes_bp.route("/api/download/audio/<filename>")
def download_audio(filename):
    """Stream a WAV file for download/playback."""
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(Config.AUDIO_DIR, filename, as_attachment=True)


@routes_bp.route("/api/delete/<name>", methods=["DELETE"])
def delete_session(name):
    """
    Delete both audio and transcript files for a session.
    🎓 BUG FIX: route variable <name> must match the function parameter name.
       Previously it was <n> in the route but 'name' in the function — Flask
       would raise a TypeError because it couldn't map the argument.
    """
    if ".." in name or "/" in name:
        return jsonify({"error": "Invalid name"}), 400

    deleted = []
    for ext, folder in [(".wav", Config.AUDIO_DIR), (".txt", Config.TRANS_DIR)]:
        path = os.path.join(folder, f"{name}{ext}")
        if os.path.exists(path):
            os.remove(path)
            deleted.append(f"{name}{ext}")

    if not deleted:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({"deleted": deleted})
