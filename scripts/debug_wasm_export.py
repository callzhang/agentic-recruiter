#!/usr/bin/env python3
"""Deep WASM resume debug helper with structured logging."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.resume_capture import (  # noqa: E402
    capture_resume_from_chat,
)

CaptureFn = Callable[[str, Optional[Any]], None]


def _safe_preview(payload: Any, limit: int = 1000) -> str:
    """Create a safe preview of payload with proper newline handling."""
    _process_string = lambda s: s[:limit] + "..." if len(s) > limit else s
    
    def _process_value(value):
        """Process a single value."""
        if isinstance(value, str):
            return _process_string(value)
        elif isinstance(value, dict):
            return {k: _process_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_process_value(item) for item in value]
        else:
            return _process_string(str(value))
    
    try:
        processed = _process_value(payload)
        return json.dumps(processed, ensure_ascii=False, indent=2)
    except Exception:
        return _process_string(str(payload))


def _print_step(title: str, payload: Optional[Any] = None) -> None:
    print(f"\n=== {title} ===")
    if payload is None:
        print('(Empty payload)')
        return
    
    preview = _safe_preview(payload)
    print(preview)


class _StdoutLogger:
    def info(self, msg: str) -> None:
        print(f"[INFO] {msg}")

    def error(self, msg: str) -> None:
        print(f"[ERROR] {msg}")

    def warning(self, msg: str) -> None:
        print(f"[WARNING] {msg}")


@contextmanager
def _playwright_connection() -> Iterable[Tuple[Any, Browser]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(settings.CDP_URL)
        try:
            yield playwright, browser
        finally:
            pass  # 浏览器由外部生命周期管理


def _navigate_to_chat(page: Page, capture: CaptureFn) -> None:
    if settings.CHAT_URL in (page.url or ''):
        return
    try:
        page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception as err:
        capture("导航错误", {"error": str(err)})


def _get_first_chat_id(page: Page, capture: CaptureFn) -> Optional[str]:
    try:
        first_item = page.locator("div.geek-item").first
        first_item.wait_for(state="visible", timeout=3000)
        chat_id = first_item.get_attribute("data-id") or first_item.get_attribute("id")
        capture("获取聊天ID", {"chat_id": chat_id})
        return chat_id
    except Exception as err:
        capture("获取聊天ID失败", {"error": str(err)})
    return None


def _validate_chat_id(page: Page, chat_id: str, capture: CaptureFn) -> bool:
    """Validate that the provided chat_id exists on the page."""
    try:
        # Try to find the chat item with the provided ID
        chat_item = page.locator(f"div.geek-item[data-id='{chat_id}'], div.geek-item[id='{chat_id}']").first
        if chat_item.count() > 0:
            capture("验证聊天ID", {"chat_id": chat_id, "status": "found"})
            return True
        else:
            capture("验证聊天ID", {"chat_id": chat_id, "status": "not_found"})
            return False
    except Exception as e:
        capture("验证聊天ID失败", {"chat_id": chat_id, "error": str(e)})
        return False


def _run_debug_step(capture: CaptureFn, title: str, runner: Callable[[], Dict[str, Any]]) -> None:
    try:
        payload = runner()
    except Exception as err:
        payload = {"error": str(err)}
    capture(title, payload)


def _save_results(output_path: pathlib.Path, results: List[Dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n保存调试输出到 {output_path}")
    except Exception as err:
        print(f"保存调试输出失败: {err}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deep WASM resume debug helper",
        epilog="Examples:\n"
               "  python debug_wasm_export.py                    # Use first available chat\n"
               "  python debug_wasm_export.py --chat-id abc123   # Test specific chat ID",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output",
        default=str((ROOT / 'scripts' / 'debug_wasm_export_output.json').resolve()),
        help="Path for JSON output",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        help="Specific chat ID to test (if not provided, will use the first available chat)",
    )
    parser.add_argument(
        "--use-local-wasm",
        action="store_true",
        help="Serve local wasm_canvas bundle (behaves differently from production)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    results: List[Dict[str, Any]] = []
    start = time.time()

    def capture(title: str, payload: Optional[Any] = None) -> None:
        elapsed = time.time() - start
        record = {"title": title, "payload": payload, "elapsed": elapsed}
        results.append(record)
        _print_step(f"{title} (t+{elapsed:.2f}s)", payload)

    with _playwright_connection() as (_, browser):
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        _navigate_to_chat(page, capture)

        # Use provided chat_id or get the first available one
        if args.chat_id:
            chat_id = args.chat_id
            capture("使用提供的聊天ID", {"chat_id": chat_id})
            # Validate that the provided chat_id exists
            if not _validate_chat_id(page, chat_id, capture):
                capture("错误", {"message": f"提供的聊天ID '{chat_id}' 在页面上未找到"})
                _save_results(pathlib.Path(args.output), results)
                return
        else:
            chat_id = _get_first_chat_id(page, capture)
            if not chat_id:
                _save_results(pathlib.Path(args.output), results)


        # 直接使用 capture_resume_from_chat 进行简历捕获
        primary = capture_resume_from_chat(page, chat_id, _StdoutLogger())
        capture("主捕获(auto)", primary)



    _save_results(pathlib.Path(args.output), results)


if __name__ == "__main__":
    main()
