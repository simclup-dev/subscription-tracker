"""
FastAPI main application — Subscription & API Tracker.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import init_db, SessionLocal
from .models import Subscription, PaymentHistory, ProviderBalance, NotificationLog
from .services.provider_poller import poll_all_providers
from .services.reminder import run_reminder_check
from .services.telegram_bot import acknowledge_subscription
from .config import DASHBOARD_TITLE

from .routers import api, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, start scheduler."""
    init_db()
    from apscheduler.schedulers.background import BackgroundScheduler
    from .config import PROVIDER_POLL_INTERVAL, REMINDER_CHECK_INTERVAL

    scheduler = BackgroundScheduler()

    def poll_job():
        db = SessionLocal()
        try:
            poll_all_providers(db)
        finally:
            db.close()

    def reminder_job():
        db = SessionLocal()
        try:
            run_reminder_check(db)
        finally:
            db.close()

    scheduler.add_job(poll_job, "interval", seconds=PROVIDER_POLL_INTERVAL, id="poll_providers")
    scheduler.add_job(reminder_job, "interval", seconds=REMINDER_CHECK_INTERVAL, id="check_reminders")
    scheduler.start()

    yield

    scheduler.shutdown()


app = FastAPI(title="Subscription Tracker", lifespan=lifespan)

# CORS — allow bookmarklets from provider pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aistudio.google.com",
        "https://ollama.com",
        "https://claude.ai",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api.router, prefix="/api")
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/healthz")
def healthz():
    """Lightweight health check for Pangolin."""
    return {"status": "ok"}
