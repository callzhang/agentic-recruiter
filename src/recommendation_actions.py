"""Recommendation page actions for Boss Zhipin automation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    if not page.url.startswith("https://www.zhipin.com/web/chat/recommend"):
        menu_locator = page.locator("dl.menu-recommend").first
        menu_locator.scroll_into_view_if_needed(timeout=2000)
        menu_locator.click()

    # Wait for the iframe to appear and get its frame
    iframe = page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, timeout=wait_timeout)
    
    if frame := iframe.content_frame():
        frame.wait_for_selector(CANDIDATE_CARD_SELECTOR, timeout=wait_timeout)
        logger.info("已导航到推荐页面")
    else:
        page.wait_for_selector(CANDIDATE_CARD_SELECTOR, timeout=wait_timeout)
    return frame


def list_recommended_candidates_action(page, *, limit: int = 20) -> Dict[str, Any]:
    """Click the recommended panel and return structured card information."""
    frame = _prepare_recommendation_page(page)

    # Use the frame to locate card items
    card_locators: List[Locator] = frame.locator(CANDIDATE_CARD_SELECTOR).all()

    candidates = []
    for card in card_locators[:limit]:
        card.scroll_into_view_if_needed(timeout=1000)
        viewd = 'viewed' in card.get_attribute('class')
        text = card.inner_text().strip()
        candidates.append({
            'viewed': viewd,
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
    card.click(timeout=1000)

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


def select_current_job_action(page, job_title: str) -> Dict[str, Any]:
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
    try:
        # 获取所有职位选项
        job_options = page.locator('div.ui-dropmenu >> ul.job-list > li').all()
        
        if not job_options:
            return {'success': False, 'details': '未找到职位下拉菜单'}
        
        # 查找包含指定职位标题的选项
        selected_option = None
        for option in job_options:
            try:
                option_text = option.inner_text().strip()
                if job_title in option_text:
                    selected_option = option
                    logger.info(f"找到匹配的职位: {option_text}")
                    break
            except Exception as e:
                logger.warning(f"获取职位选项文本失败: {e}")
                continue
        
        if not selected_option:
            available_jobs = []
            for option in job_options:
                try:
                    available_jobs.append(option.inner_text().strip())
                except Exception:
                    continue
            return {
                'success': False, 
                'details': f'未找到包含"{job_title}"的职位',
                'available_jobs': available_jobs
            }
        
        # 点击选中的职位
        selected_option.click(timeout=3000)
        logger.info(f"已点击职位: {job_title}")
        
        # 等待页面变化并验证选择
        try:
            # 等待下拉菜单标签更新
            page.wait_for_timeout(1000)  # 给页面一点时间更新
            
            # 检查下拉菜单标签是否已更新
            dropdown_label = page.locator('div.ui-dropmenu > div.ui-dropmenu-label').first
            if dropdown_label.count():
                label_text = dropdown_label.inner_text().strip()
                if job_title in label_text:
                    return {
                        'success': True,
                        'details': f'成功选择职位: {label_text}',
                        'selected_job': label_text
                    }
                else:
                    return {
                        'success': False,
                        'details': f'职位选择可能失败，当前显示: {label_text}',
                        'expected_job': job_title,
                        'actual_job': label_text
                    }
            else:
                return {
                    'success': False,
                    'details': '无法验证职位选择，未找到下拉菜单标签'
                }
                
        except Exception as e:
            logger.warning(f"验证职位选择时出错: {e}")
            return {
                'success': True,
                'details': f'已点击职位但无法验证: {job_title}',
                'warning': str(e)
            }
            
    except Exception as e:
        logger.error(f"选择职位时发生错误: {e}")
        return {
            'success': False,
            'details': f'选择职位失败: {str(e)}'
        }


def greet_recommend_candidate_action(page, index: int, message: str) -> Dict[str, Any]:
    """发送标准化打招呼消息给推荐候选人。"""
    frame = _prepare_recommendation_page(page)

    card = frame.locator(CANDIDATE_CARD_SELECTOR).all()[index]
    card.scroll_into_view_if_needed(timeout=1000)
    card.click(timeout=1000)

    greet_selectors = [
        "button:has-text('打招呼')",
        "span:has-text('打招呼')",
        "text=打招呼",
    ]

    greeted = False
    for selector in greet_selectors:
        target = page.locator(selector).first
        if not target.count():
            continue
        try:
            target.wait_for(state="visible", timeout=2000)
            target.click(timeout=2000)
            greeted = True
            break
        except Exception:
            continue

    if not greeted:
        return {'success': False, 'details': '未找到打招呼按钮'}

    input_selectors = [
        "#boss-chat-editor-input",
        "textarea",
        "div.editor textarea",
    ]
    input_box = None
    for selector in input_selectors:
        candidate = page.locator(selector).first
        if candidate.count():
            input_box = candidate
            break

    if input_box:
        try:
            input_box.click()
            input_box.fill("")
            input_box.type(message)
        except Exception:
            try:
                input_box.evaluate("(el, value) => { if (el.value !== undefined) el.value = value; }", message)
            except Exception:
                pass

    send_selectors = [
        "div.submit:has-text('发送')",
        "button:has-text('发送')",
        "span:has-text('发送')",
    ]
    sent = False
    for selector in send_selectors:
        btn = page.locator(selector).first
        if not btn.count():
            continue
        try:
            btn.click(timeout=2000)
            sent = True
            break
        except Exception:
            continue

    close_overlay_dialogs(page)

    chat_id = None
    try:
        selected = page.locator("div.geek-item.selected").first
        if selected.count():
            chat_id = selected.get_attribute('data-id')
    except Exception:
        pass

    if not sent:
        return {'success': False, 'details': '发送消息失败', 'chat_id': chat_id}

    return {
        'success': True,
        'details': '已发送打招呼',
        'chat_id': chat_id,
    }
