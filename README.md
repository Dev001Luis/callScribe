# 🎙️ CallScribe — Setup Guide (Windows)

## Step 1 — Install Python 3.11+
Download from https://python.org — check "Add to PATH" during install.

## Step 2 — Create a virtual environment
```
cd CallScribe
python -m venv venv
venv\Scripts\activate
```
🎓 A virtual environment keeps CallScribe's packages isolated from
   your system Python. Always activate it before working on the project.

## Step 3 — Install dependencies
```
pip install -r requirements.txt
```
Note: faster-whisper will download the Whisper model on first run (~150MB for "base").

## Step 4 — Run the app
```
python run.py
```
Open http://localhost:5000 in Chrome or Edge.

## Step 5 — Access from your Android tablet
1. Make sure your tablet and PC are on the same Wi-Fi.
2. Find your PC's local IP: open CMD and run `ipconfig`
   Look for "IPv4 Address" under your Wi-Fi adapter (e.g. 192.168.1.42)
3. On your tablet browser, open: http://192.168.1.42:5000

## (Optional) Step 6 — Enable speaker diarization
1. Create a free account at https://huggingface.co
2. Generate a token at https://huggingface.co/settings/tokens
3. Accept the model license at https://huggingface.co/pyannote/speaker-diarization-3.1
4. Set the token in your terminal before running:
   ```
   set HF_TOKEN=hf_yourTokenHere
   python run.py
   ```
5. Uncomment the pyannote lines in requirements.txt and re-run pip install.

## Git — remember to commit!
```
git init
git add .
git commit -m "feat: initial CallScribe scaffold with live transcription"
```
# callScribe
