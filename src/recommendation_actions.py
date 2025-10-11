"""Async recommendation page actions for Boss Zhipin automation."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from playwright.async_api import Frame, Locator, Page

from src.config import settings
from .global_logger import get_logger
from .resume_capture_async import (
    _create_error_result,
    _get_resume_handle,
    _install_parent_message_listener,
    _process_resume_entry,
    _setup_wasm_route,
    collect_resume_debug_info,
)
from .boss_utils import IFRAME_OVERLAY_SELECTOR, close_overlay_dialogs

logger = get_logger()

CANDIDATE_CARD_SELECTOR = "div.candidate-card-wrap"
JOB_POPOVER_SELECTOR = "div.ui-dropmenu"
JOB_SELECTOR = "div.ui-dropmenu >> ul.job-list > li"


async def _prepare_recommendation_page(page: Page, *, wait_timeout: int = 8000) -> Frame:
    await close_overlay_dialogs(page)
    if settings.RECOMMEND_URL not in page.url:
        menu_chat = page.locator("dl.menu-recommend").first
        await menu_chat.click(timeout=1000)

    iframe = await page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=wait_timeout)
    frame = await iframe.content_frame()
    if not frame:
        raise RuntimeError("推荐页面 iframe 未找到")
    await frame.wait_for_selector(CANDIDATE_CARD_SELECTOR, timeout=wait_timeout)
    logger.info("已导航到推荐页面")
    return frame


async def select_recommend_job_action(frame: Frame, job_title: str) -> Dict[str, Any]:
    """Select job from dropdown. Returns dict with 'selected_job' and 'available_jobs'. Raises ValueError on failure."""
    job_options = frame.locator(JOB_SELECTOR)
    count = await job_options.count()
    if count == 0:
        raise ValueError("未找到职位下拉菜单")

    dropdown_label = frame.locator(JOB_POPOVER_SELECTOR).first
    current_selected_job = await dropdown_label.inner_text(timeout=500)
    available_jobs: List[str] = []
    for index in range(count):
        option = job_options.nth(index)
        label = (await option.inner_text(timeout=500)).strip()
        available_jobs.append(label)
        if job_title in label:
            await frame.locator(JOB_POPOVER_SELECTOR).click(timeout=1000)
            await option.click(timeout=1000)
            break
    else:
        raise ValueError(f"未找到包含'{job_title}'的职位。可用职位: {', '.join(available_jobs)}")

    for _ in range(15):
        current_selected_job = await dropdown_label.inner_text(timeout=500)
        if job_title in current_selected_job:
            return {
                "selected_job": current_selected_job,
                "available_jobs": available_jobs,
            }
        await asyncio.sleep(0.2)

    raise ValueError(f"职位选择可能失败。当前选择: {current_selected_job}")


async def list_recommended_candidates_action(page: Page, *, limit: int = 20) -> List[Dict[str, Any]]:
    """List recommended candidates. Returns list of candidate dicts. Raises ValueError if no candidates found."""
    frame = await _prepare_recommendation_page(page)
    candidates: List[Dict[str, Any]] = []
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    count = await cards.count()
    if count == 0:
        raise ValueError("未找到推荐候选人")

    for index in range(min(count, limit)):
        card = cards.nth(index)
        await card.scroll_into_view_if_needed(timeout=1000)
        classes = await card.get_attribute("class") or ""
        viewed = "viewed" in classes
        greeted = await card.locator("button:has-text('继续沟通')").count() > 0
        text = (await card.inner_text()).strip()
        candidates.append({"viewed": viewed, "greeted": greeted, "text": text})
    
    logger.info("成功获取 %d 个推荐候选人", len(candidates))
    return candidates


async def view_recommend_candidate_resume_action(page: Page, index: int) -> Dict[str, Any]:
    """View recommended candidate's resume. Returns dict with 'text'. Raises ValueError on failure."""
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        raise ValueError(f"候选人索引 {index} 超出范围")

    card = cards.nth(index)
    await card.scroll_into_view_if_needed(timeout=1000)
    await card.click(timeout=800)

    await _setup_wasm_route(page.context)
    await _install_parent_message_listener(page, logger)

    context = await _get_resume_handle(page, 10000, logger)
    if not context.get("success"):
        raise ValueError(context.get("details", "未找到在线简历"))

    result = await _process_resume_entry(page, context, logger)
    if not result.get("success"):
        debug = await collect_resume_debug_info(page)
        raise RuntimeError(f"处理简历失败: {result.get('details', '未知错误')}, debug: {debug}")
    
    logger.info("处理推荐候选人简历结果: %s", result.get('text', '')[:100])
    return result


async def greet_recommend_candidate_action(page: Page, index: int, message: str) -> bool:
    """Greet recommended candidate with message. Returns True on success, raises ValueError on failure."""
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        raise ValueError(f"候选人索引 {index} 超出范围")

    card = cards.nth(index)
    await card.scroll_into_view_if_needed(timeout=1000)

    greet_selectors = [
        "button.btn-greet",
        "button:has-text('打招呼')",
        "span:has-text('打招呼')",
    ]
    greeted = False
    for selector in greet_selectors:
        target = card.locator(selector).first
        if await target.count() > 0:
            await target.click(timeout=2000)
            greeted = True
            break
    if not greeted:
        raise ValueError("未找到打招呼按钮")

    if message:
        chat_btn = card.locator("button:has-text('继续沟通')").first
        if await chat_btn.count() > 0:
            await chat_btn.click(timeout=1000)
        input_box = page.locator("div.conversation-bd-content").first
        await input_box.click()
        input_field = input_box.locator("div.bosschat-chat-input").first
        await input_field.fill("")
        await input_field.type(message)
        send_btn = page.locator("span:has-text('发送')").first
        if await send_btn.count() > 0:
            await send_btn.click(timeout=1000)
        else:
            await page.keyboard.press("Enter")

    logger.info("打招呼成功")
    return True


async def skip_recommend_candidate_action(page: Page, index: int) -> bool:
    """Placeholder for skipping a recommendation card without interacting.

    # TODO: 实现推荐卡片跳过/标记逻辑
    """
    raise NotImplementedError("TODO: implement skip logic for recommendation cards")


__all__ = [
    "_prepare_recommendation_page",
    "select_recommend_job_action",
    "list_recommended_candidates_action",
    "view_recommend_candidate_resume_action",
    "greet_recommend_candidate_action",
    "skip_recommend_candidate_action",
]
