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
    job_options = frame.locator(JOB_SELECTOR)
    count = await job_options.count()
    if count == 0:
        return {"success": False, "details": "未找到职位下拉菜单"}

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
        return {
            "success": False,
            "details": f"未找到包含'{job_title}'的职位",
            "selected_job": current_selected_job,
            "available_jobs": available_jobs,
        }

    for _ in range(15):
        current_selected_job = await dropdown_label.inner_text(timeout=500)
        if job_title in current_selected_job:
            return {
                "success": True,
                "details": f"成功选择职位: {current_selected_job}",
                "selected_job": current_selected_job,
                "available_jobs": available_jobs,
            }
        await asyncio.sleep(0.2)

    return {
        "success": False,
        "details": "职位选择可能失败",
        "selected_job": current_selected_job,
        "available_jobs": available_jobs,
    }


async def list_recommended_candidates_action(page: Page, *, limit: int = 20) -> Dict[str, Any]:
    frame = await _prepare_recommendation_page(page)
    candidates: List[Dict[str, Any]] = []
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    count = await cards.count()
    if count == 0:
        return {"success": False, "details": "未找到推荐候选人", "candidates": []}

    for index in range(min(count, limit)):
        card = cards.nth(index)
        await card.scroll_into_view_if_needed(timeout=1000)
        classes = await card.get_attribute("class") or ""
        viewed = "viewed" in classes
        greeted = await card.locator("button:has-text('继续沟通')").count() > 0
        text = (await card.inner_text()).strip()
        candidates.append({"viewed": viewed, "greeted": greeted, "text": text})
    return {"success": True, "details": f"成功获取 {len(candidates)} 个推荐候选人", "candidates": candidates}


async def view_recommend_candidate_resume_action(page: Page, index: int) -> Dict[str, Any]:
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        return {"success": False, "details": "候选人索引超出范围"}

    card = cards.nth(index)
    await card.scroll_into_view_if_needed(timeout=1000)
    await card.click(timeout=800)

    await _setup_wasm_route(page.context)
    await _install_parent_message_listener(page, logger)

    context = await _get_resume_handle(page, 10000, logger)
    if not context.get("success"):
        return _create_error_result(context, context.get("details", "未找到在线简历"))

    result = await _process_resume_entry(page, context, logger)
    logger.info("处理推荐候选人简历结果: %s", result)
    if not result.get("success"):
        result["debug"] = await collect_resume_debug_info(page)
    return result


async def greet_recommend_candidate_action(page: Page, index: int, message: str) -> Dict[str, Any]:
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        return {"success": False, "details": "候选人索引超出范围"}

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
        return {"success": False, "details": "未找到打招呼按钮"}

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

    return {"success": True, "details": "打招呼成功"}


async def skip_recommend_candidate_action(page: Page, index: int) -> Dict[str, Any]:
    """Placeholder for skipping a recommendation card without interacting.

    # TODO: 实现推荐卡片跳过/标记逻辑
    """
    return {
        "success": False,
        "details": "TODO: implement skip logic for recommendation cards",
        "index": index,
    }


__all__ = [
    "_prepare_recommendation_page",
    "select_recommend_job_action",
    "list_recommended_candidates_action",
    "view_recommend_candidate_resume_action",
    "greet_recommend_candidate_action",
    "skip_recommend_candidate_action",
]
