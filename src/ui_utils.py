"""
Shared chat utilities for navigation and element discovery.
These helpers are side-effect free (except for Playwright interactions)
and do not depend on BossService internals.
"""

from __future__ import annotations
from typing import Any, Optional
from .global_logger import get_logger
logger = get_logger()

# used to detect resume overlay, 
IFRAME_OVERLAY_SELECTOR = "iframe[src*='c-resume'], iframe[name='recommendFrame']"
RESUME_OVERLAY_SELECTOR = "div.boss-popup__wrapper"
CLOSE_BTN = "div.boss-popup__close"


def ensure_on_chat_page(page, settings, logger=lambda msg, level: None, timeout_ms: int = 6000) -> bool:
    """Ensure we are on the chat page; navigate if necessary. Returns True if ok."""
    try:
        if settings.CHAT_URL not in getattr(page, 'url', ''):
            try:
                page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            except Exception as e:
                logger(f"导航聊天页面失败: {e}", "warning")
                return False
        return True
    except Exception:
        return False


def find_chat_item(page, chat_id: str):
    """Return a locator to the chat list item for chat_id, or None if not found."""
    try:
        precise = page.locator(
            f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
            f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
        ).first
        if precise and precise.count() > 0:
            return precise
    except Exception:
        pass
    # Fallback scan
    try:
        for sel in ["div.geek-item", "[role='listitem']"]:
            try:
                items = page.locator(sel).all()
            except Exception:
                items = []
            for it in items:
                try:
                    did = it.get_attribute('data-id') or it.get_attribute('id')
                    if did and chat_id and did == chat_id:
                        return it
                except Exception:
                    continue
    except Exception:
        pass
    return None


def close_overlay_dialogs(page, timeout_ms: int = 1000) -> bool:
    """Close any overlay dialogs that might be blocking the page.
    """
    try: # close directly
        btn = page.locator(CLOSE_BTN)
        btn.click(timeout=timeout_ms)
        return True
    except Exception:
        try: # iframe >> #boss-dynamic-dialog-1j67hfgpm > div.boss-popup__wrapper.boss-dialog.boss-dialog__wrapper.dialog-lib-resume.recommend > div.boss-popup__close
            overlay = page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=timeout_ms)
            if iframe:=overlay.content_frame():
                btn = iframe.locator(CLOSE_BTN)
                btn.click(timeout=timeout_ms)
                return True
            return False
        except Exception:
            return False

