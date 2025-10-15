"""
Shared chat utilities for navigation and element discovery.
These helpers are side-effect free (except for Playwright interactions)
and do not depend on BossService internals.
"""

from __future__ import annotations

from typing import Any, Optional

from .global_logger import logger

# used to detect resume overlay
IFRAME_OVERLAY_SELECTOR = "iframe[src*='c-resume'], iframe[name='recommendFrame']"
RESUME_OVERLAY_SELECTOR = "div.boss-popup__wrapper"
CLOSE_BTN = "div.boss-popup__close"


async def ensure_on_chat_page(page, settings, logger=lambda msg, level: None, timeout_ms: int = 6000) -> bool:
    """Ensure we are on the chat page; navigate if necessary. Returns True if ok."""
    if settings.CHAT_URL not in getattr(page, "url", ""):
        await page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        # await page.wait_for_load_state("networkidle", timeout=5000)
        return True
    return True


async def find_chat_item(page, chat_id: str):
    """Return a locator to the chat list item for chat_id, or None if not found."""
    precise = page.locator(
        f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
        f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
    ).first
    if await precise.count() > 0:
        return precise

    # Fallback scan
    for sel in ["div.geek-item", "[role='listitem']"]:
        items = page.locator(sel)
        count = await items.count()
        for index in range(count):
            it = items.nth(index)
            data_id = await it.get_attribute("data-id")
            item_id = await it.get_attribute("id") if data_id is None else None
            did = data_id or item_id
            if did and chat_id and did == chat_id:
                return it
    return None


async def close_overlay_dialogs(page, timeout_ms: int = 1000) -> bool:
    """Close any overlay dialogs that might be blocking the page."""
    btn = page.locator(CLOSE_BTN)
    if await btn.count() > 0:
        await btn.click(timeout=timeout_ms)
        return True

    overlay = page.locator(IFRAME_OVERLAY_SELECTOR)
    if await overlay.count() > 0:
        frame = overlay.content_frame
        iframe_btn = frame.locator(CLOSE_BTN)
        if await iframe_btn.count() > 0:
            await iframe_btn.click(timeout=timeout_ms)
            return True

    # close recommendation page's popup dialog
    close_btn = page.locator("div.iboss-close").first
    if await close_btn.count() > 0:
        await close_btn.click(timeout=1000)
        return True
    return False
