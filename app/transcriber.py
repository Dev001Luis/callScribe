import numpy as np
import threading
import time
import os
from config import Config

# 🎓 JUNIOR NOTE: We use lazy loading here — the heavy ML models
#    (Whisper, pyannote) are only loaded when first needed, not at
#    import time. This keeps startup fast and avoids crashing if
#    optional dependencies (pyannote) aren't installed yet.

_whisper_model = None
_diarize_pipeline = None
_model_lock = threading.Lock()


def get_whisper_model():
    """Load (or return cached) Whisper model. Thread-safe singleton."""
    global _whisper_model
    if _whisper_model is None:
        with _model_lock:
            if _whisper_model is None:  # double-check after acquiring lock
                print("[Transcriber] Loading Whisper model... (first time only)")
                from faster_whisper import WhisperModel

                _whisper_model = WhisperModel(
                    Config.WHISPER_MODEL,
                    device=Config.WHISPER_DEVICE,
                    compute_type=Config.WHISPER_COMPUTE,
                )
                print(f"[Transcriber] Whisper '{Config.WHISPER_MODEL}' ready.")
    return _whisper_model

    # def get_diarize_pipeline():
    """Load (or return cached) pyannote diarization pipeline."""
    global _diarize_pipeline
    if not Config.DIARIZATION_ON:
        return None
    if _diarize_pipeline is None:
        with _model_lock:
            if _diarize_pipeline is None:
                try:
                    print("[Transcriber] Loading pyannote diarization pipeline...")
                    from pyannote.audio import Pipeline

                    _diarize_pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=Config.HF_TOKEN,
                    )
                    print("[Transcriber] Diarization pipeline ready.")
                except Exception as e:
                    print(f"[Transcriber] WARNING: Diarization failed to load: {e}")
                    print("[Transcriber] Continuing WITHOUT diarization.")
    return _diarize_pipeline


# ── Core transcription function ───────────────────────────────────────


def transcribe_chunk(audio_np: np.ndarray) -> list[dict]:
    """
    Takes a numpy float32 audio array and returns a list of segments:
        [{"speaker": "Speaker 1", "start": 0.0, "end": 2.3, "text": "Hello there"}, ...]

    🎓 Why return a list? One audio chunk can contain multiple sentences
       and potentially multiple speakers. A list lets us handle all of them.
    """
    model = get_whisper_model()

    # ── Step 1: Transcribe with Whisper ──────────────────────────────
    # beam_size=5 → Whisper considers 5 candidate sequences at once
    # vad_filter=True → Voice Activity Detection built into faster-whisper
    #   it automatically skips silence, reducing hallucinations
    #   (Whisper sometimes transcribes silence as random words!)
    segments_iter, info = model.transcribe(
        audio_np,
        language=Config.WHISPER_LANGUAGE,
        beam_size=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    # Convert generator to list (we need to iterate twice for diarization)
    segments = list(segments_iter)

    if not segments:
        return []

    # ── Step 2: Diarization (optional) ───────────────────────────────
    # diarize = get_diarize_pipeline()

    # if diarize is not None:
    #   return _transcribe_with_diarization(audio_np, segments, diarize)
    # else:
    # No diarization — label everything as "You" or alternate by heuristic
    return _transcribe_no_diarization(segments)


def _transcribe_no_diarization(segments) -> list[dict]:
    """
    Without diarization we can't tell speakers apart by voice.
    We use a simple heuristic: if there's a long pause between segments,
    assume speaker changed. Not perfect, but better than nothing.

    🎓 This is called a "graceful degradation" — the app still works
       without the optional feature, just with reduced quality.
    """
    results = []
    last_end = 0.0
    speaker_index = 0
    PAUSE_THRESHOLD = 1.0  # seconds of silence = assume speaker change

    for seg in segments:
        if seg.start - last_end > PAUSE_THRESHOLD and results:
            speaker_index = 1 - speaker_index  # toggle 0 ↔ 1

        results.append(
            {
                "speaker": f"Speaker {speaker_index + 1}",
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            }
        )
        last_end = seg.end

    return results


def _transcribe_with_diarization(audio_np, segments, diarize_pipeline) -> list[dict]:
    """
    Align Whisper segments with pyannote speaker labels.
    For each Whisper segment, we find which speaker was dominant
    during that time window.

    🎓 Whisper gives us WHAT was said. pyannote gives us WHO said it.
       We merge them by time overlap.
    """
    import torch
    import io, wave

    # pyannote needs the audio as a file-like WAV object
    wav_buf = io.BytesIO()
    int16 = (audio_np * 32767).astype("int16")
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(Config.SAMPLE_RATE)
        wf.writeframes(int16.tobytes())
    wav_buf.seek(0)

    try:
        diarization = diarize_pipeline({"uri": "chunk", "audio": wav_buf})
    except Exception as e:
        print(f"[Diarization] Error: {e} — falling back to no-diarization mode")
        return _transcribe_no_diarization(segments)

    # Build speaker timeline: list of (start, end, speaker_label)
    timeline = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]

    results = []
    for seg in segments:
        # Find speaker with most overlap in this segment's time window
        speaker = _dominant_speaker(seg.start, seg.end, timeline)
        results.append(
            {
                "speaker": speaker,
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            }
        )
    return results


def _dominant_speaker(start: float, end: float, timeline: list) -> str:
    """
    Given a time window [start, end] and a list of speaker segments,
    return the speaker label with the most overlap in that window.
    """
    overlap_by_speaker = {}
    for t_start, t_end, speaker in timeline:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > 0:
            overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0) + overlap

    if not overlap_by_speaker:
        return "Speaker 1"

    # Return the speaker with the most overlap
    best = max(overlap_by_speaker, key=overlap_by_speaker.get)

    # Map pyannote labels (SPEAKER_00, SPEAKER_01) to friendlier names
    label_map = {}
    for label in sorted(set(s for _, _, s in timeline)):
        idx = len(label_map)
        label_map[label] = f"Speaker {idx + 1}"

    return label_map.get(best, best)
