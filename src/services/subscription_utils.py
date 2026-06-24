"""
Helpers for subscription math and duplicate cleanup.
"""
from collections import defaultdict
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Subscription


def normalize_service_name(name: str) -> str:
    return " ".join((name or "").strip().casefold().split())


def monthly_equivalent(subscription: Subscription) -> float:
    if subscription.frequency == "quarterly":
        return subscription.amount / 3
    if subscription.frequency == "yearly":
        return subscription.amount / 12
    return subscription.amount


def calculate_monthly_totals_by_currency(subscriptions: Iterable[Subscription]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for subscription in subscriptions:
        currency = (subscription.currency or "USD").upper()
        totals[currency] += monthly_equivalent(subscription)
    return dict(sorted(totals.items()))


def deactivate_duplicate_subscriptions(db: Session) -> int:
    """
    Keep one active subscription per exact billing signature and deactivate extras.
    """
    active_subs = (
        db.query(Subscription)
        .filter(Subscription.is_active == True)
        .order_by(Subscription.id.asc())
        .all()
    )

    seen: dict[tuple[str, float, str, str], Subscription] = {}
    changed = 0

    for subscription in active_subs:
        key = (
            normalize_service_name(subscription.service_name),
            round(float(subscription.amount), 2),
            (subscription.currency or "USD").upper(),
            (subscription.frequency or "monthly").casefold(),
        )
        keeper = seen.get(key)
        if keeper is None:
            seen[key] = subscription
            continue

        if subscription.last_payment_date and (
            not keeper.last_payment_date or subscription.last_payment_date > keeper.last_payment_date
        ):
            keeper.last_payment_date = subscription.last_payment_date
        if subscription.next_payment_date and (
            not keeper.next_payment_date or subscription.next_payment_date < keeper.next_payment_date
        ):
            keeper.next_payment_date = subscription.next_payment_date
        if not keeper.notes and subscription.notes:
            keeper.notes = subscription.notes
        if keeper.source == "manual" and subscription.source != "manual":
            keeper.source = subscription.source

        subscription.is_active = False
        existing_note = (subscription.notes or "").strip()
        duplicate_note = f"Auto-disabled duplicate of subscription #{keeper.id}"
        subscription.notes = duplicate_note if not existing_note else f"{existing_note} | {duplicate_note}"
        changed += 1

    if changed:
        db.commit()

    return changed
