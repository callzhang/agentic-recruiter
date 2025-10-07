"""Common high-level chat actions used by automation flows (async version)."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any, Dict, List, Optional

from playwright.async_api import Locator, Page

from src.config import settings
from .global_logger import get_logger
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
from .boss_utils import close_overlay_dialogs, ensure_on_chat_page

logger = get_logger()

CHAT_MENU_SELECTOR = "dl.menu-chat"
CHAT_ITEM_SELECTORS = "div.geek-item"
CONVERSATION_SELECTOR = "div.conversation-message"
MESSAGE_INPUT_SELECTOR = "#boss-chat-editor-input"
RESUME_BUTTON_SELECTOR = "div.resume-btn-file, a.resume-btn-file"
RESUME_IFRAME_SELECTOR = "iframe.attachment-box"
PDF_VIEWER_SELECTOR = "div.pdfViewer"


async def _prepare_chat_page(page: Page, tab: Optional[str] = None, wait_timeout: int = 5000) -> Page:
    await close_overlay_dialogs(page)
    await ensure_on_chat_page(page, settings, logger)

    if tab:
        tab_selector = f"div.chat-label-item[title*='{tab}']"
        chat_tab = page.locator(tab_selector).first
        try:
            await chat_tab.wait_for(state="visible", timeout=wait_timeout)
            await chat_tab.click()
            await page.locator(CHAT_ITEM_SELECTORS).first.wait_for(state="visible", timeout=wait_timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("切换聊天标签失败(%s): %s", tab, exc)
    return page


async def _go_to_chat_dialog(page: Page, chat_id: str, wait_timeout: int = 5000) -> Optional[Locator]:
    direct_selectors = [
        f"{CHAT_ITEM_SELECTORS}[data-id=\"{chat_id}\"]",
        f"{CHAT_ITEM_SELECTORS}[id='{chat_id}']",
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


async def select_chat_job_action(page: Page, job_title: str) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    current_selected = page.locator("div.ui-dropmenu-label").first
    await current_selected.wait_for(state="visible", timeout=1000)
    current_selected_job = await current_selected.inner_text()
    if job_title in current_selected_job:
        return {"success": True, "details": "已选中职位", "selected_job": current_selected_job}

    await current_selected.click(timeout=1000)
    jobs_locator = page.locator("div.ui-dropmenu-list >> li")
    count = await jobs_locator.count()
    all_job_titles: List[str] = []
    for index in range(count):
        job = jobs_locator.nth(index)
        title = await job.inner_text()
        all_job_titles.append(title)
        if job_title in title:
            await job.click()
            break
    else:
        return {
            "success": False,
            "details": "未找到职位",
            "selected_job": current_selected_job,
            "available_jobs": all_job_titles,
        }

    for _ in range(15):
        current_selected_job = await current_selected.inner_text()
        if job_title in current_selected_job:
            return {"success": True, "details": "已选中职位", "selected_job": current_selected_job}
        await asyncio.sleep(0.2)
    return {
        "success": False,
        "details": "未找到职位",
        "selected_job": current_selected_job,
        "available_jobs": all_job_titles,
    }


async def get_chat_stats_action(page: Page) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    NEW_MESSAGE_SELECTOR = "span.menu-chat-badge"
    NEW_GREET_SELECTOR = "div.chat-label-item[title*='新招呼']"

    try:
        new_message_count_text = await page.locator(NEW_MESSAGE_SELECTOR).inner_text(timeout=1000)
    except Exception:
        new_message_count_text = "0"
    new_message_count = int(new_message_count_text) if new_message_count_text else 0

    try:
        new_greet_text = await page.locator(NEW_GREET_SELECTOR).inner_text(timeout=1000)
        numbers = re.findall(r"\d+", new_greet_text)
        new_greet_count = int(numbers[0]) if numbers else 0
    except Exception:
        new_greet_count = 0
    return {
        "success": True,
        "new_message_count": new_message_count,
        "new_greet_count": new_greet_count,
    }


async def request_resume_action(page: Page, chat_id: str) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return {"success": False, "details": "未找到指定对话项"}

    btn = page.locator("span.operate-btn:has-text('求简历')").first
    await btn.wait_for(state="visible", timeout=3000)
    is_disabled = await btn.evaluate(
        "el => el.classList.contains('disabled') || el.disabled || el.getAttribute('disabled') !== null"
    )
    if is_disabled:
        return {"success": True, "already_sent": True, "details": "简历请求已发送（按钮已禁用）"}

    await btn.click()
    confirm_continue = page.locator("div:has-text('继续交换')").first
    if await confirm_continue.count() > 0:
        await confirm_continue.click()
    confirm = page.locator("span.boss-btn-primary:has-text('确定')").first
    await confirm.click()

    await page.wait_for_function(
        "() => (document.body && document.body.innerText && document.body.innerText.includes('简历请求已发送'))",
        timeout=5000,
    )
    return {"success": True, "already_sent": False, "details": "简历请求已发送"}


async def send_message_action(page: Page, chat_id: str, message: str) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return {"success": False, "details": "未找到指定对话项"}

    input_field = page.locator(MESSAGE_INPUT_SELECTOR).first
    if await input_field.count() == 0:
        return {"success": False, "details": "未找到消息输入框"}

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
    if not remaining:
        return {"success": True, "details": "消息发送成功"}
    return {"success": False, "details": "消息可能未发送成功，输入框仍有内容"}


async def check_full_resume_available(page: Page, chat_id: str, internal: bool = False) -> Optional[Dict[str, Any]]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return {"success": False, "details": "未找到指定对话项"}

    resume_button = page.locator(RESUME_BUTTON_SELECTOR).first
    if await resume_button.count() == 0:
        return {"success": False, "details": "未找到简历按钮"}

    for _ in range(10):
        classes = await resume_button.get_attribute("class") or ""
        if "disabled" not in classes:
            break
        await asyncio.sleep(0.1)
    else:
        return None if internal else {"success": False, "details": "暂无离线简历，请先请求简历"}

    return resume_button if internal else {"success": True, "details": "离线简历已启用"}


async def view_full_resume_action(page: Page, chat_id: str) -> Dict[str, Any]:
    resume_button = await check_full_resume_available(page, chat_id, internal=True)
    if not resume_button:
        return {"success": False, "details": "暂无离线简历，请先请求简历"}

    await resume_button.click()
    try:
        iframe_handle = await page.wait_for_selector(RESUME_IFRAME_SELECTOR, timeout=8000)
        frame = await iframe_handle.content_frame()
        if not frame:
            raise RuntimeError("无法进入简历 iframe")
        await frame.wait_for_selector(PDF_VIEWER_SELECTOR, timeout=5000)
        content = await extract_pdf_viewer_text(frame)
    except Exception as exc:  # noqa: BLE001
        await close_overlay_dialogs(page)
        return {"success": False, "details": "简历查看器未出现", "error": str(exc)}
    finally:
        await close_overlay_dialogs(page)

    return {
        "success": True,
        "details": "简历查看器已打开",
        "content": content.get("text", ""),
        "pages": content.get("pages", []),
    }


async def discard_candidate_action(page: Page, chat_id: str) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return {"success": False, "details": "未找到指定对话项"}

    not_fit_button = page.locator("div.not-fit-wrap").first
    await not_fit_button.wait_for(state="visible", timeout=3000)
    await not_fit_button.hover()
    await asyncio.sleep(0.5)
    await not_fit_button.click()

    await page.wait_for_timeout(300)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if dialog is None:
        return {"success": True, "details": "确认已丢弃"}
    return {"success": False, "details": "确认丢弃失败: 未删除对话"}


async def get_chat_list_action(page: Page, limit: int = 10) -> List[Dict[str, Any]]:
    await _prepare_chat_page(page)
    items = page.locator("div.geek-item")
    count = await items.count()
    messages: List[Dict[str, Any]] = []
    for index in range(min(count, limit)):
        item = items.nth(index)
        try:
            data_id = await item.get_attribute("data-id")
            name = await item.locator("span.geek-name").inner_text()
            job_title = await item.locator("span.source-job").inner_text()
            text = await item.locator("span.push-text").inner_text()
            timestamp = await item.locator("span.time").inner_text()
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取列表项失败 #%s: %s", index, exc)
            continue
        messages.append(
            {
                "id": data_id,
                "name": name.strip(),
                "job_title": job_title.strip(),
                "text": text.strip(),
                "timestamp": timestamp.strip(),
            }
        )
    logger.info("成功获取 %s 条消息", len(messages))
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
        await message.scroll_into_view_if_needed(timeout=200)
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

        system_entry = message.locator("div.item-resume")
        if await system_entry.count() > 0:
            message_str = await system_entry.inner_text(timeout=200)
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


async def accept_resume_action(page: Page, chat_id: str) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return {"success": False, "details": "未找到指定对话项"}

    selectors = [
        "button:has-text('接受')",
        "a:has-text('接受')",
        "xpath=//button[contains(., '接受')]",
        "xpath=//a[contains(., '接受')]",
    ]
    for selector in selectors:
        loc = page.locator(selector).first
        if await loc.count() > 0:
            try:
                if await loc.is_visible(timeout=2000):
                    await loc.click(timeout=2000)
                    logger.info("成功点击接受按钮")
                    return {"success": True, "details": "候选人已接受"}
            except Exception:
                continue
    logger.warning("未找到接受按钮")
    return {"success": False, "details": "未找到接受按钮"}


async def view_online_resume_action(page: Page, chat_id: str) -> Dict[str, Any]:
    await _prepare_chat_page(page)
    dialog = await _go_to_chat_dialog(page, chat_id)
    if not dialog:
        return {"success": False, "details": "未找到指定对话项"}

    candidate_name_locator = page.locator("span.name-box").first
    try:
        candidate_name = await candidate_name_locator.inner_text(timeout=1000)
    except Exception:
        candidate_name = ""

    await _setup_wasm_route(page.context)
    await _install_parent_message_listener(page, logger)

    open_result = await _open_online_resume(page, chat_id, logger)
    if not open_result.get("success"):
        return _create_error_result(open_result, "无法打开在线简历")

    context = await _get_resume_handle(page, 8000, logger)
    if not context.get("success"):
        return _create_error_result(context, context.get("details", "未找到在线简历"))

    result = await _process_resume_entry(page, context, logger)
    if not isinstance(result, dict):
        debug = await collect_resume_debug_info(page)
        return {"success": False, "details": "未知错误: 结果类型异常", "debug": debug}

    result.update({"name": candidate_name, "chat_id": chat_id})
    return result


async def mark_candidate_stage_action(page: Page, chat_id: str, stage: str) -> Dict[str, Any]:
    """Placeholder for updating candidate stage in the chat UI.

    # TODO: 实现 UI 自动化，标记候选人阶段 (PASS / GREET / SEEK / CONTACT)
    """
    return {
        "success": False,
        "details": "TODO: implement stage tagging in chat UI",
        "chat_id": chat_id,
        "stage": stage,
    }


async def notify_hr_action(page: Page, chat_id: str) -> Dict[str, Any]:
    """Placeholder for triggering HR notification workflow.

    # TODO: 实现 HR 通知功能（电话/微信已获取的场景）
    """
    return {
        "success": False,
        "details": "TODO: implement HR notification workflow",
        "chat_id": chat_id,
    }


__all__ = [name for name in globals() if name.endswith("_action") or name.startswith("get_chat")]
