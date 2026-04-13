import os

# ─────────────────────────────────────────────
#  CallScribe Configuration
#  🎓 JUNIOR NOTE: Keep ALL magic values here.
#  Never hardcode paths or numbers inside logic files.
#  If you need to change something, you change it HERE only.
# ─────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # ── Flask ──────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "super_secret")
    DEBUG = True

    # ── Recordings ────────────────────────────
    RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
    AUDIO_DIR = os.path.join(BASE_DIR, "recordings", "audio")
    TRANS_DIR = os.path.join(BASE_DIR, "recordings", "transcriptions")

    # ── Whisper (faster-whisper) ───────────────
    # Model sizes: tiny, base, small, medium, large-v2
    # 🎓 Start with "base" — good balance of speed vs accuracy.
    #    On a decent laptop: ~2-4x real-time speed.
    #    "small" is better quality but slower.
    WHISPER_MODEL = "tiny"
    WHISPER_LANGUAGE = "en"  # Force English for best accuracy
    WHISPER_DEVICE = "cpu"  # Change to "cuda" if you have an NVIDIA GPU
    WHISPER_COMPUTE = "int8"  # int8 = quantized = faster on CPU, tiny quality loss

    # ── Audio chunking ────────────────────────
    # 🎓 We process audio in chunks rather than one huge file.
    #    CHUNK_SECONDS = how many seconds of audio we buffer before
    #    sending to Whisper. Smaller = more responsive, less accurate.
    #    Larger = more accurate, more lag. 4s is a sweet spot.
    CHUNK_SECONDS = 4
    SAMPLE_RATE = 16000  # Whisper expects 16kHz audio
    CHANNELS = 1  # Mono is fine for speech

    # ── Speaker Diarization ───────────────────
    # 🎓 Diarization = "who spoke when". pyannote needs a HuggingFace
    #    token. Set it as an env variable: set HF_TOKEN=your_token_here
    #    Get it free at https://huggingface.co/settings/tokens
    #    Then accept model terms at:
    #    https://huggingface.co/pyannote/speaker-diarization-3.1
    HF_TOKEN = os.environ.get("HF_TOKEN", "")
    DIARIZATION_ON = bool(HF_TOKEN)  # Auto-disabled if no token

    # ── Telegram (future) ─────────────────────
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

    # ── SocketIO ──────────────────────────────
    # 🎓 "threading" mode works on Windows without extra setup.
    #    "eventlet" or "gevent" are faster but need extra packages.
    SOCKETIO_ASYNC_MODE = "threading"
