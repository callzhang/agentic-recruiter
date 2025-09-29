#!/usr/bin/env python3
"""Debug helper for recommended candidate resume extraction."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.recommendation_actions import (
    _prepare_recommendation_page,
    view_recommend_candidate_resume_action,
)
from src.resume_capture import collect_resume_debug_info  # noqa: E402
from src.ui_utils import close_overlay_dialogs  # noqa: E402


def _connect_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(settings.CDP_URL)
    return playwright, browser


def _get_primary_page(browser):
    contexts = browser.contexts
    for context in contexts:
        pages = context.pages
        if pages:
            return context, pages[0]
    raise RuntimeError('未找到可用的浏览器页面')


def debug_candidate(index: int, inspect_only: bool = False, wait_ms: int = 2000) -> dict:
    playwright, browser = _connect_browser()
    try:
        context, page = _get_primary_page(browser)
        frame, error = _prepare_recommendation_page(page)
        if error:
            return {'success': False, 'details': '准备推荐页面失败', 'payload': error}

        resume_frame_info = {}
        if inspect_only:
            card = frame.locator("div.candidate-card-wrap").nth(index)
            card.scroll_into_view_if_needed(timeout=1000)
            card.click()
            page.wait_for_timeout(wait_ms)
            result = {'success': False, 'details': 'inspect_only'}
            resume_frame = next((fr for fr in page.frames if 'c-resume' in fr.url), None)
            if resume_frame:
                try:
                    resume_frame_info = resume_frame.evaluate(
                        "() => ({ store: window.__resume_data_store || null, keys: Object.keys(window || {}) })"
                    )
                except Exception as exc:
                    resume_frame_info = {'error': str(exc)}
        else:
            result = view_recommend_candidate_resume_action(page, index)
        debug_info = collect_resume_debug_info(page)
        pages_urls = []
        for ctx in browser.contexts:
            for p in ctx.pages:
                pages_urls.append(p.url)

        payload = {
            'result': result,
            'debug': debug_info,
            'frames': [(fr.name, fr.url) for fr in page.frames],
            'pages': pages_urls,
            'resumeFrame': resume_frame_info,
        }
        close_overlay_dialogs(page)
        return payload
    finally:
        browser.close()
        playwright.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description='调试推荐候选人简历抓取流程')
    parser.add_argument('--index', type=int, default=0, help='候选人索引 (0-based)')
    parser.add_argument('--inspect-only', action='store_true', help='只收集调试信息，不触发正式抓取逻辑')
    parser.add_argument('--wait-ms', type=int, default=2000, help='点击卡片后等待毫秒数，再收集调试信息')
    parser.add_argument('--output', type=pathlib.Path, help='输出JSON文件路径')
    args = parser.parse_args()

    payload = debug_candidate(args.index, inspect_only=args.inspect_only, wait_ms=args.wait_ms)
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.output:
        args.output.write_text(text, encoding='utf-8')
        print(f"调试信息已写入 {args.output}")
    else:
        print(text)


if __name__ == '__main__':
    main()
