"""Recommendation page actions for Boss Zhipin automation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import time
from src.config import settings
from playwright.sync_api import Locator

from .resume_capture import (
    collect_resume_debug_info,
    CANVAS_TEXT_HOOK_SCRIPT,
)
from .ui_utils import close_overlay_dialogs, IFRAME_OVERLAY_SELECTOR, RESUME_OVERLAY_SELECTOR
from .global_logger import get_logger

# Get logger once at module level
logger = get_logger()

CANDIDATE_CARD_SELECTOR = "div.candidate-card-wrap"

def _prepare_recommendation_page(page, *, wait_timeout: int = 8000) -> tuple[Optional[Locator], Optional[Dict[str, Any]]]:
    """Ensure the recommendation panel is opened and ready."""
    close_overlay_dialogs(page)
    # Click the recommendation menu
    if not settings.RECOMMEND_URL in page.url:
        menu_chat = page.locator('dl.menu-recommend')
        menu_chat.click(timeout=1000)
    
        # wait for chat box
        # page.wait_for_selector('div.chat-box', timeout=wait_timeout)
        # logger.info("已导航到聊天页面")

    # Wait for the iframe to appear and get its frame
    iframe = page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=wait_timeout)
    
    if frame := iframe.content_frame():
        frame.wait_for_selector(CANDIDATE_CARD_SELECTOR, timeout=wait_timeout)
        logger.info("已导航到推荐页面")
    else:
        page.wait_for_selector(CANDIDATE_CARD_SELECTOR, timeout=wait_timeout)
    return frame

def select_recommend_job_action(frame, job_title: str) -> Dict[str, Any]:
    """选择当前职位从下拉菜单中。
    
    select_current_job_action(page, job_title)
    ├── 1. LOCATE JOB DROPDOWN PHASE
    │   ├── frame.locator('div.ui-dropmenu >> ul.job-list > li')
    │   └── 遍历所有li元素查找包含job_title的文本
    │
    ├── 2. SELECTION PHASE
    │   ├── 找到匹配的li元素
    │   └── li.click() 点击选择
    │
    └── 3. VERIFICATION PHASE
        ├── 等待页面变化
        └── 检查 div.ui-dropmenu -> div.ui-dropmenu-label 的文本
    """
    # 获取所有职位选项
    t0 = time.time()
    JOB_POPOVER_SELECTOR = 'div.ui-dropmenu'
    JOB_SELECTOR = 'div.ui-dropmenu >> ul.job-list > li'
    job_options = frame.locator(JOB_SELECTOR).all()
    
    if not job_options:
        return {'success': False, 'details': '未找到职位下拉菜单'}
    
    # 查找包含指定职位标题的选项
    selected_option, idx = None, -1
    dropdown_label = frame.locator(JOB_POPOVER_SELECTOR)
    current_selected_job = dropdown_label.inner_text(timeout=300)
    available_jobs = [option.inner_text(timeout=100).strip() for option in job_options]
    current_job_matched = job_title in current_selected_job
    if current_job_matched:
        # 已经选中，无需点击
        return {
            'success': True,
            'details': f'已选中职位: {job_title}',
            'selected_job': job_title,
            'available_jobs': available_jobs
        }
    for i, job in enumerate(available_jobs):
        if job_title in job:
            selected_option = job_options[i]
            idx = i
            break
    if idx == -1:
        return {
            'success': False, 
            'details': f'未找到包含"{job_title}"的职位',
            'selected_job': job_title,
            'available_jobs': available_jobs,
            'expected_job': job_title,
        }
    else:
        frame.locator(JOB_POPOVER_SELECTOR).click(timeout=1000)
        selected_option.click(timeout=1000)
        logger.info(f"已点击职位: {job_title}")
        
        # 等待页面变化并验证选择
        # 等待下拉菜单标签更新
        frame.wait_for_timeout(2000)  # 给页面一点时间更新
    
    # 检查下拉菜单标签是否已更新
    while job_title not in current_selected_job and (time.time() - t0 < 3):
        current_selected_job = dropdown_label.inner_text(timeout=300)
        time.sleep(0.2)

    if job_title in current_selected_job:
        return {
            'success': True,
            'details': f'成功选择职位: {available_jobs[idx]}',
            'selected_job': current_selected_job,
            'available_jobs': available_jobs,
        }
    else:
        return {
            'success': False,
            'details': f'职位选择可能失败，当前显示: {available_jobs[idx]}',
            'selected_job': current_selected_job,
            'available_jobs': available_jobs,
            'expected_job': job_title,
        }

def list_recommended_candidates_action(page, *, limit: int = 20) -> Dict[str, Any]:
    """Click the recommended panel and return structured card information."""
    frame = _prepare_recommendation_page(page)

    # Use the frame to locate card items
    candidates = []
    while len(candidates) < limit:
        card_locators: List[Locator] = frame.locator(CANDIDATE_CARD_SELECTOR).all()
        if len(card_locators) < limit:
            card_locators[-1].hover(timeout=1000)
            time.sleep(1)
            continue
        for card in card_locators[:limit]:
            card.scroll_into_view_if_needed(timeout=1000)
            viewd = 'viewed' in card.get_attribute('class')
            greeted = card.locator('button:has-text("继续沟通")').count() > 0
            text = card.inner_text().strip()
            candidates.append({
                'viewed': viewd,
                'greeted': greeted,
                'text': text,
            })
    success = bool(candidates)
    details = f"成功获取 {len(candidates)} 个推荐候选人" if success else '未找到推荐候选人'
    return { 'success': success, 'details': details, 'candidates': candidates }

def view_recommend_candidate_resume_action(page, index: int) -> Dict[str, Any]:
    """点击推荐候选人卡片并抓取在线简历内容。
    view_recommend_candidate_resume_action(page, index)
    ├── 1. NAVIGATION PHASE
    │   └── _prepare_recommendation_page(page)
    │       ├── close_overlay_dialogs(page) [ui_utils.py]
    │       ├── page.locator("dl.menu-recommend").click() [if not on recommend page]
    │       └── page.wait_for_selector(IFRAME_OVERLAY_SELECTOR) [wait for iframe]
    │
    ├── 2. CANDIDATE SELECTION PHASE
    │   ├── frame.locator(CANDIDATE_CARD_SELECTOR).all()[index]
    │   ├── card.scroll_into_view_if_needed(timeout=1000)
    │   └── card.click(timeout=1000)
    │
    ├── 3. RESUME CAPTURE SETUP PHASE
    │   ├── _setup_wasm_route(page.context) [resume_capture.py]
    │   └── _install_parent_message_listener(page, logger) [resume_capture.py]
    │
    ├── 4. RESUME PROCESSING PHASE
    │   ├── _get_resume_handle(page, 8000, logger) [resume_capture.py]
    │   └── _process_resume_entry(page, entry, logger) [resume_capture.py]
    │
    └── 5. ERROR HANDLING PHASE (if needed)
        └── collect_resume_debug_info(page) [resume_capture.py]
"""
    frame = _prepare_recommendation_page(page)

    ''' click candidate card '''
    card = frame.locator(CANDIDATE_CARD_SELECTOR).all()[index]
    card.scroll_into_view_if_needed(timeout=1000)
    card.click(timeout=800)

    ''' prepare resume context '''
    from .resume_capture import _setup_wasm_route, _install_parent_message_listener, _get_resume_handle, _process_resume_entry
    _setup_wasm_route(page.context)
    _install_parent_message_listener(page, logger)

    ''' process resume entry '''
    context = _get_resume_handle(page, 10000, logger)
    result = _process_resume_entry(page, context, logger)
    logger.info(f"处理简历结果: {result}")
    
    ''' collect resume debug info '''
    if not result.get('success'):
        result['debug'] = collect_resume_debug_info(page)
    return result

def greet_recommend_candidate_action(page, index: int, message: str) -> Dict[str, Any]:
    """发送标准化打招呼消息给推荐候选人。"""
    frame = _prepare_recommendation_page(page)

    card = frame.locator(CANDIDATE_CARD_SELECTOR).all()[index]
    card.scroll_into_view_if_needed(timeout=1000)
    # card.click(timeout=1000)

    greet_selectors = [
        "button.btn-greet",
        "button:has-text('打招呼')",
        "span:has-text('打招呼')"
    ]

    greeted = False
    for selector in greet_selectors:
        target = card.locator(selector).first
        if target.count():
            target.click(timeout=2000)
            greeted = True
            break

    if not greeted:
        return {'success': False, 'details': '未找到打招呼按钮'}

    if message:
        ''' continue chat '''
        chat_selector = 'button:has-text("继续沟通")'
        chat_btn = card.locator(chat_selector)
        if chat_btn.count():
            chat_btn.click(timeout=1000)

        ''' input message '''
        input_box = page.locator("div.conversation-bd-content")
        input_box.click()
        input_field = input_box.locator("div.bosschat-chat-input")
        input_field.fill("")
        input_field.type(message)

        ''' send message '''
        send_selector = "span:has-text('发送')"
        send_btn = page.locator(send_selector)
        send_btn.click(timeout=1000)

        ''' verify message '''
        t0, sent = time.time(), False
        msg = page.locator("div.conversation-message:has-text('" + message + "')")
        while not msg.count() and (time.time() - t0 < 3) and not sent:
            time.sleep(0.2)
            msg = page.locator("div.conversation-message:has-text('" + message + "')")
        else:
            sent = True

    close_overlay_dialogs(page)

    if sent:
        return { 'success': True, 'details': '已发送消息' }
    elif greeted:
        return { 'success': True, 'details': '已打招呼' }
    else:
        return { 'success': False, 'details': '发送打招呼失败' }