"""
Shared chat utilities for navigation and element discovery.
These helpers are side-effect free (except for Playwright interactions)
and do not depend on BossService internals.
"""

from __future__ import annotations

from typing import Any, Optional


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


def close_overlay_dialogs(page, logger=lambda msg, level: None, timeout_ms: int = 1000) -> bool:
    """Close any overlay dialogs that might be blocking the page.
    """
    # Close boss-layer__wrapper overlays (like resume dialogs)
    overlay_resume = page.locator("div.boss-layer__wrapper, div.boss-popup__close, div[class*='boss-popup__close'], div[ka][class*='boss-popup__close']")
    for btn in overlay_resume.all():
        logger("检测到在线简历对话框，正在关闭", "info")
        btn.click(timeout=timeout_ms)


