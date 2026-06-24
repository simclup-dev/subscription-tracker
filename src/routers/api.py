"""
API router — JSON endpoints for subscriptions, providers, Telegram webhook.
"""
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from ..database import get_db
from ..models import Subscription, PaymentHistory, ProviderBalance, NotificationLog
from ..services.provider_poller import poll_all_providers
from ..services.reminder import run_reminder_check
from ..services.telegram_bot import acknowledge_subscription, send_status_message
from ..config import TELEGRAM_CHAT_ID, N8N_CALLBACK_URL
import httpx
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Pydantic Schemas ─────────────────────────────────────
class SubscriptionCreate(BaseModel):
    service_name: str
    amount: float
    currency: str = "USD"
    frequency: str = "monthly"
    last_payment_date: Optional[date] = None
    next_payment_date: date
    category: str = "other"
    notes: str = ""

class SubscriptionUpdate(BaseModel):
    service_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    frequency: Optional[str] = None
    last_payment_date: Optional[date] = None
    next_payment_date: Optional[date] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ─── Subscriptions CRUD ───────────────────────────────────
@router.get("/subscriptions")
def list_subscriptions(db: Session = Depends(get_db)):
    subs = db.query(Subscription).order_by(Subscription.next_payment_date).all()
    return [
        {
            "id": s.id,
            "service_name": s.service_name,
            "amount": s.amount,
            "currency": s.currency,
            "frequency": s.frequency,
            "last_payment_date": str(s.last_payment_date) if s.last_payment_date else None,
            "next_payment_date": str(s.next_payment_date),
            "category": s.category,
            "notes": s.notes,
            "is_active": s.is_active,
            "source": s.source,
        }
        for s in subs
    ]

@router.post("/subscriptions")
def create_subscription(data: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = Subscription(**data.model_dump())
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"id": sub.id, "status": "created"}

@router.get("/subscriptions/{sub_id}")
def get_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter_by(id=sub_id).first()
    if not sub:
        raise HTTPException(404, "Not found")
    return {
        "id": sub.id,
        "service_name": sub.service_name,
        "amount": sub.amount,
        "currency": sub.currency,
        "frequency": sub.frequency,
        "last_payment_date": str(sub.last_payment_date) if sub.last_payment_date else None,
        "next_payment_date": str(sub.next_payment_date),
        "category": sub.category,
        "notes": sub.notes,
        "is_active": sub.is_active,
    }

@router.put("/subscriptions/{sub_id}")
def update_subscription(sub_id: int, data: SubscriptionUpdate, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter_by(id=sub_id).first()
    if not sub:
        raise HTTPException(404, "Not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(sub, field, val)
    db.commit()
    return {"status": "updated"}

@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter_by(id=sub_id).first()
    if not sub:
        raise HTTPException(404, "Not found")
    db.delete(sub)
    db.commit()
    return {"status": "deleted"}

@router.get("/subscriptions/{sub_id}/payments")
def get_payments(sub_id: int, db: Session = Depends(get_db)):
    payments = db.query(PaymentHistory).filter_by(subscription_id=sub_id).all()
    return [
        {
            "id": p.id,
            "amount": p.amount,
            "currency": p.currency,
            "payment_date": str(p.payment_date),
        }
        for p in payments
    ]

@router.get("/upcoming")
def get_upcoming(days: int = Query(7), db: Session = Depends(get_db)):
    target = date.today()
    from datetime import timedelta
    target = date.today() + timedelta(days=days)
    subs = db.query(Subscription).filter(
        Subscription.is_active == True,
        Subscription.next_payment_date == target
    ).all()
    return [
        {"id": s.id, "service_name": s.service_name, "amount": s.amount,
         "currency": s.currency, "next_payment_date": str(s.next_payment_date)}
        for s in subs
    ]


# ─── Providers ────────────────────────────────────────────
@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    providers = db.query(ProviderBalance).all()
    return [
        {
            "provider_name": p.provider_name,
            "balance": p.balance,
            "limit_total": p.limit_total,
            "limit_used_percent": p.limit_used_percent,
            "spent": p.spent,
            "currency": p.currency,
            "raw_response": p.raw_response,
            "last_checked": str(p.last_checked) if p.last_checked else None,
            "last_error": p.last_error,
        }
        for p in providers
    ]

@router.post("/providers/poll")
def trigger_poll(db: Session = Depends(get_db)):
    """Manually trigger a provider poll."""
    results = poll_all_providers(db)
    return {"status": "polled", "providers": list(results.keys())}


@router.post("/providers/{provider_name}/update")
def update_provider_balance(provider_name: str, data: dict, db: Session = Depends(get_db)):
    """Manually update provider balance/spent (for providers without API)."""
    provider = db.query(ProviderBalance).filter_by(provider_name=provider_name).first()
    if not provider:
        provider = ProviderBalance(provider_name=provider_name, currency="USD")
        db.add(provider)

    if "spent" in data:
        provider.spent = float(data["spent"])
    if "balance" in data:
        provider.balance = float(data["balance"])
    if "limit_total" in data:
        provider.limit_total = float(data["limit_total"])
    if "limit_used_percent" in data:
        provider.limit_used_percent = float(data["limit_used_percent"])
    if "raw_response" in data:
        provider.raw_response = str(data["raw_response"])[:500]
    if "is_rate_limited" in data:
        if data["is_rate_limited"]:
            reset_str = f" — скидається о {data['rate_reset_at']}" if data.get("rate_reset_at") else ""
            provider.last_error = f"RATE LIMITED{reset_str}"
        else:
            provider.last_error = ""

    provider.last_checked = datetime.now(timezone.utc)
    db.commit()
    return {"status": "updated"}


# ─── Telegram Webhook ─────────────────────────────────────
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Telegram updates: callback queries (buttons) + text commands."""
    body = await request.json()

    # ── Callback query (inline button press) ──
    callback = body.get("callback_query", {})
    data_str = callback.get("data", "")
    if data_str.startswith("ack_sub_"):
        sub_id = int(data_str.replace("ack_sub_", ""))
        ok = acknowledge_subscription(sub_id, db)
        return {
            "method": "answerCallbackQuery",
            "callback_query_id": callback.get("id", ""),
            "text": "✅ Підтверджено! Більше не нагадуватиму." if ok else "⚠️ Помилка",
            "show_alert": False
        }

    # ── Foreign callback buttons (n8n reminders, e.g. done_*) → forward to n8n ──
    if callback and data_str and N8N_CALLBACK_URL:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                await client.post(N8N_CALLBACK_URL, json=body)
        except Exception as e:
            logger.warning("forward callback to n8n failed: %s", e)
        return {"status": "forwarded"}

    # ── Text commands ──
    message = body.get("message", {})
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))

    # Security: only respond to the owner
    if chat_id and chat_id != str(TELEGRAM_CHAT_ID):
        return {"status": "ignored"}

    if text in ("/status", "/ai", "/budget", "/tracker", "/s"):
        send_status_message(db)
        return {"status": "sent"}

    return {"status": "ignored"}


# ─── Manual Reminder Trigger ──────────────────────────────
@router.post("/reminders/check")
def trigger_reminders(db: Session = Depends(get_db)):
    result = run_reminder_check(db)
    return result
