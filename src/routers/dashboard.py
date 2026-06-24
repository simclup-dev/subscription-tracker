"""
Dashboard router for HTML pages.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..config import DASHBOARD_TITLE, PUBLIC_BASE_URL
from ..database import get_db
from ..models import ProviderBalance, Subscription
from ..services.subscription_utils import (
    calculate_monthly_totals_by_currency,
    deactivate_duplicate_subscriptions,
)


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, db: Session = Depends(get_db)):
    deactivate_duplicate_subscriptions(db)
    subs = db.query(Subscription).filter_by(is_active=True).order_by(Subscription.next_payment_date).all()
    providers = db.query(ProviderBalance).all()

    monthly_totals = calculate_monthly_totals_by_currency(subs)

    today = datetime.now(timezone.utc).date()
    week_ahead = today + timedelta(days=7)
    upcoming = [s for s in subs if s.next_payment_date and s.next_payment_date <= week_ahead]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": DASHBOARD_TITLE,
        "subscriptions": subs,
        "providers": providers,
        "monthly_totals": monthly_totals,
        "upcoming": upcoming,
        "now": datetime.now(timezone.utc),
    })


@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions_page(request: Request, db: Session = Depends(get_db)):
    deactivate_duplicate_subscriptions(db)
    subs = db.query(Subscription).filter_by(is_active=True).order_by(Subscription.next_payment_date).all()
    return templates.TemplateResponse("subscriptions.html", {
        "request": request,
        "title": "Subscriptions",
        "subscriptions": subs,
    })


@router.get("/providers", response_class=HTMLResponse)
def providers_page(request: Request, db: Session = Depends(get_db)):
    providers = db.query(ProviderBalance).all()
    return templates.TemplateResponse("providers.html", {
        "request": request,
        "title": "Providers",
        "providers": providers,
    })


@router.get("/google-ai", response_class=HTMLResponse)
def google_ai_bookmarklet(request: Request):
    return templates.TemplateResponse("google_ai.html", {
        "request": request,
        "title": "Google AI Bookmarklet",
        "public_base_url": PUBLIC_BASE_URL.rstrip("/"),
    })


@router.get("/anthropic", response_class=HTMLResponse)
def anthropic_bookmarklet(request: Request, db: Session = Depends(get_db)):
    provider = db.query(ProviderBalance).filter_by(provider_name="anthropic").first()
    return templates.TemplateResponse("anthropic.html", {
        "request": request,
        "title": "Anthropic Bookmarklet",
        "provider": provider,
        "public_base_url": PUBLIC_BASE_URL.rstrip("/"),
    })
