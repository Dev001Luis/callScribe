# app/telegram_agent.py
import requests
from config import Config


def send_transcript_to_telegram(session_name, text_content):
    if not Config.TELEGRAM_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return

    message = f"🎙️ *New CallScribe Session: {session_name}*\n\n{text_content[:3500]}"  # TG limit is 4096
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
            json={
                "chat_id": Config.TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
        )
    except Exception as e:
        print(f"[Telegram] Failed to send: {e}")
