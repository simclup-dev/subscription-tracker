"""
Telegram bot service — sends reminders + handles /status command.
"""
import re
import httpx
from datetime import datetime, timezone, timedelta, date
from sqlalchemy.orm import Session

from ..config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REMINDER_RESEND_HOURS
from ..models import Subscription, NotificationLog, ProviderBalance


def send_telegram_message(text: str, reply_markup: dict = None) -> dict | None:
    """Send a message via Telegram Bot API. Returns API response or None on failure."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = httpx.post(url, json=payload, timeout=15)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def send_status_message(db: Session) -> bool:
    """Send current AI provider balances + upcoming subscriptions to Telegram."""
    lines = ["📊 <b>Трекер — поточний стан</b>\n"]

    # Providers
    providers = db.query(ProviderBalance).order_by(ProviderBalance.provider_name).all()
    if providers:
        lines.append("🤖 <b>API / Баланси:</b>")
        for p in providers:
            name = p.provider_name.upper()

            if p.last_error and "bookmarklet" not in p.last_error.lower() and "натисни" not in p.last_error.lower() and p.last_error.strip():
                lines.append(f"  ⚠️ <b>{name}</b>: {p.last_error[:60]}")
            elif p.provider_name == "deepseek" and p.balance is not None:
                lines.append(f"  💰 <b>{name}</b>: ${p.balance:.2f}")
            elif p.provider_name == "google_ai":
                if p.spent is not None and p.spent > 0:
                    left = max(0, (p.limit_total or 12.0) - p.spent)
                    lines.append(f"  🔵 <b>{name}</b>: ${p.spent:.2f} витрачено, ${left:.2f} лишилось")
                else:
                    lines.append(f"  🔵 <b>{name}</b>: немає даних (потрібен bookmarklet)")
            elif p.provider_name == "anthropic":
                plan = p.raw_response or "—"
                if p.last_error == "RATE LIMITED" or (p.last_error and "RATE" in p.last_error):
                    lines.append(f"  🔴 <b>{name}</b>: {plan} — ⛔ Rate Limited")
                elif p.last_checked:
                    lines.append(f"  🟢 <b>{name}</b>: {plan} — OK")
                else:
                    lines.append(f"  ⚪ <b>{name}</b>: немає даних (потрібен bookmarklet)")
            elif p.provider_name == "ollama" and p.limit_used_percent is not None:
                pct = p.limit_used_percent
                icon = "🔴" if pct > 80 else "🟡" if pct > 50 else "🟢"
                reset_info = ""
                if p.raw_response:
                    # extract weekly reset from "session=X%; weekly=Y% (→3 days)"
                    weekly_m = re.search(r"weekly=[^;]+ \(→([^)]+)\)", p.raw_response)
                    if weekly_m:
                        reset_info = f", тижн. скид.: {weekly_m.group(1)}"
                lines.append(f"  {icon} <b>{name}</b>: {pct:.1f}%{reset_info}")
            elif p.last_checked is None:
                lines.append(f"  ⚪ <b>{name}</b>: ще не перевірявся")
            else:
                lines.append(f"  ⚪ <b>{name}</b>: немає даних")

    # Upcoming subscriptions (7 days)
    today = date.today()
    week_ahead = today + timedelta(days=7)
    upcoming = (
        db.query(Subscription)
        .filter(
            Subscription.is_active == True,
            Subscription.next_payment_date <= week_ahead,
        )
        .order_by(Subscription.next_payment_date)
        .all()
    )

    if upcoming:
        lines.append("\n📅 <b>Списання цього тижня:</b>")
        for s in upcoming:
            days = (s.next_payment_date - today).days
            when = "сьогодні" if days == 0 else "завтра" if days == 1 else f"через {days} дн."
            lines.append(f"  💸 {s.service_name}: {s.amount:.2f} {s.currency} ({when})")
    else:
        lines.append("\n✅ Найближчих списань немає.")

    result = send_telegram_message("\n".join(lines))
    return bool(result and result.get("ok"))


def send_subscription_reminder(subscription: Subscription, db: Session) -> bool:
    """
    Send a reminder for an upcoming subscription charge.
    Returns True if message was sent successfully.
    """
    days_left = (subscription.next_payment_date - datetime.now(timezone.utc).date()).days
    text = (
        f"🔔 <b>Нагадування про списання</b>\n\n"
        f"📋 <b>{subscription.service_name}</b>\n"
        f"💰 {subscription.amount:.2f} {subscription.currency}\n"
        f"📅 Дата списання: {subscription.next_payment_date}\n"
        f"⏳ Залишилось: <b>{days_left} дн.</b>\n\n"
        f"<i>Натисни кнопку нижче, щоб підтвердити прочитання</i>"
    )

    keyboard = {
        "inline_keyboard": [[
            {
                "text": "✅ Прочитав",
                "callback_data": f"ack_sub_{subscription.id}"
            }
        ]]
    }

    result = send_telegram_message(text, reply_markup=keyboard)

    if result and result.get("ok"):
        msg_id = result["result"]["message_id"]
        log = NotificationLog(
            subscription_id=subscription.id,
            type="reminder",
            message=text,
            channel="telegram",
            telegram_message_id=msg_id,
            acknowledged=False,
            sent_at=datetime.now(timezone.utc)
        )
        db.add(log)
        db.commit()
        return True
    return False


def resend_unacknowledged(db: Session) -> int:
    """
    Find unacknowledged reminders older than REMINDER_RESEND_HOURS and resend them.
    Returns count of resent messages.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=REMINDER_RESEND_HOURS)
    unack = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.type == "reminder",
            NotificationLog.acknowledged == False,
            NotificationLog.sent_at < cutoff,
            NotificationLog.subscription_id.isnot(None)
        )
        .all()
    )

    resent = 0
    for log in unack:
        sub = db.query(Subscription).filter_by(id=log.subscription_id).first()
        if sub and sub.is_active:
            if send_subscription_reminder(sub, db):
                resent += 1
    return resent


def acknowledge_subscription(subscription_id: int, db: Session) -> bool:
    """Mark all unacknowledged reminders for a subscription as acknowledged."""
    logs = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.subscription_id == subscription_id,
            NotificationLog.type == "reminder",
            NotificationLog.acknowledged == False
        )
        .all()
    )
    for log in logs:
        log.acknowledged = True
        log.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return len(logs) > 0
