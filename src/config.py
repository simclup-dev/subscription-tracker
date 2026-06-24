import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "tracker.db"))

# Provider credentials (from env vars)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GOOGLE_COOKIE = os.getenv("GOOGLE_COOKIE", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OLLAMA_COOKIE = os.getenv("OLLAMA_COOKIE", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
N8N_CALLBACK_URL = os.getenv("N8N_CALLBACK_URL", "")

# Dashboard
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
DASHBOARD_TITLE = os.getenv("DASHBOARD_TITLE", "Subscription Tracker")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5010")

# Polling intervals (seconds)
PROVIDER_POLL_INTERVAL = int(os.getenv("PROVIDER_POLL_INTERVAL", "300"))  # 5 min
REMINDER_CHECK_INTERVAL = int(os.getenv("REMINDER_CHECK_INTERVAL", "3600"))  # 1 hour
REMINDER_RESEND_HOURS = int(os.getenv("REMINDER_RESEND_HOURS", "24"))  # resend after 24h if not ack'd
REMINDER_DAYS_BEFORE = 3  # notify 3 days before charge
