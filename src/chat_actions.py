"""Common high-level chat actions used by automation flows (async version)."""

import re
from datetime import date
from typing import Any, Dict, List, Optional
import time
from playwright.async_api import Locator, Page
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed
import random
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
RESUME_BUTTON_SELECTOR = "div.resume-file-content, a.resume-btn-file, div.resume-btn-file"
RESUME_IFRAME_SELECTOR = "iframe.attachment-box"
PDF_VIEWER_SELECTOR = "div.pdfViewer"


@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def _prepare_chat_page(page: Page, tab = None, status = None, job_title = None, timeout_s: int = 5) -> Page:
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
        timeout_s (int, optional): Timeout in seconds to wait for visibility. Defaults to 5.

    Returns:
        Page: The configured Page object, ready for further actions.
        
    Raises:
        ValueError: If filters result in no candidates being displayed.
    """
    await close_overlay_dialogs(page)
    await ensure_on_chat_page(page, logger)

    if tab:
        tab_selector = f"div.chat-label-item[title*='{tab}']"
        chat_tab = page.locator(tab_selector).first
        if await chat_tab.count() > 0 and 'selected' not in await chat_tab.get_attribute("class"):
            await chat_tab.click()
            # Wait for page to update, then check if candidates exist
            start_time = time.time()
            while await page.locator(CHAT_ITEM_SELECTORS).first.count() == 0:
                await page.wait_for_timeout(500)
                if await page.locator('p.no-setting-text:has-text("暂无牛人")').count() > 0:
                    break
                if time.time() - start_time > timeout_s:
                    raise RuntimeError(f"未找到标签为 '{tab}' 的对话")
    
    if status:
        status_selector = f"div.chat-message-filter-left > span:has-text('{status}')"
        chat_status = page.locator(status_selector).first
        if await chat_status.count() > 0 and 'active' not in await chat_status.get_attribute("class"):
            await chat_status.click()
            # Wait for page to update, then check if candidates exist
            start_time = time.time()
            while await page.locator(CHAT_ITEM_SELECTORS).first.count() == 0:
                await page.wait_for_timeout(500)
                if await page.locator('p.no-setting-text:has-text("暂无牛人")').count() > 0:
                    break
                if time.time() - start_time > timeout_s:
                    raise RuntimeError(f"未找到状态为 '{status}' 的聊天对话")
    
    if job_title:
        current_job_selector = f"div.ui-dropmenu-label > span.chat-select-job"
        job_selector = f'div.ui-dropmenu-list >> li:has-text("{job_title}")'
        current_job_loc = page.locator(current_job_selector).first
        if await current_job_loc.count() > 0:
            current_job = await current_job_loc.inner_text()
            if job_title not in current_job:
                await current_job_loc.click(timeout=1000)
                job_loc = page.locator(job_selector).first
                if await job_loc.count() > 0:
                    await job_loc.click(timeout=1000)
                    # Wait for page to update, then check if candidates exist
                    start_time = time.time()
                    while await page.locator(CHAT_ITEM_SELECTORS).first.count() == 0:
                        await page.wait_for_timeout(500)
                        if await page.locator('p.no-setting-text:has-text("暂无牛人")').count() > 0:
                            break
                        if time.time() - start_time > timeout_s:
                            raise RuntimeError(f"未找到职位为 '{job_title}' 的岗位")
                else:
                    await page.locator(CHAT_MENU_SELECTOR).click(timeout=1000)
                    raise RuntimeError(f"未找到职位为 '{job_title}' 的岗位")


    return page

async def _find_chat_dialog(page: Page, chat_id: str, wait_timeout: int = 5) -> Optional[Locator]:
    direct_selectors = f"{CHAT_ITEM_SELECTORS}[data-id=\"{chat_id}\"], [role='listitem'][data-id=\"{chat_id}\"]"
    target = page.locator(direct_selectors)
    if await target.count() == 0:
        return None
    return target


async def _go_to_chat_dialog(page: Page, chat_id: str, wait_timeout: int = 5) -> Optional[Locator]:
    '''Go to the chat dialog with the given chat_id.
    Args:
        page: Page - The Playwright Page instance representing the chat page.
        chat_id: str - The chat_id of the chat dialog to go to.
        wait_timeout: int - The timeout in seconds to wait for the chat dialog to load.
    Returns:
        Optional[Locator]: The locator to the chat dialog, or None if not found.
    '''
    target = await _find_chat_dialog(page, chat_id, wait_timeout)
    if not target:
        raise RuntimeError(f"未找到指定对话项 (chat_id: {chat_id})")
    # check if the target is already selected
    await target.scroll_into_view_if_needed(timeout=1000)
    classes = await target.get_attribute("class") or ""
    # prepare for the click - get old_text before clicking
    if "selected" not in classes:
        old_conversation_selector = page.locator(CONVERSATION_SELECTOR)
        old_text = await old_conversation_selector.inner_text(timeout=1000) if await old_conversation_selector.count() > 0 else ""
        # click the target
        await target.click(timeout=1000)
        # wait for the conversation panel to refresh
        t0 = time.time()
        while time.time() - t0 < wait_timeout:
            new_text = await page.locator(CONVERSATION_SELECTOR).inner_text(timeout=1000)
            if new_text and new_text != old_text:
                break
            await page.wait_for_timeout(200)
        else:
            logger.warning("等待对话面板刷新失败")
    return target



@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def get_chat_stats_action(page: Page) -> Dict[str, Any]:
    """Get chat statistics including new message and greet counts."""
    # await _prepare_chat_page(page)
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



@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def send_message_action(page: Page, chat_id: str, message: str, timeout: int = 3000) -> bool:
    """Send message to candidate. Returns True on success, raises ValueError on failure."""
    if not message:
        return False
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)

    input_field = page.locator(MESSAGE_INPUT_SELECTOR).first
    if await input_field.count() == 0:
        # raise RuntimeError("未找到消息输入框")
        logger.error("未找到消息输入框")
        return False

    await input_field.wait_for(state="visible", timeout=timeout)
    await input_field.click()
    await input_field.fill("")
    await input_field.type(message)

    send_button = page.locator("div.submit:has-text('发送')").first
    if await send_button.count() == 0:
        await page.keyboard.press("Enter")
    else:
        await send_button.wait_for(state="visible", timeout=timeout)
        await send_button.click()

    await page.wait_for_timeout(1000)
    remaining = await input_field.evaluate("el => (el.value || el.innerText || '').trim()")
    if remaining:
        logger.warning("消息可能未发送成功，输入框仍有内容")
        return False
    
    return True


# @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def discard_candidate_action(page: Page, chat_id: str, timeout: int = 3000) -> bool:
    """Skip (PASS) candidate. Returns True on success, raises ValueError on failure."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)

    not_fit_button = page.locator("div.not-fit-wrap").first
    await not_fit_button.wait_for(state="visible", timeout=timeout)
    
    # wait for dialog to be deleted
    max_attempts = 10
    for _ in range(max_attempts):
        await not_fit_button.hover(timeout=1000)
        await page.wait_for_timeout(500)
        await not_fit_button.click()
        await page.wait_for_timeout(1000)
        if not await _find_chat_dialog(page, chat_id):
            return True  # Successfully discarded
    
    # If we get here, the dialog wasn't deleted
    raise RuntimeError("PASS失败: 未删除对话")
    

@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def list_conversations_action(
    page: Page, 
    limit: int = 999, 
    tab: str = '新招呼', 
    status: str = '未读', 
    job_applied: str = '全部', 
    unread_only=True,
    random_order=False
) -> List[Dict[str, Any]]:
    '''Get candidate list from chat page
    Args:
        page: Page - The Playwright Page instance representing the chat page.
        limit: int - The maximum number of chat items to return.
        tab: str - The chat tab to select (e.g., "新招呼", "沟通中").
        status: str - The chat status filter to apply.
        job_applied: str - The job applied to filter candidates.
        unread_only: bool - Whether to only return unread candidates.
    Returns:
        List[Dict[str, Any]]: A list of candidate items.
    '''
    await _prepare_chat_page(page, tab, status, job_applied)
    # Scroll the candidate list container to the end
    candidate_list = page.locator('div.b-scroll-stable')
    await candidate_list.evaluate('element => element.scrollTop = element.scrollHeight')
    items = page.locator(CHAT_ITEM_SELECTORS)
    count = await items.count()
    messages: List[Dict[str, Any]] = []
    index_list = list(range(count))
    if random_order:
        random.shuffle(index_list)
    for i in index_list:
        try:
            item = items.nth(i)
            data_id = await item.get_attribute("data-id", timeout=100)
            name = (await item.locator("span.geek-name").inner_text(timeout=100)).strip()
            # job_title = (await item.locator("span.source-job").inner_text()).strip() # using job_applied instead, meaning we stick to our own job_applied field instead of the web job title
            text = (await item.locator("span.push-text").inner_text(timeout=100)).strip()
            timestamp = (await item.locator("span.time").inner_text(timeout=100)).strip()
            unread = await item.locator("span.badge-count").count() > 0
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取列表项失败 #%s: %s", i, exc)
            continue
        if not unread_only or unread:
            messages.append(
                {
                    "chat_id": data_id,
                    "name": name,
                    "job_applied": job_applied,
                    "last_message": text,
                    "timestamp": timestamp,
                    "viewed": not unread,
                }
            )
        if len(messages) >= limit:
            logger.debug("成功获取 %s 条候选人", len(messages))
            break
    else:
        logger.warning("获取的候选人数量少于需求量，实际获取数量: %d", len(messages))
    return messages


@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def get_chat_history_action(page: Page, chat_id: str, timeout: int = 200) -> List[Dict[str, Any]]:
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)

    messages = page.locator("div.conversation-message >> div.message-item")
    count = await messages.count()
    last_timestamp: Optional[str] = None
    history: List[Dict[str, Any]] = []

    for index in range(count):
        message = messages.nth(index)
        # await message.scroll_into_view_if_needed(timeout=500)
        msg_type = None
        message_str = None
        status = None

        timestamp_entry = message.locator("div.message-time")
        if await timestamp_entry.count() > 0:
            timestamp_raw = await timestamp_entry.inner_text(timeout=timeout)
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
            message_str = await system_entry.inner_text(timeout=timeout)
            msg_type = "developer"
            
        resume_entry = message.locator("div.item-resume")
        if await resume_entry.count() > 0:
            message_str = await resume_entry.inner_text(timeout=timeout)
            msg_type = "developer"

        my_entry = message.locator("div.item-myself >> span")
        if await my_entry.count() > 0:
            message_str = await my_entry.inner_text(timeout=timeout)
            status_loc = message.locator("i.status")
            status = await status_loc.inner_text(timeout=timeout) if await status_loc.count() > 0 else None
            msg_type = "assistant"

        friend_entry = message.locator("div.item-friend")
        if await friend_entry.count() > 0:
            message_str = await friend_entry.inner_text(timeout=timeout)
            if message_str == '' and await friend_entry.locator('img').count() > 0:
                message_str = '[图片]无法加载'
            if await friend_entry.locator('div.message-card-wrap').count() > 0:
                msg_type = "developer"
            else:
                msg_type = "user"

        if msg_type and message_str:
            history.append(
                {
                    "role": msg_type,
                    "timestamp": timestamp,
                    "content": message_str,
                    "status": status,
                }
            )
        else:
            try:
                raw = await message.inner_text(timeout=timeout)
            except Exception:
                raw = ""
            logger.warning("不支持的消息内容: %s", raw)
    return history

# ------------------------------------------------------------
# 在线简历
# ------------------------------------------------------------
# @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def view_online_resume_action(page: Page, chat_id: str, timeout: int = 20000) -> Dict[str, Any]:
    """View candidate's online resume. Returns dict with 'text', 'name', 'chat_id'. Raises ValueError on failure."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)

    candidate_name_locator = page.locator("span.name-box").first
    if await candidate_name_locator.count() > 0:
        candidate_name = (await candidate_name_locator.inner_text(timeout=1000)).strip()
    else:
        candidate_name = ""

    await _setup_wasm_route(page.context)
    await _install_parent_message_listener(page, logger)

    open_result = await _open_online_resume(page, chat_id, logger)
    if not open_result.get("success"):
        raise RuntimeError(_create_error_result(open_result, "无法打开在线简历").get("details", "无法打开在线简历"))
    
    context = await _get_resume_handle(page, timeout, logger)
    if not context.get("success"):
        raise RuntimeError(context.get("details", "未找到在线简历"))
    
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

# @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def request_full_resume_action(page: Page, chat_id: str, timeout: int = 3000) -> bool:
    """Request resume from candidate. Returns True on success, False on failure (e.g., dialog not found)."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)
    
    # first check if candidate has already sent resume, click to accept
    accepted = await accept_full_resume_action(page, chat_id)
    if accepted:
        return True
    
    # 求简历
    btn = page.locator("span.operate-btn:has-text('求简历')").first
    await btn.wait_for(state="visible", timeout=timeout)
    
    t0 = time.time()
    while "disabled" not in await btn.get_attribute("class"):
        try:
            await btn.click(timeout=timeout)
            # 境外提醒
            confirm_continue = page.locator("div.btn-sure-v2:has-text('继续交换')")
            if await confirm_continue.count() > 0:
                await confirm_continue.click(timeout=timeout)
                logger.info("境外提醒已确认")
            # Confirm dialog
            confirm = page.locator("span.boss-btn-primary:has-text('确定')")
            if await confirm.count() > 0:
                await confirm.click(timeout=timeout)
                logger.info("简历请求已发送")
        except Exception as e:
            pass
        if time.time() - t0 > 5:
            return False
    else:
        await page.wait_for_timeout(500)
        return True
    

# @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def accept_full_resume_action(page: Page, chat_id: str, timeout_ms: int = 1000) -> bool:
    """Accept candidate's resume. Returns True on success, raises ValueError if accept button not found."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)
    accept_button_selector = 'div.notice-list >> a.btn:has-text("同意"), div.message-card-buttons >> span.card.btn:has-text("同意")'
    accept_button = page.locator(accept_button_selector)
    if await accept_button.count() == 0:
        return False
    confirm_continue = page.locator("div.btn-sure-v2:has-text('继续交换')")
    tried = 0
    while 'disabled' not in await accept_button.get_attribute("class", timeout=timeout_ms):
        try:
            await accept_button.click(timeout=timeout_ms)
            await page.wait_for_timeout(500) 
            # 境外提醒
            if await confirm_continue.count() > 0:
                await confirm_continue.click(timeout=timeout_ms)
                continue
        except Exception as e:
            pass
        tried += 1
        if tried > 10:
            break
    else:
        return True
    return False


# @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def check_full_resume_available(page: Page, chat_id: str, timeout_ms: int = 2000):
    """Check if full resume is available. Returns resume_button Locator if available, None otherwise."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)

    # Accept resume if available
    accepted = await accept_full_resume_action(page, chat_id)
    if accepted:
        return True
    # 右上角的简历查看按钮
    resume_button = page.locator(RESUME_BUTTON_SELECTOR).first
    if await resume_button.count() == 0:
        logger.warning("未找到简历按钮")
        return False

    # Wait for button to become enabled (resume uploaded)
    for _ in range(10):
        if "disabled" not in await resume_button.get_attribute("class"): # 按钮不是disabled状态，则表示简历已上传
            return True
        await page.wait_for_timeout(200)
    
    return False


# @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def view_full_resume_action(page: Page, chat_id: str, request: bool = True, timeout_ms: int = 20000) -> Dict[str, Any]:
    """View candidate's full offline resume. Returns dict with 'text' and 'pages'. Raises ValueError on failure."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)
    available = await check_full_resume_available(page, chat_id)
    if not available and request:
        requested = await request_full_resume_action(page, chat_id)
        return {
            "text": None,
            "requested": requested,
        }

    resume_button = page.locator(RESUME_BUTTON_SELECTOR).first
    await resume_button.click()
    
    iframe_handle = await page.wait_for_selector(RESUME_IFRAME_SELECTOR, timeout=timeout_ms)
    frame = await iframe_handle.content_frame()
    if not frame:
        await close_overlay_dialogs(page)
        # raise RuntimeError("无法进入简历 iframe")
        return {
            "text": None,
        }
    
    await frame.wait_for_selector(PDF_VIEWER_SELECTOR, timeout=timeout_ms)
    content = await extract_pdf_viewer_text(frame)
    await close_overlay_dialogs(page)
    
    return {
        "text": content.get("text", ""),
        "pages": content.get("pages", []),
    }


@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def request_contact_action(page: Page, chat_id: str, timeout_ms: int = 2000) -> bool:
    """Ask candidate for contact information in chat page. Returns True on success, raises ValueError on failure."""
    await _prepare_chat_page(page)
    await _go_to_chat_dialog(page, chat_id)
    phone_number = None
    wechat_number = None
    clicked_phone, clicked_wechat = False, False
    ask_phone_button = page.locator("span.operate-btn:has-text('换电话')").first
    if await ask_phone_button.count() > 0:
        t0 = time.time()
        while 'disabled' not in await ask_phone_button.get_attribute("class"):
            await ask_phone_button.click(timeout=timeout_ms)
            try:
                await ask_phone_button.locator("xpath=parent::div").locator("span.boss-btn-primary:has-text('确定')").click(timeout=timeout_ms)
            except:
                pass
            await page.wait_for_timeout(500)
            if time.time() - t0 > 5:
                break
        else:
            clicked_phone = True
    view_phone_number = page.locator("span.operate-btn:has-text('查看电话')").first
    if await view_phone_number.count() > 0:
        await view_phone_number.click(timeout=timeout_ms)
        phone_number = await view_phone_number.locator("xpath=parent::div").locator("div.exchange-tooltip > span.exchanged > span").inner_text(timeout=timeout_ms)


    ask_wechat_button = page.locator("span.operate-btn:has-text('换微信')").first
    if await ask_wechat_button.count() > 0:
        t0 = time.time()
        while 'disabled' not in await ask_wechat_button.get_attribute("class"):
            await ask_wechat_button.click(timeout=timeout_ms)
            try:
                await ask_wechat_button.locator("xpath=parent::div").locator("span.boss-btn-primary:has-text('确定')").click(timeout=timeout_ms)
            except:
                pass
            await page.wait_for_timeout(500)
            if time.time() - t0 > 5:
                break
        else:
            clicked_wechat = True
    # check wechat number
    view_wechat_number = page.locator("span.operate-btn:has-text('查看微信')").first
    if await view_wechat_number.count() > 0:
        await view_wechat_number.click(timeout=timeout_ms)
        wechat_number = await view_wechat_number.locator("xpath=parent::div").locator("div.exchange-tooltip > span.exchanged > span").inner_text(timeout=2000)

    return {
        "phone_number": phone_number,
        "wechat_number": wechat_number,
        "clicked_phone": clicked_phone,
        "clicked_wechat": clicked_wechat,
    }


__all__ = [name for name in globals() if name.endswith("_action") or name.startswith("get_chat")]
