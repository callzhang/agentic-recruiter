"""Async recommendation page actions for Boss Zhipin automation."""

import asyncio
import time
from typing import Any, Dict, List

from playwright.async_api import Frame, Locator, Page

from src.config import get_boss_zhipin_config
from .global_logger import get_logger
from .resume_capture_async import (
    _create_error_result,
    _get_resume_handle,
    _install_parent_message_listener,
    _process_resume_entry,
    _setup_wasm_route,
    collect_resume_debug_info,
)
from .ui_utils import IFRAME_OVERLAY_SELECTOR, close_overlay_dialogs

logger = get_logger()

CANDIDATE_CARD_SELECTOR = "div.candidate-card-wrap"
JOB_POPOVER_SELECTOR = "div.ui-dropmenu"
JOB_SELECTOR = "div.ui-dropmenu >> ul.job-list > li"



async def _prepare_recommendation_page(page: Page, job_title: str = None, *, wait_timeout: int = 15000) -> Frame:
    """
    Navigates and configures the recommendation page for automated actions.

    This function ensures the recommendation page is ready by:
    - Closing any overlay dialogs.
    - Navigating to the recommendation page if not already there.
    - Switching to the specified job title (if provided), if not already selected.
    - Waiting for candidate cards to become visible after each navigation step.

    Args:
        page (Page): The Playwright Page instance.
        job_title (str, optional): The job title to select from the dropdown.
        wait_timeout (int, optional): Timeout in milliseconds to wait for visibility. Defaults to 8000.

    Returns:
        Frame: The configured recommendation iframe Frame object, ready for further actions.
    """
    await close_overlay_dialogs(page)
    boss_config = get_boss_zhipin_config()
    if boss_config["recommend_url"] not in page.url:
        menu_chat = page.locator("dl.menu-recommend").first
        await menu_chat.click(timeout=10000)

    iframe = await page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=wait_timeout)
    frame = await iframe.content_frame()
    if not frame:
        raise RuntimeError("推荐页面 iframe 未找到")
    await frame.wait_for_selector(CANDIDATE_CARD_SELECTOR, timeout=wait_timeout)
    
    # Select job title if provided
    if job_title:
        job_options = frame.locator(JOB_SELECTOR)
        count = await job_options.count()
        if count == 0:
            raise ValueError("未找到职位下拉菜单")

        dropdown_label = frame.locator(JOB_POPOVER_SELECTOR).first
        current_selected_job = await dropdown_label.inner_text(timeout=500)
        if job_title in current_selected_job:
            return frame
        # Only change if not already selected
        job_titles = [await option.inner_text(timeout=500) for option in await job_options.all()]
        try:
            job_idx = next(i for i, c in enumerate(job_titles) if job_title in c)
        except StopIteration:
            error_msg = f"未找到包含'{job_title}'的职位。可用职位: {', '.join(job_titles)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        # click the job option
        await frame.locator(JOB_POPOVER_SELECTOR).click(timeout=1000)
        await job_options.nth(job_idx).click(timeout=1000)
        # Wait for selection to take effect
        t0 = time.time()
        while job_title not in current_selected_job:
            current_selected_job = await dropdown_label.inner_text(timeout=500)
            await page.wait_for_timeout(200)
            if time.time() - t0 > wait_timeout:
                raise ValueError(f"职位选择可能失败。当前选择: {current_selected_job}")
            
    
    logger.debug("已导航到推荐页面")
    return frame


async def list_recommended_candidates_action(page: Page, *, limit: int = 999, job_title: str, new_only: bool = True, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    List recommended candidates from the Boss直聘推荐页面.

    Navigates to the recommendation iframe and optionally filters by the specified job title. Extracts structured data for each candidate card found, up to the provided limit.

    Args:
        page (Page): Playwright page object.
        limit (int, optional): Maximum number of candidates to retrieve. Defaults to 20.
        job_title (str, optional): Job title to filter candidates by. If provided, the recommendation list will be filtered accordingly.
        new_only (bool): If True, only include new candidates (not yet viewed/greeted). *(Not currently implemented; reserved for future)*
        filters (Dict[str, Any], optional): Candidate filters dictionary to apply on the recommendation page. If provided, filters will be applied before listing candidates.
    Returns:
        List[Dict[str, Any]]: List of dictionaries, each representing a recommended candidate with standardized fields:
            - index: Position in the current list
            - chat_id: None (no chat established yet)
            - name: Candidate name (str)
            - job_title: Job title used for filter (str)
            - text: Resume snippet/summary (str)
            - viewed: Whether the candidate card has already been viewed (bool)
            - greeted: Whether greeted (bool)
            - stage: "GREET" if greeted, else None

    Raises:
        ValueError: If no candidates are found on the recommendation page, or if page navigation fails.

    Usage:
        Call this after logging in and loading the Boss直聘推荐页面. Use returned candidate indices for downstream actions (e.g., resume view or greeting).
    """
    frame = await _prepare_recommendation_page(page, job_title=job_title)
    # apply filters if provided
    if filters:
        await apply_filters(frame, filters)
    candidates: List[Dict[str, Any]] = []
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    t0 = time.time()
    while time.time() - t0 < 8000:
        count = await cards.count()
        if count > 0:
            break
        await page.wait_for_timeout(200)
        logger.debug("等待推荐候选人卡片出现... %d 秒", time.time() - t0)
    else:
        raise ValueError("未找到推荐候选人")

    for index in range(count):
        card = cards.nth(index)
        await card.hover(timeout=3000)
        classes = await card.get_attribute("class") or ""
        viewed = "viewed" in classes
        greeted = await card.locator("button:has-text('继续沟通')").count() > 0
        name = (await card.locator("span.name").inner_text()).strip()
        text = (await card.inner_text()).replace(name, "")
        
        # Create candidate dict with standardized field names for web UI
        if not new_only or not viewed:
            candidates.append({
                "index": index,  # Position in the current list
                # "chat_id": None,  # Recommend candidates don't have a chat_id yet
                "name": name,
                "job_applied": job_title,  # Standardized field name
                "last_message": text,
                "viewed": viewed,
                "greeted": greeted,
                'mode': 'recommend',
            })
        if len(candidates) >= limit:
            break
    else:
        logger.warning("获取的推荐候选人数量少于需求量，实际获取数量: %d", len(candidates))
    
    logger.info("成功获取 %d 个推荐候选人", len(candidates))
    return candidates


async def view_recommend_candidate_resume_action(page: Page, index: int) -> Dict[str, Any]:
    """View recommended candidate's resume. Returns dict with 'text'. Raises ValueError on failure."""
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        raise ValueError(f"候选人索引 {index} 超出范围")

    card = cards.nth(index)
    await card.hover(timeout=5000)
    await card.click(timeout=800)
    await _setup_wasm_route(page.context)
    await _install_parent_message_listener(page, logger)

    context = await _get_resume_handle(page, 20000, logger)
    if not context.get("success"):
        raise ValueError(context.get("details", "未找到在线简历"))

    result = await _process_resume_entry(page, context, logger)
    if not result.get("success"):
        debug = await collect_resume_debug_info(page)
        raise RuntimeError(f"处理简历失败: {result.get('details', '未知错误')}, debug: {debug}")
    
    logger.debug("处理推荐候选人简历结果: %s", result.get('text', '')[:100])
    return result


async def greet_recommend_candidate_action(page: Page, index: int, message: str = None) -> bool:
    """Greet recommended candidate with message. Returns True on success, raises ValueError on failure."""
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        raise ValueError(f"候选人索引 {index} 超出范围")

    card = cards.nth(index)
    await card.hover(timeout=3000)

    greet_selectors = [
        "button.btn-greet",
        "button:has-text('打招呼')",
        "span:has-text('打招呼')",
    ]
    chat_selectors = "button:has-text('继续沟通')"
    greeted = False
    for selector in greet_selectors:
        target = card.locator(selector).first
        if await target.count() > 0:
            await target.click(timeout=2000)
            greeted = True
            break
    if not greeted:
        if await card.locator(chat_selectors).count() > 0:
            pass
        else:
            raise ValueError("未找到打招呼按钮")

    if message:
        try:
            # 点击继续沟通按钮
            await page.wait_for_timeout(3000)
            chat_btn = card.locator(chat_selectors)
            await chat_btn.click(timeout=1000)
            # input_box = page.locator("div.conversation-bd-content").first
            # await input_box.click(timeout=1000)
            # 点击输入框
            input_field = page.locator("div.bosschat-chat-input").first
            await input_field.fill("", timeout=5000)
            await input_field.type(message)
            send_btn = page.locator("span:has-text('发送')").first
            if await send_btn.count() > 0:
                await send_btn.click(timeout=1000)
            else:
                await page.keyboard.press("Enter")
            close_btn = page.locator("div.iboss-close").first
            await close_btn.click(timeout=1000)
        except Exception as e:
            logger.error("发送消息失败: %s", e)
    logger.info("打招呼成功")
    return True


async def discard_recommend_candidate_action(page: Page, index: int, reason: str = "过往经历不符") -> bool:
    """Discard a recommendation candidate.
    Args:
        page: The Playwright Page instance.
        index: The index of the candidate to discard.
        reason: The reason for discarding the candidate. Can be one of the following:
            - 求职期望不符
            - 活跃度低
            - 不考虑异地牛人
            - 学历不符
            - 过往经历不符
            - 年龄不符
            - 工作年限不符
            - 其他原因
    Returns:
        True if the candidate is discarded successfully, False otherwise.
    """
    frame = await _prepare_recommendation_page(page)
    cards = frame.locator(CANDIDATE_CARD_SELECTOR)
    if index >= await cards.count():
        raise ValueError(f"候选人索引 {index} 超出范围")

    card = cards.nth(index)
    discard_btn = card.locator("button.btn-quxiao:has-text('不合适')").first
    if await discard_btn.count() > 0:
        await discard_btn.click(timeout=1000)
        await page.wait_for_timeout(1000)
    else:
        raise ValueError("未找到不合适按钮")
    # click the popup dialog's close button
    reason = card.locator("span.btn-quxiao:has-text('过往经历不符')").first
    comfirm_btn = card.locator("span.boss-dialog__button:has-text('提交')").first
    if await reason.count() > 0:
        await reason.click(timeout=1000)
        await comfirm_btn.click(timeout=1000)
        return True
    else:
        raise ValueError("未找到不合适原因")
    return False


async def apply_filters(frame: Frame, filters: Dict[str, Any]) -> bool:
    """Apply filters to the recommendation page.
    
    This function applies various filter criteria to the recommendation page
    to narrow down candidate search results.
    
    Args:
        frame: The recommendation page iframe Frame object
        filters: Dictionary containing filter criteria. If None, uses default filters.
                 Expected structure:
    Raises:
        ValueError: If filter application fails or required elements not found
    """

    # open the filter panel
    filter_wrap = frame.locator("div.recommend-filter")
    filter_panel = filter_wrap.locator("div.filter-panel")
    panel_down = filter_wrap.locator("span.filter-arrow-down")
    if await panel_down.count() > 0:
        # await panel_down.click(timeout=1000)
        logger.debug("Filter panel already applied")
        cancel_btn = filter_panel.locator("div.btn:has-text('取消')")
        if await cancel_btn.count() > 0:
            await cancel_btn.click(timeout=1000)
        return True
    if await filter_panel.count() == 0:
        # open the filter panel
        await filter_wrap.click(timeout=1000)
        await page.wait_for_timeout(500)
        # Wait for panel to appear
        await filter_panel.wait_for(state="visible", timeout=1000)
    # 取消上次设置
    reapply_button = frame.locator('div.cancel')
    if await reapply_button.count() > 0:
        await reapply_button.click(timeout=1000)
    
    # apply filters
    logger.debug("开始应用筛选条件: %s", filters)
    for key, value in filters.items():
        if key == "只看第一学历":
            await filter_panel.locator("div.first-degree-wrap").click(timeout=1000)
            continue
        # Find the parent "div.filter-wrap" that contains a child "div.name:has-text('{key}')"
        filter_wrap_item = filter_panel.locator(f"div.filter-wrap:has(div.name:has-text('{key}'))").first
        if await filter_wrap_item.count() == 0:
            logger.warning(f"未找到筛选项: {key}")
            continue
        if type(value) is str:
            value = [value]
        for v in value:
            try:
                option = filter_wrap_item.locator(f"div.option:has-text('{v}')")
                if await option.count() > 0:
                    await option.click(timeout=1000)
                else:
                    logger.warning(f"未找到筛选选项: {key} = {v}")
            except Exception as e:
                logger.error(f"点击筛选选项失败 {key} = {v}: {e}")
    
    # confirm
    confirm_btn = filter_panel.locator("div.btn:has-text('确定')")
    if await confirm_btn.count() > 0:
        await confirm_btn.click(timeout=1000)
    else:
        logger.warning("未找到确定按钮")
    
    return True
    

__all__ = [
    "_prepare_recommendation_page",
    "select_recommend_job_action",
    "list_recommended_candidates_action",
    "view_recommend_candidate_resume_action",
    "greet_recommend_candidate_action",
    "discard_recommend_candidate_action",
    "apply_filters",
]
