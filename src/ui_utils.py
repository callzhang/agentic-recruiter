"""Async Playwright helpers shared across chat and recommendation flows."""

from __future__ import annotations

from typing import Optional

from playwright.async_api import Page

from .global_logger import logger

# selectors reused across modules
IFRAME_OVERLAY_SELECTOR = "iframe[src*='c-resume'], iframe[name='recommendFrame']"
RESUME_OVERLAY_SELECTOR = "div.boss-popup__wrapper"
CLOSE_BTN = "div.boss-popup__close"


async def ensure_on_chat_page(page: Page, logger=logger, timeout_ms: int = 15000) -> bool:
    """Navigate to the chat page when current URL is off target."""
    from .config import get_boss_zhipin_config
    boss_config = get_boss_zhipin_config()
    if boss_config["chat_url"] not in getattr(page, "url", ""):
        await page.goto(boss_config["chat_url"], wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        await page.wait_for_selector('div.chat-user', timeout=timeout_ms)
    return True


async def find_chat_item(page: Page, chat_id: str):
    """Return a locator to the chat item for ``chat_id`` if present."""
    precise = page.locator(
        f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
        f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
    ).first
    if await precise.count() > 0:
        return precise

    for selector in ("div.geek-item", "[role='listitem']"):
        items = page.locator(selector)
        count = await items.count()
        for index in range(count):
            item = items.nth(index)
            data_id = await item.get_attribute("data-id")
            item_id = await item.get_attribute("id") if data_id is None else None
            resolved = data_id or item_id
            if resolved and resolved == chat_id:
                return item
    return None


async def close_overlay_dialogs(page: Page, timeout_ms: int = 1000) -> bool:
    """Attempt to close blocking overlays on the current page."""
    btn = page.locator(CLOSE_BTN)
    try:
        if await btn.count() > 0:
            await btn.click(timeout=timeout_ms)
            return True
    except Exception:
        pass

    try:
        overlay = await page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=timeout_ms)
    except Exception:
        return False

    try:
        frame = await overlay.content_frame()
    except Exception:
        frame = None

    if frame is None:
        return False

    try:
        iframe_btn = frame.locator(CLOSE_BTN)
        if await iframe_btn.count() > 0:
            await iframe_btn.click(timeout=timeout_ms)
            return True
    except Exception:
        return False
    
    # Close recommendation page's popup dialog
    try:
        close_btn = page.locator("div.iboss-close").first
        if await close_btn.count() > 0:
            await close_btn.click(timeout=1000)
            return True
    except Exception:
        pass
    
    return False


async def safe_evaluate_in_fresh_context(selector: str) -> str:
    """Safely evaluate a selector by creating a fresh page context in the current event loop."""
    from playwright.async_api import async_playwright
    from src.config import get_browser_config
    
    browser_config = get_browser_config()
    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(browser_config["cdp_url"])
    
    try:
        # Get the first available page or create a new one
        if browser.contexts and browser.contexts[0].pages:
            page = browser.contexts[0].pages[0]
        else:
            context = await browser.new_context()
            page = await context.new_page()
        
        return await page.evaluate(f"""
            () => {{
                const element = document.querySelector('{selector}');
                return element ? element.innerText : '';
            }}
        """)
    finally:
        await browser.close()
        await playwright.stop()
