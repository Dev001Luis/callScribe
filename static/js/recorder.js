/**
 * CallScribe — Browser Recorder & WebSocket Client
 *
 * 🎓 JUNIOR NOTE: This file does three things:
 *    1. Captures microphone audio via the Web Audio API
 *    2. Streams raw PCM audio chunks to the Flask server via WebSocket
 *    3. Receives transcript segments back and renders them live
 *
 * Web Audio API pipeline:
 *   Mic → AudioContext → ScriptProcessor → PCM bytes → WebSocket → Flask
 */

// ── State ─────────────────────────────────────────────────────────────
let socket         = null;
let audioContext   = null;
let mediaStream    = null;
let processor      = null;    // ScriptProcessorNode (audio pipeline)
let analyser       = null;    // for the visualiser animation
let isRecording    = false;
let isPaused       = false;
let timerInterval  = null;
let elapsedSeconds = 0;

// 🎓 Speaker → CSS class index map so Speaker 1 always gets the same colour
// 🎓 BUG FIX: must be `let` not `const` — we reassign it to {} on each new
//    recording. `const` blocks reassignment entirely, causing a silent crash.
let speakerColours = {};
let speakerCount   = 0;

// ── DOM refs ──────────────────────────────────────────────────────────
const statusBadge   = document.getElementById("status-badge");
const timerDisplay  = document.getElementById("timer");
const visualiser    = document.getElementById("visualiser");
const transcriptBody= document.getElementById("transcript-body");
const segCount      = document.getElementById("seg-count");
const sessionList   = document.getElementById("session-list");
const saveModal     = document.getElementById("save-modal");
const viewModal     = document.getElementById("view-modal");
const saveNameInput = document.getElementById("save-name");
const viewModalBody = document.getElementById("view-modal-body");
const viewModalTitle= document.getElementById("view-modal-title");

const btnStart  = document.getElementById("btn-start");
const btnPause  = document.getElementById("btn-pause");
const btnEnd    = document.getElementById("btn-end");
const btnDelete = document.getElementById("btn-delete");

// ── WebSocket connection ──────────────────────────────────────────────

function connectSocket() {
  // io() auto-connects to the server that served this page
  socket = io({ transports: ["websocket"] });

  socket.on("connect", () => {
    setStatus("connected", "Connected");
    showToast("Server connected ✓", "success");
    loadSessions();
  });

  socket.on("disconnect", () => {
    setStatus("", "Disconnected");
    showToast("Server disconnected", "error");
  });

  socket.on("status", (data) => showToast(data.message, "info"));

  socket.on("recording_started", () => {
    setStatus("recording", "● Recording");
    startTimer();
  });

  socket.on("recording_paused", () => {
    setStatus("paused", "⏸ Paused");
    stopTimer();
  });

  socket.on("recording_resumed", () => {
    setStatus("recording", "● Recording");
    startTimer();
  });

  socket.on("recording_ended",  onRecordingEnded);
  socket.on("recording_deleted", onRecordingDeleted);
  socket.on("saved",             onSaved);

  // ── Live transcript chunks ────────────────────────────────────────
  socket.on("transcript_chunk", (data) => {
    const segments = data.segments || [];
    segments.forEach(appendSegment);
  });

  socket.on("error", (data) => showToast(data.message, "error"));
}

// ── Button handlers ───────────────────────────────────────────────────

btnStart.addEventListener("click", async () => {
  try {
    await startAudioCapture();    // get mic permission + set up pipeline
    socket.emit("start_recording");

    isRecording = true;
    isPaused    = false;
    clearTranscript();
    speakerColours = {};
    speakerCount   = 0;

    btnStart.disabled  = true;
    btnPause.disabled  = false;
    btnEnd.disabled    = false;
    btnDelete.disabled = false;
  } catch (err) {
    showToast(`Microphone error: ${err.message}`, "error");
    console.error(err);
  }
});

btnPause.addEventListener("click", () => {
  if (!isPaused) {
    socket.emit("pause_recording");
    pauseAudio();
    btnPause.textContent = "▶ Resume";
    isPaused = true;
  } else {
    socket.emit("resume_recording");
    resumeAudio();
    btnPause.textContent = "⏸ Pause";
    isPaused = false;
  }
});

btnEnd.addEventListener("click", () => {
  socket.emit("end_recording");
  stopAudioCapture();
  stopTimer();
  isRecording = false;
});

btnDelete.addEventListener("click", () => {
  if (!confirm("Delete this recording? This cannot be undone.")) return;
  socket.emit("delete_recording");
  stopAudioCapture();
  stopTimer();
  clearTranscript();
  resetButtons();
  setStatus("connected", "Connected");
});

// ── Save modal ────────────────────────────────────────────────────────

function onRecordingEnded(data) {
  setStatus("connected", "Session ended");
  showToast("Recording ended — save your session!", "info");
  // Show save modal
  saveNameInput.value = "";
  saveModal.hidden    = false;
  saveNameInput.focus();
}

document.getElementById("btn-confirm-save").addEventListener("click", () => {
  socket.emit("save_recording", { name: saveNameInput.value });
  saveModal.hidden = true;
});

document.getElementById("btn-cancel-save").addEventListener("click", () => {
  saveModal.hidden = true;
  resetButtons();
});

function onSaved(data) {
  showToast(data.message, "success");
  resetButtons();
  loadSessions();
}

// ── Delete recording in progress ──────────────────────────────────────

function onRecordingDeleted() {
  showToast("Recording deleted", "info");
  resetButtons();
}

// ── Session history ───────────────────────────────────────────────────

document.getElementById("btn-refresh").addEventListener("click", loadSessions);

async function loadSessions() {
  try {
    const res  = await fetch("/api/sessions");
    const data = await res.json();

    if (!data.length) {
      sessionList.innerHTML = '<li class="placeholder">No sessions yet</li>';
      return;
    }

    sessionList.innerHTML = "";
    data.forEach(session => {
      const li = document.createElement("li");
      li.className = "session-item";
      li.innerHTML = `
        <div class="session-name">📄 ${session.name}</div>
        <div class="session-actions">
          ${session.transcript
            ? `<button class="btn btn-ghost" onclick="viewTranscript('${session.name}', '${session.transcript}')">View</button>`
            : ""}
          <a class="btn btn-primary" href="/api/download/audio/${session.audio}" download>⬇ Audio</a>
        </div>`;
      sessionList.appendChild(li);
    });
  } catch (e) {
    console.error("Failed to load sessions:", e);
  }
}

async function viewTranscript(name, filename) {
  const res  = await fetch(`/api/transcript/${filename}`);
  const data = await res.json();

  viewModalTitle.textContent = name;
  viewModalBody.innerHTML    = "";

  const lines = (data.content || "").split("\n");
  lines.forEach(line => {
    const p = document.createElement("p");
    p.style.fontSize   = "0.85rem";
    p.style.lineHeight = "1.6";
    p.style.marginBottom = "4px";
    p.textContent = line;
    viewModalBody.appendChild(p);
  });

  viewModal.hidden = false;
}

document.getElementById("btn-close-view").addEventListener("click", () => {
  viewModal.hidden = true;
});

// ── Audio capture ─────────────────────────────────────────────────────

async function startAudioCapture() {
  /**
   * 🎓 getUserMedia asks the browser for microphone access.
   *    The constraints tell the browser we want:
   *    - echoCancellation: removes YOUR voice from the "other person" channel
   *    - noiseSuppression: filters background noise
   *    - sampleRate: 16000 matches what Whisper expects
   *
   *    IMPORTANT: On Android Chrome, you must be on HTTPS or localhost
   *    for getUserMedia to work. We'll handle this in Phase 2.
   */
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      sampleRate: 16000,
      channelCount: 1,
    }
  });

  // 🎓 AudioContext is the entry point to Web Audio API.
  //    All audio processing nodes connect through it.
  audioContext = new (window.AudioContext || window.webkitAudioContext)({
    sampleRate: 16000   // Force 16kHz to match Whisper
  });

  const source = audioContext.createMediaStreamSource(mediaStream);

  // ── Analyser for visualiser ──────────────────────────────────────
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 64;
  source.connect(analyser);
  startVisualiser();

  // ── ScriptProcessor for raw PCM ─────────────────────────────────
  // 🎓 ScriptProcessorNode (legacy but reliable) fires onaudioprocess
  //    every `bufferSize` samples. At 16kHz, bufferSize=4096 means
  //    it fires ~4 times per second — a good pace for streaming.
  //    The modern API is AudioWorklet, but ScriptProcessor is simpler
  //    to learn first. We can upgrade later!
  const bufferSize = 4096;
  processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
  source.connect(processor);
  processor.connect(audioContext.destination);

  processor.onaudioprocess = (event) => {
    if (!isRecording || isPaused) return;

    // Get float32 samples from the input channel
    const float32 = event.inputBuffer.getChannelData(0);

    // Convert float32 [-1,1] → int16 [-32768,32767] for transmission
    // 🎓 We convert here to save bandwidth. Float32 = 4 bytes/sample,
    //    Int16 = 2 bytes/sample — half the data over the WebSocket.
    const int16 = float32ToInt16(float32);

    socket.emit("audio_chunk", { audio: int16.buffer });
  };
}

function pauseAudio() {
  if (audioContext) audioContext.suspend();
}

function resumeAudio() {
  if (audioContext) audioContext.resume();
}

function stopAudioCapture() {
  isRecording = false;
  if (processor) {
    processor.disconnect();
    processor.onaudioprocess = null;
    processor = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
    mediaStream = null;
  }
  stopVisualiser();
}

// ── Visualiser ────────────────────────────────────────────────────────

let visFrame = null;

function startVisualiser() {
  visualiser.classList.add("active");
  const bars    = visualiser.querySelectorAll("span");
  const dataArr = new Uint8Array(analyser.frequencyBinCount);

  function draw() {
    visFrame = requestAnimationFrame(draw);
    analyser.getByteFrequencyData(dataArr);
    bars.forEach((bar, i) => {
      const val   = dataArr[i % dataArr.length] || 0;
      const height = 4 + (val / 255) * 26;
      bar.style.height = height + "px";
    });
  }
  draw();
}

function stopVisualiser() {
  cancelAnimationFrame(visFrame);
  visualiser.classList.remove("active");
  visualiser.querySelectorAll("span").forEach(b => b.style.height = "4px");
}

// ── Transcript rendering ───────────────────────────────────────────────

function appendSegment(seg) {
  // Remove placeholder if present
  const ph = transcriptBody.querySelector(".placeholder");
  if (ph) ph.remove();

  // Assign consistent colour to each speaker
  if (!(seg.speaker in speakerColours)) {
    speakerColours[seg.speaker] = speakerCount % 4;
    speakerCount++;
  }
  const colourClass = `speaker-${speakerColours[seg.speaker]}`;

  const div = document.createElement("div");
  div.className = "segment";
  div.innerHTML = `
    <span class="segment-speaker ${colourClass}">${escHtml(seg.speaker)}</span>
    <div class="segment-text">${escHtml(seg.text)}</div>
    <div class="segment-meta">${seg.start}s – ${seg.end}s</div>`;

  transcriptBody.appendChild(div);

  // Auto-scroll to bottom
  transcriptBody.scrollTop = transcriptBody.scrollHeight;

  // Update segment count
  const current = parseInt(segCount.textContent) || 0;
  segCount.textContent = `${current + 1} segments`;
}

function clearTranscript() {
  transcriptBody.innerHTML = '<p class="placeholder">Transcript will appear here as you speak…</p>';
  segCount.textContent = "0 segments";
}

// ── Timer ─────────────────────────────────────────────────────────────

function startTimer() {
  elapsedSeconds = 0;
  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    elapsedSeconds++;
    const m = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
    const s = String(elapsedSeconds % 60).padStart(2, "0");
    timerDisplay.textContent = `${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
}

// ── Helpers ───────────────────────────────────────────────────────────

function resetButtons() {
  btnStart.disabled  = false;
  btnPause.disabled  = true;
  btnEnd.disabled    = true;
  btnDelete.disabled = true;
  btnPause.textContent = "⏸ Pause";
}

function setStatus(cssClass, text) {
  statusBadge.className  = "status-badge " + cssClass;
  statusBadge.textContent = text;
}

function showToast(msg, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  document.getElementById("toast-container").appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function float32ToInt16(float32arr) {
  const int16 = new Int16Array(float32arr.length);
  for (let i = 0; i < float32arr.length; i++) {
    // Clamp to [-1, 1] then scale
    const s = Math.max(-1, Math.min(1, float32arr[i]));
    int16[i] = s < 0 ? s * 32768 : s * 32767;
  }
  return int16;
}

function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Boot ──────────────────────────────────────────────────────────────
connectSocket();
loadSessions();
