"""Common high-level chat actions used by automation flows (async version)."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any, Dict, List, Optional
import time
from playwright.async_api import Locator, Page

from src.config import settings
from .global_logger import logger
from .resume_capture_async import (
    _create_error_result,
    _get_resume_handle,
    _install_parent_message_listener,
    _open_online_resume,
    _process_resume_entry,
    _setup_wasm_route,
    collect_resume_debug_info,
    extract_pdf_viewer_text,
)
from .ui_utils import close_overlay_dialogs, ensure_on_chat_page

CHAT_MENU_SELECTOR = "dl.menu-chat"
CHAT_ITEM_SELECTORS = "div.geek-item"
CONVERSATION_SELECTOR = "div.conversation-message"
MESSAGE_INPUT_SELECTOR = "#boss-chat-editor-input"
RESUME_BUTTON_SELECTOR = "div.resume-btn-file, a.resume-btn-file"
RESUME_IFRAME_SELECTOR = "iframe.attachment-box"
PDF_VIEWER_SELECTOR = "div.pdfViewer"


async def _prepare_chat_page(page: Page, tab = None, status = None, job_title = None, wait_timeout: int = 5000) -> Page:
    """
    Navigates and configures the chat page for automated actions.

    This function ensures the chat page is ready by:
    - Closing any overlay dialogs.
    - Navigating to the specified chat tab (if provided), and ensuring the correct tab is active.
    - Filtering by status (if provided), ensuring the correct status filter is applied.
    - Switching to the specified job title (if provided), if not already selected.
    - Waiting for chat items to become visible after each navigation/filtering step.

    Args:
        page (Page): The Playwright Page instance representing the chat page.
        tab (str, optional): The chat tab to select (e.g., "新招呼", "沟通中").
        status (str, optional): The chat status filter to apply.
        job_title (str, optional): The job title to select from the dropdown.
        wait_timeout (int, optional): Timeout in milliseconds to wait for visibility. Defaults to 5000.

    Returns:
        Page: The configured Page object, ready for further actions.
        
    Raises:
        ValueError: If filters result in no candidates being displayed.
    """
    await close_overlay_dialogs(page)
    await ensure_on_chat_page(page, settings, logger)

    if tab:
        tab_selector = f"div.chat-label-item[title*='{tab}']"
        chat_tab = page.locator(tab_selector).first
        if await chat_tab.count() > 0 and 'selected' not in await chat_tab.get_attribute("class"):
            await chat_tab.click()
            # Wait for page to update, then check if candidates exist
            start_time = time.time()
            while await page.locator(CHAT_ITEM_SELECTORS).first.count() == 0:
                await asyncio.sleep(0.5)
                if time.time() - start_time > wait_timeout:
                    raise ValueError(f"未找到标签为 '{tab}' 的对话")
    
    if status:
        status_selector = f"div.chat-message-filter-left > span:has-text('{status}')"
        chat_status = page.locator(status_selector).first
        if await chat_status.count() > 0 and 'active' not in await chat_status.get_attribute("class"):
            await chat_status.click()
            # Wait for page to update, then check if candidates exist
            start_time = time.time()
            while await page.locator(CHAT_ITEM_SELECTORS).first.count() == 0:
                await asyncio.sleep(0.5)
                if time.time() - start_time > wait_timeout:
                    raise ValueError(f"未找到状态为 '{status}' 的聊天对话")
    
    if job_title:
        current_job_selector = f"div.ui-dropmenu-label > span.chat-select-job"
        job_selector = f'div.ui-dropmenu-list >> li:has-text("{job_title}")'
        current_job_loc = page.locator(current_job_selector).first
        if await current_job_loc.count() > 0:
            current_job = await current_job_loc.inner_text()
            if job_title not in current_job:
                await current_job_loc.click()
                job_loc = page.locator(job_selector).first
                if await job_loc.count() > 0:
                    await job_loc.click()
                    # Wait for page to update, then check if candidates exist
                    start_time = time.time()
                    while await page.locator(CHAT_ITEM_SELECTORS).first.count() == 0:
                        await asyncio.sleep(0.5)
                        if time.time() - start_time > wait_timeout:
                            raise ValueError(f"未找到职位为 '{job_title}' 的岗位")

    return page


async def _go_to_chat_dialog(page: Page, chat_id: str, wait_timeout: int = 5000) -> Optional[Locator]:
    direct_selectors = [
        f"{CHAT_ITEM_SELECTORS}[data-id=\"{chat_id}\"]",
        f"[role='listitem'][data-id=\"{chat_id}\"]",
    ]
    target: Optional[Locator] = None
    for selector in direct_selectors:
        locator = page.locator(selector).first
        if await locator.count() > 0:
            target = locator
            break
    if not target:
        return None

    try:
        await target.scroll_into_view_if_needed(timeout=1000)
        classes = await target.get_attribute("class") or ""
        if "selected" not in classes:
            await target.click()
        await page.wait_for_selector(CONVERSATION_SELECTOR, timeout=wait_timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("定位聊天对话失败: %s", exc)
        return None
    return target



async def get_chat_stats_action(page: Page) -> Dict[str, Any]:
    """Get chat statistics including new message and greet counts."""
    await _prepare_chat_page(page)
    NEW_MESSAGE_SELECTOR = "span.menu-chat-badge"
    NEW_GREET_SELECTOR = "div.chat-label-item[title*='新招呼']"

    new_message_loc = page.locator(NEW_MESSAGE_SELECTOR)
    if await new_message_loc.count() > 0:
        new_message_count_text = await new_message_loc.inner_text(timeout=1000)
        new_message_count = int(new_message_count_text) if new_message_count_text else 0
    else:
        new_message_count = 0

    new_greet_loc = page.locator(NEW_GREET_SELECTOR)
    if await new_greet_loc.count() > 0:
        new_greet_text = await new_greet_loc.inner_text(timeout=1000)
        numbers = re.findall(r"\d+", new_greet_text)
        new_greet_count = int(numbers[0]) if numbers else 0
    else:
        new_greet_count = 0
    
    return {
        "new_message_count": new_message_count,
        "new_greet_count": new_greet_count,
    }



async def send_message_action(page: Page, chat_id: str, message: str) -> bool:
    """Send message to candidate. Returns True on success, raises ValueError on failure."""
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        raise ValueError("未找到指定对话项")

    input_field = page.locator(MESSAGE_INPUT_SELECTOR).first
    if await input_field.count() == 0:
        raise ValueError("未找到消息输入框")

    await input_field.wait_for(state="visible", timeout=3000)
    await input_field.click()
    await input_field.fill("")
    await input_field.type(message)

    send_button = page.locator("div.submit:has-text('发送')").first
    if await send_button.count() == 0:
        await page.keyboard.press("Enter")
    else:
        await send_button.wait_for(state="visible", timeout=3000)
        await send_button.click()

    await page.wait_for_timeout(1000)
    remaining = await input_field.evaluate("el => (el.value || el.innerText || '').trim()")
    if remaining:
        logger.warning("消息可能未发送成功，输入框仍有内容")
    
    return True


async def discard_candidate_action(page: Page, chat_id: str) -> bool:
    """Discard (PASS) candidate. Returns True on success, raises ValueError on failure."""
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        raise ValueError("未找到指定对话项")

    not_fit_button = page.locator("div.not-fit-wrap").first
    await not_fit_button.wait_for(state="visible", timeout=3000)
    await not_fit_button.hover()
    await asyncio.sleep(1)
    
    # wait for dialog to be deleted
    max_attempts = 10
    for _ in range(max_attempts):
        if not await _go_to_chat_dialog(page, chat_id):
            return True  # Successfully discarded
        await not_fit_button.click()
        await asyncio.sleep(0.5)
    
    # If we get here, the dialog wasn't deleted
    raise ValueError("PASS失败: 未删除对话")
    

async def list_conversations_action(page: Page, limit: int = 999, tab: str = '新招呼', status: str = '未读', job_title: str = '全部', unread_only=True) -> List[Dict[str, Any]]:
    '''Get candidate list from chat page
    Args:
        page: Page - The Playwright Page instance representing the chat page.
        limit: int - The maximum number of chat items to return.
        tab: str - The chat tab to select (e.g., "新招呼", "沟通中").
        status: str - The chat status filter to apply.
        job_title: str - The job title to select from the dropdown.
        unread_only: bool - Whether to only return unread candidates.
    Returns:
        List[Dict[str, Any]]: A list of candidate items.
    '''
    await _prepare_chat_page(page, tab, status, job_title)
    items = page.locator(CHAT_ITEM_SELECTORS)
    count = await items.count()
    messages: List[Dict[str, Any]] = []
    for index in range(count):
        item = items.nth(index)
        try:
            data_id = await item.get_attribute("data-id")
            name = (await item.locator("span.geek-name").inner_text()).strip()
            job_title = (await item.locator("span.source-job").inner_text()).strip()
            text = (await item.locator("span.push-text").inner_text()).strip()
            timestamp = (await item.locator("span.time").inner_text()).strip()
            unread = await item.locator("span.badge-count").count() > 0
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取列表项失败 #%s: %s", index, exc)
            continue
        if not unread_only or unread:
            messages.append(
                {
                    "chat_id": data_id,
                    "name": name,
                    "job_applied": job_title,
                    "last_message": text,
                    "timestamp": timestamp,
                }
            )
        if len(messages) >= limit:
            logger.debug("成功获取 %s 条候选人", len(messages))
            break
    else:
        logger.warning("获取的候选人数量少于需求量，实际获取数量: %d", len(messages))
    return messages


async def get_chat_history_action(page: Page, chat_id: str) -> List[Dict[str, Any]]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return []

    messages = page.locator("div.conversation-message >> div.message-item")
    count = await messages.count()
    last_timestamp: Optional[str] = None
    history: List[Dict[str, Any]] = []

    for index in range(count):
        message = messages.nth(index)
        await message.scroll_into_view_if_needed(timeout=500)
        msg_type = None
        message_str = None
        status = None

        timestamp_entry = message.locator("div.message-time")
        if await timestamp_entry.count() > 0:
            timestamp_raw = await timestamp_entry.inner_text(timeout=200)
            if len(timestamp_raw) <= 8 and not any(c in timestamp_raw for c in ("年", "月", "日", "-", "/")):
                today_str = last_timestamp.split(" ")[0] if last_timestamp else date.today().strftime("%Y-%m-%d")
                timestamp_raw = f"{today_str} {timestamp_raw}"
            try:
                import dateutil.parser as parser

                dt = parser.parse(timestamp_raw)
                timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                timestamp = timestamp_raw
            last_timestamp = timestamp
        else:
            timestamp = last_timestamp
        # accept system message with timestamp
        system_entry = message.locator("div.item-system[source='chat']")
        if await system_entry.count() > 0:
            message_str = await system_entry.inner_text(timeout=200)
            msg_type = "system"
            
        resume_entry = message.locator("div.item-resume")
        if await resume_entry.count() > 0:
            message_str = await resume_entry.inner_text(timeout=200)
            msg_type = "system"

        my_entry = message.locator("div.item-myself >> span")
        if await my_entry.count() > 0:
            message_str = await my_entry.inner_text(timeout=200)
            status_loc = message.locator("i.status")
            status = await status_loc.inner_text(timeout=200) if await status_loc.count() > 0 else None
            msg_type = "recruiter"

        friend_entry = message.locator("div.item-friend")
        if await friend_entry.count() > 0:
            message_str = await friend_entry.inner_text(timeout=200)
            msg_type = "candidate"

        if msg_type and message_str:
            history.append(
                {
                    "type": msg_type,
                    "timestamp": timestamp,
                    "message": message_str,
                    "status": status,
                }
            )
        else:
            try:
                raw = await message.inner_text(timeout=200)
            except Exception:
                raw = ""
            logger.warning("不支持的消息内容: %s", raw)
    return history

# ------------------------------------------------------------
# 在线简历
# ------------------------------------------------------------
async def view_online_resume_action(page: Page, chat_id: str, timeout: int = 20000) -> Dict[str, Any]:
    """View candidate's online resume. Returns dict with 'text', 'name', 'chat_id'. Raises ValueError on failure."""
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        raise ValueError("未找到指定对话项")

    candidate_name_locator = page.locator("span.name-box").first
    if await candidate_name_locator.count() > 0:
        candidate_name = (await candidate_name_locator.inner_text(timeout=1000)).strip()
    else:
        candidate_name = ""

    await _setup_wasm_route(page.context)
    await _install_parent_message_listener(page, logger)

    open_result = await _open_online_resume(page, chat_id, logger)
    if not open_result.get("success"):
        raise ValueError(_create_error_result(open_result, "无法打开在线简历").get("details", "无法打开在线简历"))
    
    context = await _get_resume_handle(page, timeout, logger)
    if not context.get("success"):
        raise ValueError(context.get("details", "未找到在线简历"))
    
    result = await _process_resume_entry(page, context, logger)
    if not isinstance(result, dict):
        debug = await collect_resume_debug_info(page)
        raise RuntimeError(f"未知错误: 结果类型异常, debug: {debug}")

    result.update({"name": candidate_name, "chat_id": chat_id})
    logger.debug("处理在线简历结果: %s", result.get('text', '')[:100])
    await close_overlay_dialogs(page)
    return result

#--------------------------------------------------
# 离线简历
#--------------------------------------------------

async def request_full_resume_action(page: Page, chat_id: str) -> bool:
    """Request resume from candidate. Returns True on success, raises ValueError on failure."""
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        raise ValueError("未找到指定对话项")
    
    # first check if candidate has already sent resume, click to accept
    accepted = await accept_full_resume_action(page, chat_id)
    if accepted:
        return True
    
    # 求简历
    btn = page.locator("span.operate-btn:has-text('求简历')").first
    await btn.wait_for(state="visible", timeout=3000)
    is_disabled = await btn.evaluate(
        "el => el.classList.contains('disabled') || el.disabled || el.getAttribute('disabled') !== null"
    )
    if is_disabled:
        return True  # Already requested (button disabled)
    
    await btn.click()
    await page.wait_for_timeout(1000)
    
    # 境外提醒
    confirm_continue = page.locator("div.btn-v2:has-text('继续交换')").first
    if await confirm_continue.count() > 0:
        await confirm_continue.click()
        await page.wait_for_timeout(1000)
    
    # Confirm dialog
    confirm = page.locator("span.boss-btn-primary:has-text('确定')").first
    if await confirm.count() > 0:
        await confirm.click()
    else:
        await page.keyboard.press("Enter")

    # Verify success
    await page.wait_for_timeout(2000)
    success_indicator = page.locator("div.item-system >> span:has-text('简历请求已发送')")
    if await success_indicator.count() == 0:
        logger.error("简历请求未发送或超时")
    
    return True
    
#TODO: fix this
async def accept_full_resume_action(page: Page, chat_id: str) -> bool:
    """Accept candidate's resume. Returns True on success, raises ValueError if accept button not found."""
    accept_button_selectors = ['div.notice-list >> a.btn:has-text("同意")', 'div.message-card-buttons >> span.card.btn:has-text("同意")']
    for selector in accept_button_selectors:
        resume_pending = page.locator(selector)
        if await resume_pending.count() > 0:
            await resume_pending.click(timeout=1000)
            await page.wait_for_timeout(1000) 
            return True
    return False


async def check_full_resume_available(page: Page, chat_id: str):
    """Check if full resume is available. Returns resume_button Locator if available, None otherwise."""
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        logger.warning("未找到指定对话项")
        return None

    # Accept resume if available
    await accept_full_resume_action(page, chat_id)

    resume_button = page.locator(RESUME_BUTTON_SELECTOR).first
    if await resume_button.count() == 0:
        logger.warning("未找到简历按钮")
        return None

    # Wait for button to become enabled (resume uploaded)
    for _ in range(10):
        classes = await resume_button.get_attribute("class") or ""
        if "disabled" not in classes:
            # Resume is available!
            return resume_button
        await asyncio.sleep(0.1)
    
    # Button still disabled after waiting
    logger.warning("暂无离线简历")
    return None


async def view_full_resume_action(page: Page, chat_id: str) -> Dict[str, Any]:
    """View candidate's full offline resume. Returns dict with 'text' and 'pages'. Raises ValueError on failure."""
    
    resume_button = await check_full_resume_available(page, chat_id)
    if not resume_button:
        # await request_full_resume_action(page, chat_id)
        raise ValueError("暂无离线简历，请先请求简历")

    await resume_button.click()
    
    iframe_handle = await page.wait_for_selector(RESUME_IFRAME_SELECTOR, timeout=8000)
    frame = await iframe_handle.content_frame()
    if not frame:
        await close_overlay_dialogs(page)
        raise RuntimeError("无法进入简历 iframe")
    
    await frame.wait_for_selector(PDF_VIEWER_SELECTOR, timeout=5000)
    content = await extract_pdf_viewer_text(frame)
    await close_overlay_dialogs(page)
    
    return {
        "text": content.get("text", ""),
        "pages": content.get("pages", []),
    }


async def ask_contact_action(page: Page, chat_id: str) -> bool:
    """Ask candidate for contact information in chat page. Returns True on success, raises ValueError on failure."""
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        raise ValueError("未找到指定对话项")
    
    clicked_phone, clicked_wechat = False, False
    ask_phone_button = page.locator("span.operate-btn:has-text('换电话')").first
    if await ask_phone_button.count() > 0:
        await ask_phone_button.click(timeout=1000)
        clicked_phone = True
    ask_wechat_button = page.locator("span.operate-btn:has-text('换微信')").first
    if await ask_wechat_button.count() > 0:
        await ask_wechat_button.click(timeout=1000)
        clicked_wechat = True

    if not clicked_phone and not clicked_wechat:
        raise ValueError("未找到换电话或换微信按钮")

    return True

async def notify_hr_action(page: Page, chat_id: str) -> bool:
    """Placeholder for triggering HR notification workflow.

    # TODO: 实现 HR 通知功能（电话/微信已获取的场景）
    """
    raise NotImplementedError("TODO: implement HR notification workflow")


__all__ = [name for name in globals() if name.endswith("_action") or name.startswith("get_chat")]
