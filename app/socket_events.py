import threading
import numpy as np
import os
import datetime
from flask import request
from flask_socketio import emit

from app import socketio
from app.audio_processor import AudioProcessor
from app.transcriber import transcribe_chunk
from config import Config

# 🎓 JUNIOR NOTE: WebSocket events work like this:
#    Browser emits  →  server listens with @socketio.on("event_name")
#    Server emits   →  browser listens with socket.on("event_name", ...)
#
#    Think of it as a two-way radio. Either side can talk at any time,
#    unlike HTTP where the browser always has to ask first.
#
#    The @socketio.on(...) decorators below run the moment Python
#    IMPORTS this file — that is the registration. No explicit call needed.
#    You can verify this worked by seeing the line printed below:

print("[SocketEvents] ✓ Socket event handlers registered.")


# ── Session state ─────────────────────────────────────────────────────
# 🎓 We store state per session_id (one per connected browser tab).
#    Using a dict keyed by sid (socket ID) lets multiple sessions
#    run independently — e.g. you open the app on both phone and tablet.

_sessions: dict[str, dict] = {}


def _get_session(sid: str) -> dict:
    if sid not in _sessions:
        _sessions[sid] = {
            "processor": AudioProcessor(),
            "all_samples": np.array([], dtype=np.float32),  # full recording
            "transcript": [],  # list of segment dicts
            "worker_thread": None,
            "running": False,
        }
    return _sessions[sid]


# ── Connection lifecycle ───────────────────────────────────────────────


@socketio.on("connect")
def on_connect():
    print(f"[Socket] Client connected: {request.sid}")
    emit("status", {"message": "Connected to CallScribe server ✓"})


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    print(f"[Socket] Client disconnected: {sid}")
    if sid in _sessions:
        _sessions[sid]["running"] = False
        del _sessions[sid]


# ── Recording controls ────────────────────────────────────────────────


@socketio.on("start_recording")
def on_start_recording():
    """Browser pressed START — begin buffering and transcribing."""
    sid = request.sid
    session = _get_session(sid)

    if session["running"]:
        emit("error", {"message": "Already recording."})
        return

    session["processor"].start()
    session["all_samples"] = np.array([], dtype=np.float32)
    session["transcript"] = []
    session["running"] = True

    # 🎓 We run the transcription loop in a BACKGROUND THREAD.
    #    Why? Transcription takes 1-3 seconds per chunk. If we ran it
    #    in the main thread, the server would freeze and couldn't
    #    receive any more audio while it was thinking. Background thread
    #    = server stays responsive.
    t = threading.Thread(target=_transcription_loop, args=(sid,), daemon=True)
    session["worker_thread"] = t
    t.start()

    emit("recording_started", {"message": "Recording started"})
    print(f"[Session {sid[:6]}] Recording started")


@socketio.on("pause_recording")
def on_pause_recording():
    sid = request.sid
    session = _get_session(sid)
    session["processor"].pause()
    emit("recording_paused", {"message": "Paused"})
    print(f"[Session {sid[:6]}] Paused")


@socketio.on("resume_recording")
def on_resume_recording():
    sid = request.sid
    session = _get_session(sid)
    session["processor"].resume()
    emit("recording_resumed", {"message": "Resumed"})
    print(f"[Session {sid[:6]}] Resumed")


@socketio.on("end_recording")
def on_end_recording():
    """Triggered when the user hits STOP."""
    sid = request.sid
    session = _get_session(sid)

    if not session["running"]:
        return

    session["running"] = False

    # 1. FINAL FLUSH: Transcribe any leftover audio in the buffer
    # This captures the last few words that didn't make a full 4s chunk
    try:
        remaining = session["processor"].stop()
        if remaining is not None and len(remaining) > 0:
            result = transcribe_chunk(remaining)
            if result:
                session["transcript"].extend(result)
                # Send last bit to Kivy/Browser
                socketio.emit("transcript_chunk", {"segments": result}, to=sid)
    except Exception as e:
        print(f"[Server] Error during final flush: {e}")

    # 2. THE SAVE BLOCK: Write the file immediately
    if session["transcript"]:
        # Create a unique filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"transcript_{timestamp}.txt"

        # Ensure the directory exists (Junior safety check!)
        os.makedirs(Config.TRANS_DIR, exist_ok=True)

        filepath = os.path.join(Config.TRANS_DIR, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                for seg in session["transcript"]:
                    start_time = seg.get("start", 0)
                    text = seg.get("text", "").strip()
                    f.write(f"[{start_time}s] {text}\n")

            print(f"✅ [Server] Saved transcription: {filepath}")
        except Exception as e:
            print(f"❌ [Server] Failed to write file: {e}")
    else:
        print("⚠️ [Server] End received, but transcript list was empty.")

    # 3. Cleanup: Tell the UI we are done
    emit("recording_ended", {"message": "Saved to recordings/transcriptions/"})


@socketio.on("delete_recording")
def on_delete_recording():
    """Browser pressed DELETE — discard everything, reset state."""
    sid = request.sid
    if sid in _sessions:
        _sessions[sid]["running"] = False
        _sessions[sid]["processor"].stop()
        _sessions[sid]["all_samples"] = np.array([], dtype=np.float32)
        _sessions[sid]["transcript"] = []
    emit("recording_deleted", {"message": "Recording deleted"})
    print(f"[Session {sid[:6]}] Recording deleted")


# ── Audio data stream ─────────────────────────────────────────────────


@socketio.on("audio_chunk")
def on_audio_chunk(data):
    sid = request.sid
    session = _get_session(sid)
    print(f"Received chunk: {len(data)} bytes")

    # 1. Handle different data formats (Browser vs Kivy)
    if isinstance(data, dict):
        raw = data.get("audio")
    else:
        raw = data  # Kivy sends raw bytes directly

    if raw is None or not session.get("running"):
        return

    # 2. Feed the processor
    session["processor"].add_audio(raw)

    # 3. Accumulate for the final WAV save
    # Convert bytes to float32 for the master recording array
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    session["all_samples"] = np.concatenate([session["all_samples"], samples])


# ── Save ──────────────────────────────────────────────────────────────


@socketio.on("save_recording")
def on_save_recording(data):
    """
    Browser sends the chosen session name. We save:
      - recordings/audio/<name>.wav
      - recordings/transcriptions/<name>.txt
    """
    sid = request.sid
    session = _get_session(sid)
    name = (data.get("name") or "").strip()

    # Default name = datetime if user didn't provide one
    if not name:
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"session_{now}"

    # Sanitise: remove characters that aren't safe in filenames
    safe_name = "".join(c for c in name if c.isalnum() or c in "._- ")

    audio_path = os.path.join(Config.AUDIO_DIR, f"{safe_name}.wav")
    trans_path = os.path.join(Config.TRANS_DIR, f"{safe_name}.txt")

    # Save WAV
    try:
        wav_bytes = AudioProcessor.samples_to_wav_bytes(session["all_samples"])
        with open(audio_path, "wb") as f:
            f.write(wav_bytes)
    except Exception as e:
        emit("error", {"message": f"Failed to save audio: {e}"})
        return

    # Save transcript as plain text
    try:
        lines = []
        for seg in session["transcript"]:
            lines.append(
                f"[{seg['start']}s → {seg['end']}s] {seg['speaker']}: {seg['text']}"
            )
        with open(trans_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        emit("error", {"message": f"Failed to save transcript: {e}"})
        return

    emit(
        "saved",
        {
            "message": f"Saved as '{safe_name}'",
            "audio_file": f"{safe_name}.wav",
            "trans_file": f"{safe_name}.txt",
        },
    )
    print(f"[Session {sid[:6]}] Saved → {safe_name}")


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    if sid in _sessions:
        print(f"[Session {sid[:6]}] Browser closed. Stopping recording.")
        _sessions[sid]["running"] = False
        # We don't delete yet so they can reconnect/save if we implement that later


# ── Background transcription loop ─────────────────────────────────────


def _transcription_loop(sid: str):
    """
    Runs in a background thread for the duration of a recording session.
    Every 0.5s it checks if a full chunk is ready, transcribes it,
    and emits the result back to the specific browser tab (sid).

    🎓 We use socketio.emit(..., to=sid) to send ONLY to this user.
       Without `to=sid` we'd broadcast to EVERY connected client — a bug!
    """
    import time

    session = _sessions.get(sid)
    if session is None:
        return

    while session["running"]:
        chunk = session["processor"].get_chunk()
        if chunk is not None:
            try:
                segments = transcribe_chunk(chunk)
                if segments:
                    session["transcript"].extend(segments)
                    # Emit to just this client
                    socketio.emit("transcript_chunk", {"segments": segments}, to=sid)
            except Exception as e:
                print(f"[Transcription error] {e}")
                socketio.emit("error", {"message": f"Transcription error: {e}"}, to=sid)

        time.sleep(0.3)  # 300ms polling interval — light on CPU

    print(f"[Session {sid[:6]}] Transcription loop ended")
