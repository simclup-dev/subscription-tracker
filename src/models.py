from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_name = Column(String(200), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    frequency = Column(String(20), nullable=False)  # monthly, yearly, quarterly, weekly
    last_payment_date = Column(Date, nullable=True)
    next_payment_date = Column(Date, nullable=False)
    category = Column(String(50), default="other")
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    source = Column(String(20), default="manual")  # manual or gmail_scan
    email_sender_pattern = Column(String(300), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    payments = relationship("PaymentHistory", back_populates="subscription", cascade="all, delete-orphan")
    notifications = relationship("NotificationLog", back_populates="subscription", cascade="all, delete-orphan")


class PaymentHistory(Base):
    __tablename__ = "payment_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    payment_date = Column(Date, nullable=False)
    email_id = Column(String(200), default="")
    raw_data = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    subscription = relationship("Subscription", back_populates="payments")


class ProviderBalance(Base):
    __tablename__ = "provider_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_name = Column(String(50), nullable=False, unique=True)
    balance = Column(Float, nullable=True)          # current balance (for DeepSeek, Google)
    limit_total = Column(Float, nullable=True)      # total limit (for Ollama, Anthropic)
    limit_used_percent = Column(Float, nullable=True)  # % used (for Ollama)
    spent = Column(Float, nullable=True)            # amount spent (for Google)
    currency = Column(String(10), default="USD")
    is_subscription = Column(Boolean, default=False)  # Anthropic=subscription
    raw_response = Column(Text, default="")
    last_checked = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    type = Column(String(20), nullable=False)  # reminder, alert, low_balance
    message = Column(Text, nullable=False)
    channel = Column(String(20), default="telegram")  # telegram, dashboard
    telegram_message_id = Column(Integer, nullable=True)
    acknowledged = Column(Boolean, default=False)  # user clicked "read"
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    acknowledged_at = Column(DateTime, nullable=True)

    subscription = relationship("Subscription", back_populates="notifications")
