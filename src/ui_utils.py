"""
Shared chat utilities for navigation and element discovery.
These helpers are side-effect free (except for Playwright interactions)
and do not depend on BossService internals.
"""

from __future__ import annotations
from typing import Any, Optional
from .global_logger import get_logger
logger = get_logger()

# used to detect resume overlay
IFRAME_OVERLAY_SELECTOR = "iframe[src*='c-resume'], iframe[name='recommendFrame']"
RESUME_OVERLAY_SELECTOR = "div.boss-popup__wrapper"
CLOSE_BTN = "div.boss-popup__close"


def ensure_on_chat_page(page, settings, logger=lambda msg, level: None, timeout_ms: int = 6000) -> bool:
    """Ensure we are on the chat page; navigate if necessary. Returns True if ok."""
    if settings.CHAT_URL not in getattr(page, 'url', ''):
        page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_load_state("networkidle", timeout=5000)
        return True
    return True


def find_chat_item(page, chat_id: str):
    """Return a locator to the chat list item for chat_id, or None if not found."""
    precise = page.locator(
        f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
        f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
    ).first
    if precise and precise.count() > 0:
        return precise

    # Fallback scan
    for sel in ["div.geek-item", "[role='listitem']"]:
        items = page.locator(sel).all()
        for it in items:
            did = it.get_attribute('data-id') or it.get_attribute('id')
            if did and chat_id and did == chat_id:
                return it
    return None


def close_overlay_dialogs(page, timeout_ms: int = 1000) -> bool:
    """Close any overlay dialogs that might be blocking the page."""
    try:
        # Try closing directly
        btn = page.locator(CLOSE_BTN)
        btn.click(timeout=timeout_ms)
        return True
    except Exception:
        try:
            # Try closing inside iframe
            overlay = page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=timeout_ms)
            if iframe := overlay.content_frame():
                btn = iframe.locator(CLOSE_BTN)
                btn.click(timeout=timeout_ms)
                return True
            return False
        except Exception:
            return False