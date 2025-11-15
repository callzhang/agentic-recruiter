"""
Async resume capture helpers mirroring the synchronous implementation in
``src/resume_capture.py``.  The goal is functional parity so that existing
Playwright automation (viewing online resumes, exporting WASM data, canvas
fallbacks, etc.) behaves the same when running with the async Playwright API.
"""

import asyncio
import json
import re
import time
from textwrap import dedent
from typing import Any, Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    Frame,
    Page,
    Request,
    Route,
    TimeoutError as PlaywrightTimeoutError,
)

from .global_logger import logger

INLINE_RESUME_SELECTORS = [
    "div.resume-box",
    "div.resume-content-wrap",
    "div.new-resume-online-main-ui",
]

INLINE_SECTION_HEADINGS = [
    "期望职位",
    "工作经历",
    "项目经验",
    "教育经历",
    "教育经理",
    "资格证书",
    "技能标签",
    "自我评价",
]

DETAIL_TRIGGER_NAMES = {
    "resume_detail",
    "export_resume_detail_info",
    "geek_detail",
    "geek_detail_info",
    "RUST_CALLBACK_POSITION_EXPERIENCE_TITLE_POSITION",
    "RUST_CALLBACK_ANALYSIS_TITLE_POSITION",
}

CANVAS_TEXT_HOOK_SCRIPT = dedent(
    """
    (function(){
      try {
        if (window.__resume_hooked) { return true; }
        window.__resume_hooked = true;
      } catch (err) {}

      var logs = [];

      function record(ctx, text, x, y, style) {
        try {
          logs.push({
            t: String(text || ''),
            x: Number(x) || 0,
            y: Number(y) || 0,
            f: (ctx && ctx.font) || '',
            s: style || (ctx && (ctx.fillStyle || ctx.strokeStyle)) || ''
          });
        } catch (e) {}
      }

      try {
        var proto = window.CanvasRenderingContext2D && window.CanvasRenderingContext2D.prototype;
        if (proto && !proto.__resume_text_wrapped) {
          function wrap(methodName, styleProp) {
            var original = proto[methodName];
            if (typeof original !== 'function') { return; }
            proto[methodName] = function(text, x, y) {
              record(this, text, x, y, this && this[styleProp]);
              return original.apply(this, arguments);
            };
          }
          wrap('fillText', 'fillStyle');
          wrap('strokeText', 'strokeStyle');
          proto.__resume_text_wrapped = true;
        }
      } catch (e) {}

      try {
        var canvasProto = window.HTMLCanvasElement && window.HTMLCanvasElement.prototype;
        if (canvasProto && !canvasProto.__resume_context_wrapped) {
          var originalGetContext = canvasProto.getContext;
          if (typeof originalGetContext === 'function') {
            canvasProto.getContext = function() {
              return originalGetContext.apply(this, arguments);
            };
          }
          canvasProto.__resume_context_wrapped = true;
        }
      } catch (e) {}

      try {
        window.__getResumeTextLogs = function(){ return logs.slice(); };
      } catch (e) {}

      return true;
    })();
    """
)

CANVAS_REBUILD_SCRIPT = dedent(
    """
    (function(){
      try {
        var logs = (window.__getResumeTextLogs && window.__getResumeTextLogs()) || [];
        logs.sort(function(a, b){
          var ay = (a && a.y) || 0;
          var by = (b && b.y) || 0;
          var dy = ay - by;
          if (dy !== 0) { return dy; }
          var ax = (a && a.x) || 0;
          var bx = (b && b.x) || 0;
          return ax - bx;
        });
        var tol = 4;
        var lines = [];
        for (var i = 0; i < logs.length; i++) {
          var item = logs[i];
          var y = Number(item && item.y) || 0;
          var last = lines.length ? lines[lines.length - 1] : null;
          if (!last || Math.abs(last.y - y) > tol) {
            lines.push({ y: y, parts: [item] });
          } else {
            last.parts.push(item);
          }
        }
        function esc(s) {
          return String(s).replace(/[<&>]/g, function(ch){
            if (ch === '<') { return '&lt;'; }
            if (ch === '>') { return '&gt;'; }
            return '&amp;';
          });
        }
        var textLines = [];
        var htmlLines = [];
        for (var j = 0; j < lines.length; j++) {
          var line = lines[j];
          var txt = '';
          var parts = (line && line.parts) || [];
          for (var k = 0; k < parts.length; k++) {
            var part = parts[k];
            txt += String((part && part.t) || '');
          }
          textLines.push(txt);
          htmlLines.push('<div>' + esc(txt) + '</div>');
        }
        return {
          html: htmlLines.join('\\n'),
          text: textLines.join('\\n'),
          lineCount: lines.length,
          itemCount: logs.length
        };
      } catch (err) {
        return { html: '', text: '', lineCount: 0, itemCount: 0, error: String(err) };
      }
    })();
    """
)

PARENT_MESSAGE_HOOK_SCRIPT = dedent(
    """
    (function(){
      try {
        if (window.__resume_message_hooked) { return true; }
        window.__resume_message_hooked = true;
      } catch (err) {
      }

      function safeClone(value) {
        try {
          if (typeof structuredClone === 'function') {
            return structuredClone(value);
          }
        } catch (err) {}
        try {
          if (value === undefined) {
            return value;
          }
          return JSON.parse(JSON.stringify(value));
        } catch (err) {}
        return value;
      }

      function pushMessage(entry) {
        try {
          window.__resume_messages = window.__resume_messages || [];
          window.__resume_messages.push(entry);
        } catch (err) {}
      }

      try {
        window.addEventListener('message', function(evt){
          try {
            if (!evt || !evt.data) { return; }
            var payload = evt.data;
            if (payload && payload.type === 'IFRAME_DONE') {
              pushMessage({ ts: Date.now(), data: safeClone(payload) });
            }
          } catch (err) {}
        }, true);
      } catch (err) {}

      return true;
    })();
    """
)


def _has_resume_detail(payload: Any) -> bool:
    if isinstance(payload, dict):
        keys = set(payload.keys())
        if keys.intersection(
            {
                "geekDetailInfo",
                "geekWorkExpList",
                "geekProjExpList",
                "resumeModuleInfoList",
                "geekWorkPositionExpDescList",
            }
        ):
            return True
        if "abstractData" in payload and isinstance(payload["abstractData"], dict):
            return _has_resume_detail(payload["abstractData"])
    elif isinstance(payload, list) and payload:
        head = payload[0]
        if isinstance(head, dict):
            keys = set(head.keys())
            if keys and keys.intersection({"company", "positionName", "projectName", "projectDesc", "duty"}):
                return True
    return False


def _log(logger_obj, level: str, message: str) -> None:
    try:
        if logger_obj and hasattr(logger_obj, level):
            getattr(logger_obj, level)(message)
    except Exception:
        pass


def _format_inline_text(text: str) -> str:
    if not text:
        return ""
    protection_texts = [
        "为妥善保护牛人在BOSS直聘平台提交、发布、展示的简历",
        "包括但不限于在线简历、附件简历",
        "包括但不限于联系方式、期望职位、教育经历、工作经历等",
        "任何用户原则上仅可出于自身招聘的目的",
        "通过BOSS直聘平台在线浏览牛人简历",
        "未经BOSS直聘及牛人本人书面授权",
        "任何用户不得将牛人在BOSS直聘平台提交、发布、展示的简历中的个人信息",
        "在任何第三方平台进行复制、使用、传播、存储",
        "BOSS直聘平台",
        "个人信息",
    ]
    lines = text.splitlines()
    output: List[str] = []
    for raw in lines:
        trimmed = raw.strip()
        if trimmed and any(protection_text in trimmed for protection_text in protection_texts):
            continue
        if trimmed and any(trimmed.startswith(h) for h in INLINE_SECTION_HEADINGS):
            output.append("")
            output.append(trimmed)
            output.append("---")
        else:
            output.append(raw)
    while output and output[-1] == "":
        output.pop()
    formatted = "\n".join(output)
    while "\n\n\n" in formatted:
        formatted = formatted.replace("\n\n\n", "\n\n")
    return formatted.strip("\n")


def _inline_snapshot_has_content(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not snapshot:
        return False
    text = (snapshot.get("text") or "").strip()
    if text:
        return True
    data_props = (snapshot.get("dataProps") or "").strip()
    if data_props:
        return True
    if snapshot.get("hasResumeItem") or snapshot.get("hasSectionTitle"):
        return True
    return False


def _extract_inline_snapshot(snapshot: Dict[str, Any], html_limit: int = 0) -> Dict[str, Any]:
    result = dict(snapshot or {})
    text = result.get("text") or ""
    formatted = _format_inline_text(text)
    result["formattedText"] = formatted or text
    trimmed = result["formattedText"] or ""
    snippet = trimmed[:1000]
    if trimmed and len(trimmed) > 1000:
        snippet += "...<truncated>"
    result["textSnippet"] = snippet

    html_content = result.get("html") or ""
    if html_limit and html_limit > 0 and len(html_content) > html_limit:
        result["htmlSnippet"] = html_content[:html_limit] + "...<truncated>"
    else:
        result["htmlSnippet"] = html_content
    return result


async def _snapshot_inline_resume(page_or_frame: Page | Frame) -> Optional[Dict[str, Any]]:
    try:
        return await page_or_frame.evaluate(
            """
            ({ selectors }) => {
              const list = Array.isArray(selectors) ? selectors : [];
              let target = null;
              for (const sel of list) {
                const node = document.querySelector(sel);
                if (node) { target = node; break; }
              }
              if (!target) return null;
              const rect = target.getBoundingClientRect();
              const closestData = target.closest('[data-props]') || document.querySelector('[data-props]');
              const html = target.innerHTML || '';
              const text = target.innerText || '';
              const dataProps = closestData ? (closestData.getAttribute('data-props') || '') : '';
              const hasResumeItem = !!target.querySelector('.resume-item');
              const hasSectionTitle = !!target.querySelector('.section-title');
              return {
                mode: 'inline',
                selector: target.tagName ? target.tagName.toLowerCase() : null,
                classList: Array.from(target.classList || []),
                childCount: target.childElementCount || 0,
                canvasCount: target.querySelectorAll ? target.querySelectorAll('canvas').length : 0,
                htmlLength: html.length,
                html,
                text,
                dataProps,
                textLength: text.length,
                dataPropsLength: dataProps.length,
                hasResumeItem,
                hasSectionTitle,
                boundingRect: {
                  x: rect.x,
                  y: rect.y,
                  width: rect.width,
                  height: rect.height,
                  top: rect.top,
                  left: rect.left,
                  bottom: rect.bottom,
                  right: rect.right,
                }
              };
            }
            """,
            {"selectors": INLINE_RESUME_SELECTORS},
        )
    except Exception:
        return None


async def _setup_wasm_route(context: BrowserContext) -> None:
    from pathlib import Path

    wasm_dir = Path(__file__).resolve().parents[1] / "wasm"
    patched_map: Dict[str, Path] = {}
    for patched in wasm_dir.glob("wasm_canvas-*_patched.js"):
        original = patched.name.replace("_patched", "")
        patched_map[original] = patched

    if not patched_map:
        logger.warning("本地 wasm_canvas_*_patched.js 未找到，跳过路由拦截")
        return

    glob_pattern = "**/wasm_canvas-*.js"

    async def _route_resume(route: Route, request: Request) -> None:

        filename = request.url.rsplit("/", 1)[-1]
        local_path = patched_map.get(filename)
        logger.debug("---->拦截 %s，使用本地 patched 版本 %s", filename, local_path)
        await route.abort(error_code="timedout")
        return
        if not local_path:
            # Fallback: try to find the highest versioned patch for the same base version
            import re
            m = re.match(r"(wasm_canvas-\d+\.\d+\.\d+)-(\d+)\.js", filename)
            if m:
                base, ver = m.group(1), int(m.group(2))
                # Find all matching patches with same base and lower or equal version
                candidates = [
                    (int(patched.name.split('-')[-1].split('_')[0]), patched)
                    for patched in patched_map.values()
                    if patched.name.startswith(base) and "_patched.js" in patched.name
                ]
                if candidates:
                    # Pick the highest version <= requested
                    best = max((v, p) for v, p in candidates if v <= ver)
                    logger.debug("未找到 %s，回退到本地 patched 版本 %s", filename, best[1])
                    local_path = best[1]
                    # await route.fulfill(path=str(best[1]), content_type="application/javascript; charset=utf-8")
                else:
                    logger.warning("未找到 %s，跳过路由拦截", filename)
                    #TODO: add dingtalk notification
                    await route.continue_()
                    return

        logger.debug("---->拦截 %s，使用本地 patched 版本 %s", filename, local_path)
        await route.fulfill(path=str(local_path), content_type="application/javascript; charset=utf-8")
        
    try:
        await context.unroute(glob_pattern)
    except Exception:
        pass
    await context.route(glob_pattern, _route_resume)


async def _capture_inline_resume(
    page_or_frame: Page | Frame,
    logger=None,
    html_limit: int = 0,
    *,
    max_attempts: int = 10,
) -> Optional[Dict[str, Any]]:
    for _ in range(max_attempts):
        snapshot = await _snapshot_inline_resume(page_or_frame)
        if _inline_snapshot_has_content(snapshot):
            return _extract_inline_snapshot(snapshot, html_limit)
        await asyncio.sleep(0.25)
    return None


async def _open_online_resume(page: Page, chat_id: str, logger=None) -> Dict[str, Any]:
    target = page.locator(
        f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
        f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
    ).first
    try:
        if not await target.count():
            return {"success": False, "details": "未找到指定对话项"}
        await target.scroll_into_view_if_needed(timeout=2000)
        await target.wait_for(state="visible", timeout=5000)
        await target.click()
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "details": f"定位会话失败: {exc}"}

    try:
        await page.wait_for_selector("div.conversation-message", timeout=5000)
    except Exception:
        return {"success": False, "details": "对话面板未出现"}

    try:
        btn = page.locator("a.resume-btn-online").first
        await btn.wait_for(state="visible", timeout=5000)
        await btn.click()
    except Exception as exc:
        return {"success": False, "details": f"点击在线简历失败: {exc}"}

    return {"success": True, "details": "已打开在线简历"}


async def _get_resume_handle(page: Page, timeout_ms: int = 10000, logger=None) -> Dict[str, Any]:
    from .ui_utils import IFRAME_OVERLAY_SELECTOR, RESUME_OVERLAY_SELECTOR

    iframe = page.locator(IFRAME_OVERLAY_SELECTOR)
    overlay = page.locator(RESUME_OVERLAY_SELECTOR)

    if await overlay.count() > 0:
        await overlay.locator(INLINE_RESUME_SELECTORS[0]).wait_for(state="visible", timeout=timeout_ms)
        return {
            "success": True,
            "mode": "inline",
            "iframe_handle": iframe,
            "entry": overlay,
        }

    if await iframe.count() > 0:
        await iframe.wait_for(state="attached", timeout=timeout_ms)
        tag = await iframe.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == "iframe":
            handle = await iframe.first.element_handle()
            frame = await handle.content_frame() if handle else None
            entry = frame.locator(RESUME_OVERLAY_SELECTOR) if frame else None
            await entry.wait_for(state="visible", timeout=timeout_ms)
            if entry and await entry.count() > 0:
                return {
                    "success": True,
                    "mode": "inline",
                    "iframe_handle": iframe,
                    "frame": frame,
                    "entry": entry,
                }
            return {
                "success": True,
                "mode": "iframe",
                "iframe_handle": iframe,
                "frame": frame,
            }
        return {
            "success": False,
            "mode": "unknown",
            "frame": iframe,
        }

    return {
        "success": False,
        "mode": "unknown",
        "frame": None,
        "details": "未检测到简历容器",
    }


def _create_error_result(open_result: Dict[str, Any], details: str) -> Dict[str, Any]:
    mode = None
    if isinstance(open_result, dict):
        mode = open_result.get("mode")
    return {
        "success": False,
        "mode": mode,
        "details": details,
    }


async def _install_parent_message_listener(page: Page, logger=None) -> bool:
    installed = False
    try:
        await page.evaluate("() => { try { window.__resume_messages = []; } catch (_) {} }")
    except Exception:
        pass
    try:
        if await page.evaluate(PARENT_MESSAGE_HOOK_SCRIPT):
            installed = True
    except Exception as exc:
        _log(logger, "error", f"安装父级消息监听失败: {exc}")
    for frame in page.frames:
        try:
            await frame.evaluate(PARENT_MESSAGE_HOOK_SCRIPT)
            installed = True
        except Exception:
            continue
    return installed


async def _collect_parent_messages(page: Page, logger=None) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = []
    errors: List[str] = []

    async def fetch(frame: Page | Frame) -> List[Dict[str, Any]]:
        try:
            data = await frame.evaluate(
                """
                () => {
                  try {
                    const store = window.__resume_messages;
                    if (!store || !Array.isArray(store)) {
                      return [];
                    }
                    return store.slice();
                  } catch (err) {
                    return { __error: String(err) };
                  }
                }
                """
            )
            if isinstance(data, dict) and "__error" in data:
                errors.append(str(data["__error"]))
                return []
            if isinstance(data, list):
                return data
        except Exception as exc:
            errors.append(str(exc))
        return []

    messages.extend(await fetch(page))
    for frame in page.frames:
        messages.extend(await fetch(frame))

    abstract_data = None
    for msg in messages:
        payload = msg.get("data") if isinstance(msg, dict) else None
        if isinstance(payload, dict):
            candidate = payload.get("abstractData")
            if isinstance(candidate, dict) and _has_resume_detail(candidate):
                abstract_data = candidate
                break
    success = isinstance(abstract_data, dict) and bool(abstract_data)
    result: Dict[str, Any] = {
        "success": success,
        "text": abstract_data if isinstance(abstract_data, dict) else {},
        "messages": messages,
        "method": "消息捕获",
    }
    if not success:
        result["error"] = "未截获abstractData"
        if errors:
            result["errors"] = errors
    return result


async def _try_wasm_exports(frame: Frame, logger=None) -> Optional[Dict[str, Any]]:
    payload: Optional[Dict[str, Any]] = None
    try:
        payload = await frame.evaluate(
            """
            async () => {
                const out = { data: null, error: null, attempts: [] };
                const hasPayload = (val) => {
                    if (!val) return false;
                    if (Array.isArray(val)) return val.length > 0;
                    if (typeof val === 'object') return Object.keys(val).length > 0;
                    return true;
                };

                const ensureStore = () => {
                    if (typeof window.__resume_data_store !== 'object' || window.__resume_data_store === null) {
                        try {
                            window.__resume_data_store = {};
                        } catch (_) {
                            return {};
                        }
                    }
                    return window.__resume_data_store;
                };

                const takeFromStore = () => {
                    try {
                        const store = ensureStore();
                        const data = store.export_geek_detail_info || store.geek_detail_info;
                        return hasPayload(data) ? data : null;
                    } catch (err) {
                        out.attempts.push(`store:${err}`);
                        return null;
                    }
                };

                const useModule = async (mod, label) => {
                    if (!mod) return null;
                    const tag = (msg) => out.attempts.push(`${label||'mod'}:${msg}`);

                    try {
                        if (typeof mod.default === 'function') {
                            await mod.default();
                        }
                    } catch (err) {
                        tag(`init:${err}`);
                    }

                    try {
                        const store = ensureStore();
                        if (typeof mod.register_js_callback === 'function') {
                            try {
                                mod.register_js_callback('export_geek_detail_info', (d) => {
                                    try { store.export_geek_detail_info = d; } catch (_) {}
                                });
                            } catch (err) {
                                tag(`register-export:${err}`);
                            }
                            try {
                                mod.register_js_callback('geek_detail_info', (d) => {
                                    try { store.geek_detail_info = d; } catch (_) {}
                                });
                            } catch (err) {
                                tag(`register-geek:${err}`);
                            }
                        }
                    } catch (err) {
                        tag(`store:${err}`);
                    }

                    try {
                        if (typeof mod.get_export_geek_detail_info === 'function') {
                            const direct = mod.get_export_geek_detail_info();
                            if (hasPayload(direct)) {
                                return direct;
                            }
                        }
                    } catch (err) {
                        tag(`get:${err}`);
                    }

                    const triggerPayloads = [undefined, null, '', 'null', '{}', '[]', { force: true }, []];
                    const triggerNames = [
                        'export_geek_detail_info',
                        'geek_detail_info',
                        'export_resume_detail_info',
                        'resume_detail',
                        'geek_detail',
                    ];

                    if (typeof mod.trigger_rust_callback === 'function') {
                        for (const name of triggerNames) {
                            for (const payload of triggerPayloads) {
                                try {
                                    mod.trigger_rust_callback(name, payload);
                                    tag(`trigger:${name}:${typeof payload}:ok`);
                                } catch (err) {
                                    tag(`trigger:${name}:${typeof payload}:${err}`);
                                }
                            }
                        }
                    }

                    for (let attempt = 0; attempt < 6; attempt++) {
                        const storeData = takeFromStore();
                        if (hasPayload(storeData)) {
                            return storeData;
                        }
                        if (typeof mod.get_export_geek_detail_info === 'function') {
                            try {
                                const retryDirect = mod.get_export_geek_detail_info();
                                if (hasPayload(retryDirect)) {
                                    return retryDirect;
                                }
                            } catch (err) {
                                tag(`retry-get:${err}`);
                            }
                        }
                        await new Promise((resolve) => setTimeout(resolve, 20 * (attempt + 1)));
                    }

                    const fallbackStore = takeFromStore();
                    if (hasPayload(fallbackStore)) {
                        return fallbackStore;
                    }

                    return null;
                };

                try {
                    if (typeof get_export_geek_detail_info === 'function') {
                        const direct = get_export_geek_detail_info();
                        if (hasPayload(direct)) {
                            out.data = direct;
                            return out;
                        }
                    }
                } catch (err) {
                    out.attempts.push(`global-direct:${err}`);
                }

                const moduleObjects = [];
                try {
                    const store = ensureStore();
                    const globalKeys = Object.keys(window);
                    for (const key of globalKeys) {
                        if (!key) continue;
                        let val;
                        try {
                            val = window[key];
                        } catch (_) {
                            continue;
                        }
                        if (!val || (typeof val !== 'object' && typeof val !== 'function')) continue;
                        const hasExports = typeof val.register_js_callback === 'function'
                            && typeof val.trigger_rust_callback === 'function';
                        if (hasExports || typeof val.get_export_geek_detail_info === 'function') {
                            moduleObjects.push({ label: `window.${key}`, module: val });
                        }
                    }
                } catch (err) {
                    out.attempts.push(`enumerate:${err}`);
                }

                for (const entry of moduleObjects) {
                    try {
                        const res = await useModule(entry.module, entry.label);
                        if (hasPayload(res)) {
                            out.data = res;
                            return out;
                        }
                    } catch (err) {
                        out.attempts.push(`use-${entry.label}:${err}`);
                    }
                }

                const urlCandidates = new Set();
                const pushUrl = (url, reason) => {
                    if (!url || typeof url !== 'string') return;
                    try {
                        const normalized = new URL(url, window.location.href).href;
                        urlCandidates.add(normalized);
                        out.attempts.push(`candidate:${reason}:${normalized}`);
                    } catch (_) {}
                };

                const nodes = [
                    ...Array.from(document.querySelectorAll("script[type='module'][src]")),
                    ...Array.from(document.querySelectorAll('script[src]')),
                    ...Array.from(document.querySelectorAll("link[rel='modulepreload'][href]")),
                    ...Array.from(document.querySelectorAll("link[rel='preload'][as='script'][href]"))
                ];
                for (const node of nodes) {
                    const src = node && (node.src || node.href);
                    if (!src) continue;
                    const lower = src.toLowerCase();
                    if (lower.includes('wasm') && lower.includes('canvas') && lower.endsWith('.js')) {
                        pushUrl(src, 'match');
                    } else if (lower.includes('index') && lower.endsWith('.js')) {
                        try {
                            const normalized = new URL(src, window.location.href);
                            const baseHref = normalized.href.replace(/[^/]*$/, '');
                            pushUrl(`${baseHref}wasm_canvas-1.0.2-5030_patched.js`, 'derived');
                        } catch (_) {}
                    }
                }

                try {
                    const resources = (performance && typeof performance.getEntriesByType === 'function')
                        ? performance.getEntriesByType('resource')
                        : [];
                    for (const entry of resources || []) {
                        if (entry && entry.name) {
                            pushUrl(entry.name, 'perf');
                        }
                    }
                } catch (_) {}

                const fallbackVersion = '1.0.2-5030';
                try {
                    pushUrl(new URL(`wasm_canvas-${fallbackVersion}.js`, window.location.href).href, 'fallback-relative');
                } catch (_) {}
                try {
                    pushUrl(`https://static.zhipin.com/assets/zhipin/wasm/resume/wasm_canvas-${fallbackVersion}.js`, 'fallback-global');
                } catch (_) {}

                for (const url of Array.from(urlCandidates)) {
                    try {
                        const mod = await import(url);
                        const res = await useModule(mod, url);
                        if (hasPayload(res)) {
                            out.data = res;
                            return out;
                        }
                    } catch (err) {
                        out.attempts.push(`import:${url}:${err}`);
                    }
                }

                const finalStore = takeFromStore();
                if (hasPayload(finalStore)) {
                    out.data = finalStore;
                }

                return out;
            }
            """
        )
    except Exception as exc:
        _log(logger, "error", f"WASM导出失败: {exc}")

    if not isinstance(payload, dict):
        return None

    extras: Dict[str, Any]
    try:
        extras = await frame.evaluate(
            """
            () => {
                const out = {};
                try {
                    const node = document.querySelector('[data-props]');
                    if (node) {
                        const raw = node.getAttribute('data-props');
                        if (raw) {
                            try {
                                out.dataProps = JSON.parse(raw);
                            } catch (err) {
                                out.dataPropsError = String(err);
                            }
                        }
                    }
                } catch (err) {
                    out.dataPropsError = String(err);
                }
                try {
                    const state = window.__INITIAL_STATE__;
                    if (state) {
                        out.initialStateKeys = Object.keys(state || {});
                        if (state.resume) {
                            out.initialResume = state.resume;
                        } else if (state.geekDetail) {
                            out.initialResume = state.geekDetail;
                        }
                    }
                } catch (err) {
                    out.initialStateError = String(err);
                }
                return out;
            }
            """
        )
    except Exception as extras_err:
        extras = {"error": str(extras_err)}

    try:
        store_state = await frame.evaluate(
            """
            () => {
                try {
                    const store = window.__resume_data_store || {};
                    return {
                        exportInfo: store.export_geek_detail_info || null,
                        geekInfo: store.geek_detail_info || null,
                        callbackLogs: Array.isArray(store.callbackLogs) ? store.callbackLogs.slice() : [],
                        triggerLogs: Array.isArray(store.triggerLogs) ? store.triggerLogs.slice() : [],
                    };
                } catch (err) {
                    return { __error: String(err) };
                }
            }
            """
        )
    except Exception as store_err:
        store_state = {"__error": str(store_err)}

    data_obj = payload.get("data")
    if isinstance(data_obj, dict) and isinstance(extras, dict):
        data_obj.update(extras)

    if isinstance(data_obj, dict) and isinstance(store_state, dict):
        if "__error" in store_state:
            data_obj.setdefault("storeErrors", []).append(store_state["__error"])
        export_info = store_state.get("exportInfo")
        if isinstance(export_info, dict):
            data_obj.setdefault("exportInfo", export_info)
            if isinstance(export_info.get("geekDetailInfo"), dict):
                data_obj.setdefault("geekDetailInfo", {}).update(export_info["geekDetailInfo"])
            if isinstance(export_info.get("geekWorkExpList"), list) and export_info["geekWorkExpList"]:
                data_obj["geekWorkExpList"] = export_info["geekWorkExpList"]
            if isinstance(export_info.get("geekProjExpList"), list) and export_info["geekProjExpList"]:
                data_obj["geekProjExpList"] = export_info["geekProjExpList"]

        geek_info = store_state.get("geekInfo")
        if isinstance(geek_info, dict) and geek_info:
            data_obj.setdefault("geekDetailInfo", {}).update(geek_info)

        trigger_details: Dict[str, Any] = {}
        for entry in store_state.get("triggerLogs") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            result_payload = entry.get("result")
            if name in DETAIL_TRIGGER_NAMES or _has_resume_detail(result_payload):
                if result_payload not in (None, "", [], {}):
                    trigger_details[name] = result_payload
        if trigger_details:
            data_obj.setdefault("triggerDetails", {}).update(trigger_details)
            for detail in trigger_details.values():
                if isinstance(detail, dict):
                    if isinstance(detail.get("geekDetailInfo"), dict):
                        data_obj.setdefault("geekDetailInfo", {}).update(detail["geekDetailInfo"])
                    if isinstance(detail.get("geekWorkExpList"), list) and detail["geekWorkExpList"]:
                        data_obj["geekWorkExpList"] = detail["geekWorkExpList"]
                    if isinstance(detail.get("geekProjExpList"), list) and detail["geekProjExpList"]:
                        data_obj["geekProjExpList"] = detail["geekProjExpList"]
                    if isinstance(detail.get("geekWorkPositionExpDescList"), list) and detail["geekWorkPositionExpDescList"]:
                        data_obj["geekWorkPositionExpDescList"] = detail["geekWorkPositionExpDescList"]

        callback_details: Dict[str, Any] = {}
        for entry in store_state.get("callbackLogs") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            payload_data = entry.get("payload")
            if not name or payload_data in (None, "", []):
                continue
            if name in {"FIRST_LAYOUT", "SEGMENT_TEXT", "SEND_ACTION"} or _has_resume_detail(payload_data):
                callback_details.setdefault(name, []).append(payload_data)
                if isinstance(payload_data, dict):
                    abstract = payload_data.get("abstractData")
                    if isinstance(abstract, dict) and _has_resume_detail(abstract):
                        if isinstance(abstract.get("geekProjExpList"), list) and abstract["geekProjExpList"]:
                            data_obj["geekProjExpList"] = abstract["geekProjExpList"]
                        if isinstance(abstract.get("geekWorkExpList"), list) and abstract["geekWorkExpList"]:
                            data_obj["geekWorkExpList"] = abstract["geekWorkExpList"]
                        if isinstance(abstract.get("geekDetailInfo"), dict):
                            data_obj.setdefault("geekDetailInfo", {}).update(abstract["geekDetailInfo"])
        if callback_details:
            data_obj.setdefault("callbackDetails", {}).update(callback_details)

    result = {
        "text": data_obj,
        "method": "WASM导出",
    }
    if isinstance(data_obj, dict) and data_obj.get("geekBaseInfo"):
        result["success"] = True
    else:
        result["success"] = False
        result["error"] = (
            data_obj.get("error")
            if isinstance(data_obj, dict)
            else None
        ) or extras.get("error") if isinstance(extras, dict) else "WASM导出失败"
    return result


async def _install_canvas_text_hooks(frame: Frame, logger=None) -> bool:
    if frame is None:
        return False
    try:
        return bool(await frame.evaluate(CANVAS_TEXT_HOOK_SCRIPT))
    except Exception as exc:
        _log(logger, "error", f"安装fillText钩子失败: {exc}")
        return False


async def _rebuild_text_from_logs(frame: Frame, logger=None) -> Optional[Dict[str, Any]]:
    if frame is None:
        return None
    try:
        await frame.wait_for_selector("canvas#resume", timeout=5000)
    except Exception:
        pass
    try:
        rebuilt = await frame.evaluate(CANVAS_REBUILD_SCRIPT)
        if isinstance(rebuilt, dict) and (rebuilt.get("text") or rebuilt.get("html")):
            return rebuilt
    except Exception as exc:
        _log(logger, "error", f"canvas拦截失败: {exc}")
    return None


async def _install_clipboard_hooks(frame: Frame, logger=None) -> bool:
    if frame is None:
        return False
    try:
        code = (
            "(function(){\n"
            "  try { if (window.__resume_clipboard_hooked) return true; } catch(e) {}\n"
            "  try { window.__resume_clipboard_hooked = true; } catch(e) {}\n"
            "  try { if (!window.__clipboardWrites) window.__clipboardWrites = []; } catch(e) {}\n"
            "  try {\n"
            "    if (navigator && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {\n"
            "      var orig = navigator.clipboard.writeText.bind(navigator.clipboard);\n"
            "      navigator.clipboard.writeText = function(t){\n"
            "        try { (window.__clipboardWrites||[]).push({ text: String(t||''), ts: Date.now() }); } catch(e) {}\n"
            "        return orig(t);\n"
            "      };\n"
            "    }\n"
            "  } catch(e) {}\n"
            "  try {\n"
            "    var origExec = document.execCommand && document.execCommand.bind(document);\n"
            "    if (origExec) {\n"
            "      document.execCommand = function(cmd){\n"
            "        var r = true;\n"
            "        try { r = origExec.apply(document, arguments); } catch(e) {}\n"
            "        try {\n"
            "          var c = String(cmd||'').toLowerCase();\n"
            "          if (c === 'copy') {\n"
            "            var sel = '';\n"
            "            try { sel = String(window.getSelection && window.getSelection()); } catch(e2) {}\n"
            "            (window.__clipboardWrites||[]).push({ text: sel||'', ts: Date.now(), via: 'execCommand' });\n"
            "          }\n"
            "        } catch(e3) {}\n"
            "        return r;\n"
            "      };\n"
            "    }\n"
            "  } catch(e) {}\n"
            "  return true;\n"
            "})();"
        )
        return bool(await frame.evaluate(code))
    except Exception as exc:
        _log(logger, "error", f"安装剪贴板钩子失败: {exc}")
        return False


async def _read_clipboard_logs(frame: Frame, logger=None) -> Optional[str]:
    if frame is None:
        return None
    try:
        data = await frame.evaluate(
            "(function(){ try { return (window.__clipboardWrites||[]).slice(); } catch(e){ return []; } })()"
        )
        if isinstance(data, list) and data:
            texts: List[str] = []
            seen: set[str] = set()
            for item in data:
                try:
                    text = str((item or {}).get("text") or "")
                    if text and text not in seen:
                        seen.add(text)
                        texts.append(text)
                except Exception:
                    continue
            if texts:
                return "\n".join(texts)
    except Exception:
        return None
    return None


async def _try_trigger_copy_buttons(frame: Frame, logger=None) -> None:
    if frame is None:
        return
    selectors = [
        "button:has-text('复制')",
        "a:has-text('复制')",
        "button:has-text('复制简历')",
        "a:has-text('复制简历')",
        "button:has-text('导出')",
        "a:has-text('导出')",
    ]
    for selector in selectors:
        try:
            target = frame.locator(selector).first
            if not await target.count():
                continue
            try:
                await target.click()
                await frame.wait_for_timeout(300)
            except Exception:
                continue
        except Exception:
            continue


async def collect_resume_debug_info(page: Page, logger=None) -> Dict[str, Any]:
    info: Dict[str, Any] = {"frames": [], "resources": []}
    for frame in page.frames:
        frame_info: Dict[str, Any] = {
            "name": frame.name,
            "url": frame.url,
        }
        try:
            frame_info["canvasCount"] = await frame.locator("canvas").count()
            frame_info["iframeCount"] = await frame.locator("iframe").count()
        except Exception:
            frame_info["canvasCount"] = 0
            frame_info["iframeCount"] = 0
        try:
            frame_info["scripts"] = await frame.evaluate(
                "() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src)"
            )
        except Exception:
            frame_info["scripts"] = []
        try:
            frame_info["resumeStore"] = await frame.evaluate(
                "() => { try { return window.__resume_data_store || null; } catch (_) { return 'error'; } }"
            )
        except Exception:
            frame_info["resumeStore"] = "error"
        info["frames"].append(frame_info)

    try:
        info["resources"] = await page.evaluate(
            "() => (performance.getEntriesByType('resource') || [])"
        )
    except Exception:
        info["resources"] = []
    return info


async def _try_canvas_text_hooks(frame: Frame, logger=None) -> Dict[str, Any]:
    hooked = await _install_canvas_text_hooks(frame, logger)
    rebuilt = await _rebuild_text_from_logs(frame, logger) if hooked else None
    if rebuilt and (rebuilt.get("text") or rebuilt.get("html")):
        return {
            "success": True,
            "text": rebuilt.get("text"),
            "html": rebuilt.get("html"),
            "method": "Canvas拦截",
        }
    return {"success": False, "error": "Canvas拦截失败", "method": "Canvas拦截"}


async def _try_clipboard_hooks(frame: Frame, logger=None) -> Dict[str, Any]:
    await _install_clipboard_hooks(frame, logger)
    await _try_trigger_copy_buttons(frame, logger)
    clip_text = await _read_clipboard_logs(frame, logger)
    if clip_text:
        return {
            "success": True,
            "text": clip_text,
            "method": "剪贴板拦截",
        }
    return {"success": False, "error": "剪贴板拦截失败", "method": "剪贴板拦截"}


async def _process_resume_entry(page: Page, context_info: Dict[str, Any], logger=None) -> Dict[str, Any]:
    mode = context_info.get("mode")
    frame: Optional[Frame] = context_info.get("frame")

    if mode == "inline":
        inline_data = await _capture_inline_resume(frame or page, logger, max_attempts=5)
        if inline_data:
            rect = inline_data.get("boundingRect") or {}
            text = inline_data.get("formattedText") or inline_data.get("text")
            html = inline_data.get("htmlSnippet") or inline_data.get("html")
            return {
                "success": True,
                "text": text,
                "textLenth": len(text),
                "htmlLenth": len(html),
                "width": int(rect.get("width") or 0),
                "height": int(rect.get("height") or 0),
                "details": "来自inline简历",
            }
        entry = context_info.get("entry")
        if entry:
            text = await entry.inner_text()
            html = await entry.inner_html()
            return {
                "success": True,
                "text": text,
                "textLenth": len(text),
                "htmlLenth": len(html),
                "details": "来自inner_text简历",
            }
        return {"success": False, "details": "未找到inline简历容器"}

    if mode == "iframe" and frame:
        parent_result = await _collect_parent_messages(page, logger)
        wasm_result = await _try_wasm_exports(frame, logger)
        canvas_result = await _try_canvas_text_hooks(frame, logger)
        hooks_result = await _try_clipboard_hooks(frame, logger)

        results = [res for res in [parent_result, wasm_result, canvas_result, hooks_result] if isinstance(res, dict)]
        success = any(result.get("success") for result in results)
        methods = [result.get("method") for result in results]

        aggregated_text: Dict[str, Any] = {}
        for result in results:
            payload = result.get("text")
            if isinstance(payload, dict):
                aggregated_text.update(payload)
            elif isinstance(payload, str) and payload:
                aggregated_text[result.get("method", "文本")] = payload

        error_msg = "\n".join(filter(None, [result.get("error", "") for result in results]))
        if not isinstance(results[-1], dict):
            debug_info = await collect_resume_debug_info(page, logger)
            return {
                "success": False,
                "details": "未知错误: 简历结果异常",
                "debug": debug_info,
            }
        return {
            "success": success,
            "text": aggregated_text,
            "capture_method": methods,
            "error": error_msg,
        }

    return {"success": False, "details": "未知的简历模式"}


async def extract_pdf_viewer_text(frame: Frame) -> Dict[str, Any]:
    # use inner_html to extract text
    try:
        text_list = []
        pdf_text_layer = frame.locator("div.textLayer")
        await pdf_text_layer.first.wait_for(state="visible", timeout=5000)
        for page in await pdf_text_layer.all():
            html = await page.inner_html()
            text = extract_text_from_pdfjs_html(html)
            text_list.append(text)
        text = "\n".join(text_list)
        cleaned_text = clean_resume_text(text)
        assert len(cleaned_text) > 100, "PDF文本长度小于100"
        return {"pages": [], "text": cleaned_text}
    except Exception as e:
        logger.error(f"提取PDF文本失败: {e}\n {cleaned_text}")
        pass

    # use evaluate to extract text
    try:
        pages: Any = await frame.evaluate(
            dedent(
                """
                (async () => {
                  const app = window.PDFViewerApplication;
                  if (!app || !app.pdfDocument) {
                    return { __error: 'pdfDocument not ready' };
                  }

                  const doc = app.pdfDocument;
                  const viewer = app.pdfViewer;
                  const scale = viewer && viewer._currentScale ? viewer._currentScale : 1;
                  const results = [];

                  for (let pageIndex = 1; pageIndex <= doc.numPages; pageIndex++) {
                    const page = await doc.getPage(pageIndex);
                    const viewport = page.getViewport({ scale });
                    const textContent = await page.getTextContent();

                    const items = textContent.items
                      .map(item => {
                        const [x, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
                        const height = item.height || Math.abs(item.transform[3]) || 1;
                        const width = item.width || Math.abs(item.transform[0]) || 1;
                        return { text: item.str, x, y, height, width };
                      })
                      .filter(entry => entry.text && entry.text.trim());

                    items.sort((a, b) => {
                      if (Math.abs(a.y - b.y) > 2) {
                        return a.y - b.y;
                      }
                      return a.x - b.x;
                    });

                    const lines = [];
                    let currentY = null;
                    let buffer = [];
                    let tolerance = 6;
                    if (items.length) {
                      const heights = items.map(s => s.height).filter(Boolean);
                      const avg = heights.reduce((acc, val) => acc + val, 0) / heights.length;
                      tolerance = Math.max(6, avg * 0.8);
                    }

                    const flush = () => {
                      if (!buffer.length) return;
                      const joined = buffer
                        .join(' ')
                        .replace(/\u00a0/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                      if (joined) {
                        lines.push(joined);
                      }
                      buffer = [];
                    };

                    for (const item of items) {
                      if (currentY === null) {
                        currentY = item.y;
                      }
                      if (Math.abs(item.y - currentY) > tolerance) {
                        flush();
                        currentY = item.y;
                      }
                      buffer.push(item.text);
                    }
                    flush();

                    results.push({ page: pageIndex, lines, text: lines.join('\n') });
                  }

                  return results;
                })()
                """
            )
        )
    except Exception as e:
        logger.error(f"evaluate frame文本失败: {e}")
        pages = {}

    if isinstance(pages, dict):
        if "__error" in pages:
            pages = []
        else:
            pages = [pages]

    combined: List[str] = []
    for page_data in pages:
        for line in page_data.get("lines", []) or []:
            if line:
                combined.append(line)

    cleaned_text = clean_resume_text("\n".join(combined))
    if len(cleaned_text) < 100:
        logger.error(f"evaluate frame文本长度小于100: {cleaned_text}")

    # fallback to inner_text
    pages = []
    fallback = await frame.evaluate("() => document.body ? document.body.innerText || '' : ''")
    fallback = clean_pdf_text(fallback)
    if len(fallback) < 100:
        logger.error(f"fallback to inner_text文本长度小于100: {fallback}")
    return {"pages": [], "text": fallback, "error": str(e)}



def clean_resume_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "<TRIPLE_NL>", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"\n\s\n", "\n", text)
    text = text.replace("<TRIPLE_NL>", "\n\n")
    return text.strip()

import re, unicodedata

def clean_pdf_text(raw: str) -> str:
    text = raw.replace('\x00', '')
    text = re.sub(r'[\x01-\x1F\x7F]', '', text)
    # remove BOSS-style hashed tokens like f6a4b4051154ea161XJ_2tS-GFFTwYu4VvOcWOGkl_7RPhFl3g~~
    text = re.sub(r'[A-Za-z0-9_-]{10,}~~', '', text)
    # merge single-char lines
    text = re.sub(r'(?<=\S)\n(?=\S)', '', text)
    # collapse newlines and spaces
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = unicodedata.normalize('NFKC', text)
    return text.strip()

from bs4 import BeautifulSoup
import re

def extract_text_from_pdfjs_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Try standard textLayer spans first
    spans = soup.select(".textLayer span")
    if not spans:
        # fallback: PDF.js markedContent structure
        spans = soup.select("span.markedContent span[role='presentation']")

    items = []
    for s in spans:
        style = s.get("style", "")
        m_top = re.search(r"top:\s*([\d.]+)px", style)
        m_left = re.search(r"left:\s*([\d.]+)px", style)
        text = s.get_text(strip=True)
        if m_top and m_left and text:
            items.append((float(m_top.group(1)), float(m_left.group(1)), text))

    if not items:
        # fallback to simple innerText for debugging
        return soup.get_text(separator="", strip=True)

    # Sort by vertical then horizontal position
    items.sort(key=lambda x: (round(x[0], 1), x[1]))
    lines = []
    buffer, current_y = [], None
    for y, x, t in items:
        if current_y is None or abs(y - current_y) > 5:
            if buffer:
                lines.append("".join(buffer))
            buffer = [t]
            current_y = y
        else:
            buffer.append(t)
    if buffer:
        lines.append("".join(buffer))
    return "\n".join(lines)


__all__ = [
    "_setup_wasm_route",
    "_install_parent_message_listener",
    "_open_online_resume",
    "_get_resume_handle",
    "_create_error_result",
    "_process_resume_entry",
    "extract_pdf_viewer_text",
    "collect_resume_debug_info",
    "clean_resume_text",
]
