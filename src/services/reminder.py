"""
Reminder service — checks subscriptions and sends Telegram reminders
3 days before next payment, with resend for unacknowledged.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from ..models import Subscription, NotificationLog
from ..config import REMINDER_DAYS_BEFORE
from .telegram_bot import send_subscription_reminder, resend_unacknowledged


def check_upcoming_charges(db: Session) -> int:
    """
    Find subscriptions due in exactly REMINDER_DAYS_BEFORE days,
    and for which no reminder has been sent yet.
    Returns count of new reminders sent.
    """
    today = datetime.now(timezone.utc).date()
    target_date = today + timedelta(days=REMINDER_DAYS_BEFORE)

    # Find subscriptions with next_payment_date = target_date
    due_subs = (
        db.query(Subscription)
        .filter(
            Subscription.is_active == True,
            Subscription.next_payment_date == target_date
        )
        .all()
    )

    sent = 0
    for sub in due_subs:
        # Check if already reminded for this cycle
        already = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.subscription_id == sub.id,
                NotificationLog.type == "reminder",
                NotificationLog.sent_at >= today
            )
            .first()
        )
        if not already:
            if send_subscription_reminder(sub, db):
                sent += 1

    # Also resend unacknowledged reminders
    resent = resend_unacknowledged(db)

    return sent + resent


def run_reminder_check(db: Session) -> dict:
    """Run the full reminder check. Returns summary."""
    new_reminders = check_upcoming_charges(db)
    return {
        "new_reminders": new_reminders,
        "checked_at": datetime.now(timezone.utc).isoformat()
    }
