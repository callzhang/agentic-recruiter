"""Common high-level chat actions used by automation flows."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import Locator
from .resume_capture import extract_pdf_viewer_text
from src.config import settings
from .ui_utils import close_overlay_dialogs
from .global_logger import get_logger
from .resume_capture import _process_resume_entry
# Get logger once at module level
logger = get_logger()
CHAT_MENU_SELECTOR = "dl.menu-chat"
CHAT_ITEM_SELECTORS = "div.geek-item"
CONVERSATION_SELECTOR = "div.conversation-message"
MESSAGE_INPUT_SELECTOR = "#boss-chat-editor-input"
RESUME_BUTTON_SELECTOR = "div.resume-btn-file, a.resume-btn-file"
RESUME_IFRAME_SELECTOR = "iframe.attachment-box"
PDF_VIEWER_SELECTOR = "div.pdfViewer"

CHAT_TAB_SELECTOR = "div.chat-label-item"

def _prepare_chat_page(page, tab: Optional[str] = None, wait_timeout: int = 5000) -> tuple[Optional[Locator], Optional[Dict[str, Any]]]:
    close_overlay_dialogs(page)
    # If current URL is not the chat page, click the chat menu to navigate
    if not settings.CHAT_URL in page.url:
        menu_chat = page.locator(CHAT_MENU_SELECTOR)
        menu_chat.click(timeout=100)
    
        # wait for chat box
        page.wait_for_selector('div.chat-box', timeout=wait_timeout)
        logger.info("已导航到聊天页面")

    if tab:
        CHAT_TAB_SELECTOR = f"div.chat-label-item[title*='{tab}']"
        chat_tab = page.locator(CHAT_TAB_SELECTOR)
        chat_tab.click(timeout=100)
        page.locator(CHAT_ITEM_SELECTORS).wait_for(state="visible", timeout=wait_timeout)
    return page

def _go_to_chat_dialog(page, chat_id: str, wait_timeout: int = 5000) -> tuple[Optional[Locator], Optional[Dict[str, Any]]]:
    # Ensure we are on the chat page; if not, click the chat menu
    # If current URL is not the chat page, click the chat menu to navigate
    """Ensure the chat is focused and the conversation panel is ready."""

    direct_selectors = [
        f"{CHAT_ITEM_SELECTORS}[data-id=\"{chat_id}\"]",
        # f"{CHAT_ITEM_SELECTORS}[id=_{chat_id}]",
        # f"div[role='listitem'][key=\"{chat_id}\"]",
    ]
    target = None
    for selector in direct_selectors:
        locator = page.locator(selector)
        if locator.count():
            target = locator.first
            break
    else:
        return None

    # move to chat dialog
    target.hover()
    if 'selected' not in target.get_attribute('class'):
        target.click()
        page.wait_for_selector(CONVERSATION_SELECTOR, timeout=wait_timeout)

    return target

def select_chat_job_action(page, job_title: str) -> Dict[str, Any]:
    """Select job for a specific conversation."""
    _prepare_chat_page(page)
    t0 = time.time()
    CURRENT_JOB_SELECTOR = "div.ui-dropmenu-label"
    JOB_LIST_SELECTOR = "div.ui-dropmenu-list >> li"
    current_selected = page.locator(CURRENT_JOB_SELECTOR)
    current_selected_job = current_selected.inner_text(timeout=300)
    if job_title in current_selected_job:
        return { 'success': True, 'details': '已选中职位', 'selected_job': current_selected_job }
    # 点击下拉菜单
    current_selected.click(timeout=200)
    all_jobs = page.locator(JOB_LIST_SELECTOR).all(timeout=200)
    all_job_titles = [job.inner_text(timeout=300) for job in all_jobs]
    idx = -1
    for i, job in enumerate(all_job_titles):
        if job_title in job:
            idx = i
            break
    if idx == -1:
        return { 'success': False, 'details': '未找到职位', 'selected_job': current_selected_job, 'available_jobs': all_job_titles }
    all_jobs[idx].click(timeout=200)
    while job_title not in current_selected_job and (time.time() - t0 < 3):
        current_selected_job = current_selected.inner_text(timeout=300)
        time.sleep(0.2)
    if job_title in current_selected_job:
        return { 'success': True, 'details': '已选中职位', 'selected_job': current_selected_job }
    else:
        return { 'success': False, 'details': '未找到职位', 'selected_job': current_selected_job, 'available_jobs': all_job_titles }

def get_chat_stats_action(page) -> Dict[str, Any]:
    """Get chat stats for the given chat_id"""
    _prepare_chat_page(page)
    import re
    NEW_MESSAGE_SELECTOR = "span.menu-chat-badge"
    NEW_GREET_SELECTOR = "div.chat-label-item[title*='新招呼']"
    new_message_count = page.locator(NEW_MESSAGE_SELECTOR).inner_text(timeout=300)
    new_message_count = int(new_message_count) if new_message_count else 0
    new_greet_count = page.locator(NEW_GREET_SELECTOR).inner_text(timeout=300)
    # Convert new_greet_count like "新招呼(41)" to integer 41
    new_greet_count = int(re.findall(r"\d+", new_greet_count)[0])
    return { 'success': True, 'new_message_count': new_message_count, 'new_greet_count': new_greet_count }

def request_resume_action(page, chat_id: str) -> Dict[str, Any]:
    """Send a resume request in the open chat panel for the given chat_id"""
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return { 'success': False, 'details': '未找到指定对话项' }

    # Find the resume request button
    btn = page.locator("span.operate-btn:has-text('求简历')").first
    btn.wait_for(state="visible", timeout=3000)

    # Check if button is disabled (already sent)
    is_disabled = btn.evaluate("el => el.classList.contains('disabled') || el.disabled || el.getAttribute('disabled') !== null")
    if is_disabled:
        return { 'success': True, 'already_sent': True, 'details': '简历请求已发送（按钮已禁用）' }

    # Click the resume request button
    btn.click()
    # Confirm
    btn0 = page.locator('div:has-text("继续交换")')
    if btn0.count():
        btn0.click()
    confirm = page.locator("span.boss-btn-primary:has-text('确定')").first
    confirm.click()

    # Verify
    page.wait_for_function(
        "() => (document.body && document.body.innerText && document.body.innerText.includes('简历请求已发送'))",
        timeout=5000
    )
    return { 'success': True, 'already_sent': False, 'details': '简历请求已发送' }

def send_message_action(page, chat_id: str, message: str) -> Dict[str, Any]:
    """Send a text message in the open chat panel for the given chat_id"""
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return { 'success': False, 'details': '未找到指定对话项' }

    # Find the message input field
    input_field = page.locator(MESSAGE_INPUT_SELECTOR).first
    if not input_field.count():
        return { 'success': False, 'details': '未找到消息输入框' }
    
    input_field.wait_for(state="visible", timeout=3000)

    # Clear existing content and type the message
    input_field.click()
    input_field.fill("")  # Clear existing content
    input_field.type(message)

    # Find and click the send button
    send_button = page.locator("div.submit:has-text('发送')").first
    if not send_button.count():
        return { 'success': False, 'details': '未找到发送按钮' }
    
    send_button.wait_for(state="visible", timeout=3000)
    send_button.click()

    # Wait a moment for the message to be sent
    page.wait_for_timeout(1000)

    # Verify the message was sent by checking if input field is cleared
    remaining = input_field.evaluate("el => (el.value || el.innerText || '').trim()") or input_field.inner_text() or ''
    if not remaining:
        return { 'success': True, 'details': '消息发送成功' }
    return { 'success': False, 'details': '消息可能未发送成功，输入框仍有内容' }

def check_full_resume_available(page, chat_id: str, internal: bool = False) -> Optional[Dict[str, Any]]:
    """检查简历按钮是否启用"""
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return { 'success': False, 'details': '未找到指定对话项' }

    # Find and click the resume file button
    resume_button = page.locator(RESUME_BUTTON_SELECTOR).first
    if not resume_button.count():
        return { 'success': False, 'details': '未找到简历按钮' }
    # Check if the resume button is disabled
    t0 = time.time()
    while is_disabled := "disabled" in resume_button.get_attribute("class"):
        time.sleep(0.1)
        if time.time() - t0 > 1:
            break
    if is_disabled:
        if internal:
            return None
        else:
            return { 'success': False, 'details': '暂无离线简历，请先请求简历' }
    else:
        if internal:
            return resume_button
        else:
            return { 'success': True, 'details': '离线简历已启用' }

def view_full_resume_action(page, chat_id: str) -> Dict[str, Any]:
    """点击查看候选人的附件简历
    view_full_resume_action(page, chat_id)
    ├── _go_to_chat_dialog(page, chat_id)
    │   ├── close_overlay_dialogs(page) [ui_utils.py:66]
    │   └── page.locator(CHAT_MENU_SELECTOR)
    ├── page.locator(RESUME_BUTTON_SELECTOR)
    ├── page.wait_for_selector(RESUME_IFRAME_SELECTOR)
    └── close_overlay_dialogs(page) [ui_utils.py:66]
    """
    resume_button = check_full_resume_available(page, chat_id, internal=True)
    if not resume_button:
        return { 'success': False, 'details': '暂无离线简历，请先请求简历' }
    resume_button.click()

    # Wait for resume viewer to appear
    try:
        # Wait for iframe to appear first
        iframe_handle = page.wait_for_selector(RESUME_IFRAME_SELECTOR, timeout=8000)
        frame = iframe_handle.content_frame()
        frame.wait_for_selector(PDF_VIEWER_SELECTOR, timeout=5000)

        content = extract_pdf_viewer_text(frame)
    except Exception as e:
        close_overlay_dialogs(page)
        return { 'success': False, 'details': '简历查看器未出现', 'error': str(e) }
    finally:
        close_overlay_dialogs(page)

    return {
        'success': True,
        'details': '简历查看器已打开',
        'content': content.get('text', ''),
        'pages': content.get('pages', []),
    }

def discard_candidate_action(page, chat_id: str) -> Dict[str, Any]:
    """丢弃候选人 - 点击"不合适"按钮"""
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return { 'success': False, 'details': '未找到指定对话项' }

    # 查找"不合适"按钮
    not_fit_button = page.locator("div.not-fit-wrap").first
    # not_fit_button = page.get_by_text('不合适').first
    
    not_fit_button.wait_for(state="visible", timeout=3000)
    not_fit_button.hover()
    time.sleep(2)
    not_fit_button.click()

    # 等待确认对话框
    dialog = _go_to_chat_dialog(page, chat_id)
    if dialog is None:
        return { 'success': True, 'details': f'确认已丢弃' }
    else:
        return { 'success': False, 'details': f'确认丢弃失败: 未删除对话' }

def get_chat_list_action(page, limit: int = 10):
    """获取消息列表"""
    _prepare_chat_page(page)
    # Simple text extraction for messages
    items_selector = "div.geek-item"
    messages = []
    items = page.locator(items_selector).all()
    for item in items[:limit]:
        # item.scroll_into_view_if_needed(timeout=1000)
        messages.append({
            'id': item.get_attribute('data-id'),
            'name': item.locator('span.geek-name').inner_text(),
            'job_title': item.locator('span.source-job').inner_text(),
            'text': item.locator('span.push-text').inner_text(),
            'timestamp': item.locator('span.time').inner_text(),
        })
    
    # Use cache if no messages found
    logger.info(f"成功获取 {len(messages)} 条消息")
    return messages

def get_chat_history_action(page, chat_id: str) -> List[Dict[str, Any]]:
    """读取右侧聊天历史，返回结构化消息列表"""
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return []
    
    # Simple text extraction for chat history
    ''' multiple div.message-time item
    1. 
    - div.message-time: timestamp
    - div.item-resume: background info
    2. div.item-myself > div.text: my message
    3. div.item-system: system message
    4. div.item-friend > div.text: candidate message
    '''
    import dateutil.parser as parser
    from datetime import date

    messages = page.locator("div.conversation-message >> div.message-item").all()
    last_timestamp:str = None #%Y-%m-%d %H:%M:%S
    history = []
    for message in messages:
        type, message_str, status = None, None, None
        # timestamp
        timestamp_entry = message.locator("div.message-time")
        if timestamp_entry.count():
            timestamp = timestamp_entry.inner_text(timeout=100)
            # Try to detect if it's only time (e.g., "14:23" or "14:23:01")
            if len(timestamp) <= 8 and not any(c in timestamp for c in ('年', '月', '日', '-', '/')):
                if last_timestamp:
                    today_str = last_timestamp.split(' ')[0]
                else:
                    today_str = date.today().strftime("%Y-%m-%d")
                timestamp = f"{today_str} {timestamp}"
            dt = parser.parse(timestamp)
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            last_timestamp = timestamp
        else:
            timestamp = last_timestamp
        
        # resume item / system message
        message_str_entry = message.locator("div.item-resume, div.item-system")
        if message_str_entry.count():
            message_str = message.inner_text(timeout=100)
        else:
            message_str = ''
        type = 'system'

        pass

        message_str_entry = message.locator("div.item-myself >> span")
        if message_str_entry.count():
            message_str = message_str_entry.inner_text(timeout=100)
            status = message.locator('i.status').inner_text(timeout=100)
        else:
            message_str, status = '', None
        type = 'recruiter'

        pass

        message_str_entry = message.locator("div.item-friend")
        if message_str_entry.count():
            message_str = message_str_entry.inner_text(timeout=100)
        else:
            message_str = ''
        type = 'candidate'

        pass
        if message_str:
            history.append({
                'type': type,
                'timestamp': timestamp,
                'message': message_str,
                'status': status,
            })

    logger.info(f"chat_id: {chat_id}, messages: {history}")
    return history

def accept_resume_action(page, chat_id: str) -> Dict[str, Any]:
    """Accept a candidate by clicking the accept button.
    
    Args:
        page: Playwright page object
        chat_id: ID of the chat/conversation
        
    Returns:
        Dict with success status and details
    """
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return { 'success': False, 'details': '未找到指定对话项' }
    
    # Look for accept button
    accept_selectors = [
        "button:has-text('接受')",
        "a:has-text('接受')",
        "xpath=//button[contains(., '接受')]",
        "xpath=//a[contains(., '接受')]"
    ]
    
    for selector in accept_selectors:

            if page.locator(selector).first.is_visible(timeout=2000):
                page.locator(selector).first.click(timeout=2000)
                logger.info(f"Successfully clicked accept button")
                return {'success': True, 'details': '候选人已接受'}

            continue
    
    logger.warning("No accept button found")
    return {'success': False, 'details': '未找到接受按钮'}
        
def view_online_resume_action(page, chat_id: str) -> Dict[str, Any]:
    """点击会话 -> 点击"在线简历" -> 使用多级回退链条输出文本
    view_online_resume_action(page, chat_id)
    ├── _go_to_chat_dialog(page, chat_id)
    │   ├── close_overlay_dialogs(page) [ui_utils.py:66]
    │   └── page.locator(CHAT_MENU_SELECTOR)
    ├── _setup_wasm_route()
    ├── _install_parent_message_listener()
    ├── _open_online_resume()
    └── _get_resume_handle()
    ├── _process_resume_entry(page, context_info, logger) [resume_capture.py:1254]
    │   ├── (inline)
    │       ├── _capture_inline_resume()
    │   └── (iframe)
    │       ├── _collect_parent_messages()
    │       ├── _try_wasm_exports()
    │       ├── _try_canvas_text_hooks()
    │       └── _try_clipboard_hooks()
    └── close_overlay_dialogs(page) [ui_utils.py:66]
"""
    _prepare_chat_page(page)
    dialog = _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return { 'success': False, 'details': '未找到指定对话项' }

    # get the candidate name
    candidate_name = page.locator("span.name-box").inner_text(timeout=200)

    # Prepare resume context by opening resume and detecting mode.
    from .resume_capture import _setup_wasm_route, _install_parent_message_listener, _open_online_resume, _get_resume_handle, _create_error_result
    _setup_wasm_route(page.context)
    _install_parent_message_listener(page, logger)

    # open the online resume
    open_result = _open_online_resume(page, chat_id, logger)
    if not open_result.get('success'):
        return _create_error_result(open_result, '无法打开在线简历')

    # get the resume handle
    context = _get_resume_handle(page, 8000, logger)
    context.update(open_result)

    # process resume entry
    result = _process_resume_entry(page, context, logger)
    logger.info(f"处理简历结果: {result}")
    close_overlay_dialogs(page)
    if not isinstance(result, dict):
        return { 'success': False, 'details': '未知错误: 结果类型异常' }

    result.update({ 'name': candidate_name, 'chat_id': chat_id })
    return result
