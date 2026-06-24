"""
Provider Poller — fetches balance/usage from AI providers every N minutes.
Supports: DeepSeek (USD balance), Google AI Studio (spent vs deposited),
          Ollama Cloud (session/weekly % used), Anthropic (bookmarklet).
"""
import re
import hashlib
import time
import httpx
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from ..config import DEEPSEEK_API_KEY, GOOGLE_COOKIE, GOOGLE_API_KEY, OLLAMA_COOKIE
from ..models import ProviderBalance


def generate_sapisidhash(sapisid: str, origin: str = "https://aistudio.google.com") -> str:
    """Generate SAPISIDHASH from SAPISID cookie (Google's internal auth)."""
    timestamp = str(int(time.time()))
    message = f"{timestamp} {sapisid} {origin}"
    digest = hashlib.sha1(message.encode()).hexdigest()
    return f"SAPISIDHASH {timestamp}_{digest}"


def extract_sapisid(cookie_str: str) -> str:
    """Extract SAPISID value from cookie string."""
    match = re.search(r"SAPISID=([^;]+)", cookie_str)
    return match.group(1) if match else ""


# ─── DeepSeek ─────────────────────────────────────────────
def poll_deepseek(db: Session) -> ProviderBalance:
    """Fetch DeepSeek balance (USD)."""
    provider = db.query(ProviderBalance).filter_by(provider_name="deepseek").first()
    if not provider:
        provider = ProviderBalance(provider_name="deepseek", currency="USD")
        db.add(provider)

    try:
        resp = httpx.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            balances = data.get("balance_infos", [])
            if balances:
                bal = float(balances[0].get("total_balance", 0))
                currency = balances[0].get("currency", "USD")
                provider.balance = bal
                provider.currency = currency
            provider.last_error = ""
        else:
            provider.last_error = f"HTTP {resp.status_code}"
    except Exception as e:
        provider.last_error = str(e)[:200]

    provider.last_checked = datetime.now(timezone.utc)
    provider.raw_response = str(resp.json() if 'resp' in dir() and resp.status_code == 200 else "")[:500]
    db.commit()
    return provider


# ─── Google AI Studio ─────────────────────────────────────
def poll_google_ai(db: Session) -> ProviderBalance:
    """Google AI Studio: keep existing bookmarklet data, just update timestamp."""
    provider = db.query(ProviderBalance).filter_by(provider_name="google_ai").first()
    if not provider:
        provider = ProviderBalance(provider_name="google_ai", currency="USD", balance=12.0, spent=0.0)
        db.add(provider)

    provider.last_checked = datetime.now(timezone.utc)
    if provider.spent is None or provider.spent == 0.0:
        provider.last_error = "Натисни bookmarklet на aistudio.google.com/spend"
    else:
        provider.last_error = ""
    db.commit()
    return provider


# ─── Ollama Cloud ─────────────────────────────────────────
def poll_ollama(db: Session) -> ProviderBalance:
    """Fetch Ollama Cloud usage by scraping settings page HTML."""
    provider = db.query(ProviderBalance).filter_by(provider_name="ollama").first()
    if not provider:
        provider = ProviderBalance(provider_name="ollama", currency="USD", limit_used_percent=0.0)
        db.add(provider)

    try:
        resp = httpx.get(
            "https://ollama.com/settings",
            headers={"Cookie": OLLAMA_COOKIE},
            follow_redirects=False,
            timeout=15
        )

        # Cookie expired → Ollama redirects to login
        if resp.status_code in (301, 302, 303, 307, 308):
            provider.last_error = "Cookie протух — оновити в трекері (/ollama)"
            provider.last_checked = datetime.now(timezone.utc)
            db.commit()
            return provider

        if resp.status_code == 200:
            html = resp.text

            # Detect login page (cookie expired but no redirect)
            if "sign in" in html.lower() or "log in" in html.lower() or "<title>Sign" in html:
                provider.last_error = "Cookie протух — оновити в трекері (/ollama)"
                provider.last_checked = datetime.now(timezone.utc)
                db.commit()
                return provider

            session_match = re.search(r"Session usage.*?([\d.]+)% used", html, re.DOTALL)
            weekly_match = re.search(r"Weekly usage.*?([\d.]+)% used", html, re.DOTALL)
            # "Resets in 1 hour." / "Resets in 3 days." after each block
            session_reset_match = re.search(r"Session usage.*?Resets in ([^\n<.]+)\.", html, re.DOTALL)
            weekly_reset_match  = re.search(r"Weekly usage.*?Resets in ([^\n<.]+)\.", html, re.DOTALL)

            session_pct = float(session_match.group(1)) if session_match else None
            weekly_pct  = float(weekly_match.group(1))  if weekly_match  else None
            session_reset = session_reset_match.group(1).strip() if session_reset_match else None
            weekly_reset  = weekly_reset_match.group(1).strip()  if weekly_reset_match  else None

            if session_pct is None and weekly_pct is None:
                provider.last_error = "Не знайдено % використання — перевір cookie або структуру сторінки"
            else:
                provider.limit_used_percent = max(p for p in [session_pct, weekly_pct] if p is not None)
                provider.limit_total = 100.0
                parts = []
                if session_pct is not None:
                    parts.append(f"session={session_pct}%{(' (→' + session_reset + ')') if session_reset else ''}")
                if weekly_pct is not None:
                    parts.append(f"weekly={weekly_pct}%{(' (→' + weekly_reset + ')') if weekly_reset else ''}")
                provider.raw_response = "; ".join(parts)
                provider.last_error = ""
        else:
            provider.last_error = f"HTTP {resp.status_code}"
    except Exception as e:
        provider.last_error = str(e)[:200]

    provider.last_checked = datetime.now(timezone.utc)
    db.commit()
    return provider


# ─── Anthropic (Claude.ai subscription) ───────────────────
def init_anthropic(db: Session) -> ProviderBalance:
    """Ensure Anthropic provider row exists; data updated via bookmarklet."""
    provider = db.query(ProviderBalance).filter_by(provider_name="anthropic").first()
    if not provider:
        provider = ProviderBalance(
            provider_name="anthropic",
            currency="USD",
            is_subscription=True,
        )
        db.add(provider)
        db.commit()
    return provider


def poll_all_providers(db: Session) -> dict:
    """Poll all providers. Returns summary dict."""
    results = {}
    if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "sk-your-deepseek-api-key":
        results["deepseek"] = poll_deepseek(db)
    if GOOGLE_COOKIE and GOOGLE_COOKIE != "PASTE_FULL_COOKIE_STRING_HERE":
        results["google_ai"] = poll_google_ai(db)
    if OLLAMA_COOKIE and OLLAMA_COOKIE != "PASTE_FULL_COOKIE_STRING_HERE":
        results["ollama"] = poll_ollama(db)
    # Always keep Anthropic row alive
    results["anthropic"] = init_anthropic(db)
    return results
