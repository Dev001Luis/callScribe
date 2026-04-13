import io
import wave
import numpy as np
import threading
import time
from config import Config

# 🎓 JUNIOR NOTE: This module handles ONE job — taking raw audio bytes
#    that arrive from the browser via WebSocket, buffering them into
#    chunks, and emitting those chunks when they're big enough to
#    send to Whisper. This is the "producer" in a producer/consumer pattern.


class AudioProcessor:
    """
    Buffers incoming PCM audio frames and yields fixed-size chunks.

    Why chunks? Whisper works on audio segments. If we fed it every
    tiny frame (e.g. 100ms) it would be terribly inaccurate — it needs
    context. But if we wait for the whole call to finish, there's no
    "real-time". So we compromise: 4-second rolling chunks.
    """

    def __init__(self, chunk_seconds=None, sample_rate=None):
        self.chunk_seconds  = chunk_seconds or Config.CHUNK_SECONDS
        self.sample_rate    = sample_rate   or Config.SAMPLE_RATE
        self.channels       = Config.CHANNELS

        # How many raw int16 samples make one chunk
        self.chunk_size     = self.chunk_seconds * self.sample_rate

        self._buffer        = np.array([], dtype=np.float32)
        self._lock          = threading.Lock()

        # ── Overlap ───────────────────────────────────────────────────
        # 🎓 We keep 0.5s of the PREVIOUS chunk and prepend it to the next.
        #    Why? Words at the boundary of a chunk get cut off and mis-
        #    transcribed. Overlapping gives Whisper extra context at edges.
        self.overlap_seconds = 0.5
        self.overlap_samples = int(self.overlap_seconds * self.sample_rate)
        self._tail           = np.array([], dtype=np.float32)

        self.is_recording   = False
        self.is_paused      = False

    # ── Public API ────────────────────────────────────────────────────

    def start(self):
        self._buffer     = np.array([], dtype=np.float32)
        self._tail       = np.array([], dtype=np.float32)
        self.is_recording = True
        self.is_paused    = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_recording = False
        self.is_paused    = False
        remaining = self._buffer.copy()
        self._buffer = np.array([], dtype=np.float32)
        return remaining if len(remaining) > 0 else None

    def add_audio(self, raw_bytes: bytes):
        """
        Called every time a WebSocket message arrives with audio data.
        raw_bytes: 16-bit PCM, 16kHz, mono — straight from the browser.
        """
        if not self.is_recording or self.is_paused:
            return

        # Convert raw bytes → numpy float32 array normalised to [-1, 1]
        # 🎓 Whisper expects float32 in [-1,1]. Browser sends int16 in
        #    [-32768, 32767]. Dividing by 32768 normalises it.
        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        with self._lock:
            self._buffer = np.concatenate([self._buffer, samples])

    def get_chunk(self):
        """
        Returns a chunk (with overlap prepended) if the buffer is full.
        Returns None if not enough audio has accumulated yet.
        """
        with self._lock:
            if len(self._buffer) < self.chunk_size:
                return None

            chunk       = self._buffer[:self.chunk_size]
            self._buffer = self._buffer[self.chunk_size:]

            # Prepend tail from last chunk for overlap
            if len(self._tail) > 0:
                chunk_with_overlap = np.concatenate([self._tail, chunk])
            else:
                chunk_with_overlap = chunk

            # Save the tail for next iteration
            self._tail = chunk[-self.overlap_samples:]

            return chunk_with_overlap

    # ── Utility: save full audio to WAV ──────────────────────────────
    @staticmethod
    def samples_to_wav_bytes(samples: np.ndarray, sample_rate: int = Config.SAMPLE_RATE) -> bytes:
        """Convert a numpy float32 array to WAV bytes for saving to disk."""
        buf = io.BytesIO()
        int16_samples = (samples * 32767).astype(np.int16)
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)          # 2 bytes = 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(int16_samples.tobytes())
        return buf.getvalue()
