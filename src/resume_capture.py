"""
Resume capture helpers: robust multi-step pipeline to extract structured
resume text from the WASM-driven viewer embedded in an iframe.

Primary entrypoint: capture_resume_from_chat(page, chat_id, logger=None)

Steps (in order):
- open chat and click "在线简历"
- locate iframe ('c-resume') or inline resume container
- tap iframe→parent postMessage payloads
- query WASM exports / triggers for JSON data
- install canvas & clipboard hooks as defensive fallbacks

This module is intentionally verbose and defensive.
"""

from __future__ import annotations
import re, json
import time
from textwrap import dedent
from typing import Any, Dict, Optional, TYPE_CHECKING
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.sync_api import Frame


INLINE_RESUME_SELECTORS = [
    'div.resume-box', # inner div
    'div.resume-content-wrap', # middle div
    'div.new-resume-online-main-ui', # outer div
]

INLINE_SECTION_HEADINGS = [
    '期望职位',
    '工作经历',
    '项目经验',
    '教育经历',
    '教育经理',
    '资格证书',
    '技能标签',
    '自我评价',
]

DETAIL_TRIGGER_NAMES = {
    'resume_detail',
    'export_resume_detail_info',
    'geek_detail',
    'geek_detail_info',
    'RUST_CALLBACK_POSITION_EXPERIENCE_TITLE_POSITION',
    'RUST_CALLBACK_ANALYSIS_TITLE_POSITION',
}


def _has_resume_detail(payload: Any) -> bool:
    if isinstance(payload, dict):
        keys = set(payload.keys())
        if keys.intersection({'geekDetailInfo', 'geekWorkExpList', 'geekProjExpList', 'resumeModuleInfoList', 'geekWorkPositionExpDescList'}):
            return True
        if 'abstractData' in payload and isinstance(payload['abstractData'], dict):
            return _has_resume_detail(payload['abstractData'])
    elif isinstance(payload, list) and payload:
        head = payload[0]
        if isinstance(head, dict):
            keys = set(head.keys())
            if keys and keys.intersection({'company', 'positionName', 'projectName', 'projectDesc', 'duty'}):
                return True
    return False


CANVAS_TEXT_HOOK_SCRIPT = dedent("""
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
""")


CANVAS_REBUILD_SCRIPT = dedent("""
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
      html: htmlLines.join('\\\\n'),
      text: textLines.join('\\\\n'),
      lineCount: lines.length,
      itemCount: logs.length
    };
  } catch (err) {
    return { html: '', text: '', lineCount: 0, itemCount: 0, error: String(err) };
  }
})();
""")


PARENT_MESSAGE_HOOK_SCRIPT = dedent("""
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
""")


def _log(logger, level: str, message: str) -> None:
    try:
        if logger and hasattr(logger, level):
            getattr(logger, level)(message)
    except Exception:
        pass


def _format_inline_text(text: str) -> str:
    if not text:
        return ''
    
    # 过滤保护文本
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
        "个人信息"
    ]
    
    lines = text.splitlines()
    output = []
    for raw in lines:
        trimmed = raw.strip()
        
        # 跳过保护文本
        if trimmed and any(protection_text in trimmed for protection_text in protection_texts):
            continue
            
        if trimmed and any(trimmed.startswith(h) for h in INLINE_SECTION_HEADINGS):
            output.append('')
            output.append(trimmed)
            output.append('---')
        else:
            output.append(raw)
    
    while output and output[-1] == '':
        output.pop()
    formatted = "\n".join(output)
    while "\n\n\n" in formatted:
        formatted = formatted.replace("\n\n\n", "\n\n")
    return formatted.strip("\n")


def _snapshot_inline_resume(page) -> Optional[Dict[str, Any]]:
    try:
        return page.evaluate(
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


def _setup_wasm_route(context):
    """如果启用且本地存在 wasm 文件，则用它替换远程资源."""

    from pathlib import Path

    wasm_dir = Path(__file__).resolve().parents[1] / 'wasm'
    patched_map = {}
    for patched in wasm_dir.glob('wasm_canvas-*_patched.js'):
        original = patched.name.replace('_patched', '')
        patched_map[original] = patched

    if not patched_map:
        print("本地 wasm_canvas_*_patched.js 未找到，跳过路由拦截")
        return

    glob_pattern = "**/wasm_canvas-*.js"

    def _route_resume(route, request):
        if request.method.upper() != 'GET':
            return route.continue_()
        filename = request.url.rsplit('/', 1)[-1]
        local_path = patched_map.get(filename)
        if not local_path:
            return route.continue_()
        print(f"----> 拦截 {filename}，使用本地 patched 版本{local_path}")
        return route.fulfill(
            path=str(local_path),
            content_type='application/javascript; charset=utf-8',
        )

    try:
        context.unroute(glob_pattern)
    except Exception:
        pass
    context.route(glob_pattern, _route_resume)


def _inline_snapshot_has_content(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not snapshot:
        return False
    text = (snapshot.get('text') or '').strip()
    if text:
        return True
    data_props = (snapshot.get('dataProps') or '').strip()
    if data_props:
        return True
    if snapshot.get('hasResumeItem') or snapshot.get('hasSectionTitle'):
        return True
    return False


def _extract_inline_snapshot(snapshot: Dict[str, Any], html_limit: int = 0) -> Dict[str, Any]:
    result = dict(snapshot or {})
    text = result.get('text') or ''
    formatted = _format_inline_text(text)
    result['formattedText'] = formatted or text
    trimmed = result['formattedText'] or ''
    snippet = trimmed[:1000]
    if trimmed and len(trimmed) > 1000:
        snippet += '...<truncated>'
    result['textSnippet'] = snippet

    html_content = result.get('html') or ''
    if html_limit and html_limit > 0 and len(html_content) > html_limit:
        result['htmlSnippet'] = html_content[:html_limit] + '...<truncated>'
    else:
        result['htmlSnippet'] = html_content
    return result


def _capture_inline_resume(
    page,
    logger=None,
    html_limit: int = 0,
    *,
    max_attempts: int = 10,
) -> Optional[Dict[str, Any]]:
    for _ in range(max_attempts):
        snapshot = _snapshot_inline_resume(page)
        if _inline_snapshot_has_content(snapshot):
            return _extract_inline_snapshot(snapshot, html_limit)
        time.sleep(0.25)
    return None


def _open_online_resume(page, chat_id: str, logger=None) -> Dict[str, Any]:
    """Open the target chat and click the online resume button.
    Returns { success, details } and leaves the UI on the online resume dialog.
    """
    # Close existing overlay if present=
    # close_overlay_dialogs(page, logger)

    # Focus the chat item
    target = None
    try:
        precise = page.locator(
            f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
            f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
        ).first
        if precise and precise.count() > 0:
            target = precise
        target.wait_for(state="visible", timeout=5000)
        target.click()
    except Exception:
        target = None
    if not target:
        return { 'success': False, 'details': '未找到指定对话项' }

    # Wait for conversation panel
    try:
        page.wait_for_selector("div.conversation-message", timeout=5000)
    except Exception:
        return { 'success': False, 'details': '对话面板未出现' }

    # Click online resume button
    try:
        btn = page.locator("a.resume-btn-online").first
        btn.wait_for(state="visible", timeout=5000)
        btn.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击在线简历失败: {e}' }

    # wait for the div.toast to disappear
    # try:
    #     page.wait_for_selector("div.toast", timeout=5000)
    #     page.wait_for_selector("div.toast", state="detached", timeout=5000)
    #     _log(logger, "info", "toast消失")
    #     time.sleep(1)
    # except Exception as e:
    #     _log(logger, "error", f"等待toast消失失败: {e}")

    # #IMPORTANT: wait for the div.toast to disappear, but we cannot use playwright to wait for it because it will be blocked by the iframe
    # time.sleep(8)

    return { 'success': True, 'details': '已打开在线简历' }


def _get_resume_handle(page, timeout_ms=10000, logger=None) -> Dict[str, Any]:
    """
    Detects and returns the handle to the resume overlay or iframe for further processing.

    This function inspects the current page for the presence of the resume overlay or iframe,
    and returns a dictionary describing the mode and relevant handles for downstream capture logic.

    Args:
        page: The Playwright page object.
        timeout_ms (int): Timeout in milliseconds to wait for the resume overlay or iframe to appear.
        logger: Optional logger for debug output.

    Returns:
        Dict[str, Any]: A dictionary with keys:
            - 'mode': One of 'inline', 'iframe', or 'unknown'.
            - 'frame': The Playwright frame or page object containing the resume.
            - 'iframe_handle': (optional) The locator for the iframe element, if applicable.

    Raises:
        Exception: If neither the overlay nor the iframe is found within the timeout.
    """
    t0 = time.time()
    tag = None
    from .ui_utils import IFRAME_OVERLAY_SELECTOR, RESUME_OVERLAY_SELECTOR
    iframe = page.locator(IFRAME_OVERLAY_SELECTOR)
    overlay = page.locator(RESUME_OVERLAY_SELECTOR)
    if overlay.count() > 0:
        ''' `wait_for()` ANYTHING WILL cause the canvas pressits'''
        # overlay.wait_for(timeout=timeout_ms)
        # page.wait_for_selector(RESUME_OVERLAY_SELECTOR, timeout=timeout_ms)
        # page.wait_for_selector(INLINE_RESUME_SELECTORS[0], timeout=timeout_ms)
        ''' try waiting the iframe to be destroyed'''
        # page.wait_for_selector(IFRAME_OVERLAY_SELECTOR, state="detached", timeout=timeout_ms)
        ''' use polling methods '''
        # while iframe.count() > 0 and time.time() - t0 < timeout_ms/1000:
        #     time.sleep(1)
        #     iframe = page.locator(IFRAME_OVERLAY_SELECTOR)
        ''' use page.evaluate() to wait for the iframe to be destroyed'''
        # Wait for the inline resume selector to appear, but with a timeout
        # result = page.evaluate(
        #     """({ sel, timeout }) => new Promise(resolve => {
        #         const start = Date.now();
        #         const check = () => {
        #             if (document.querySelector(sel)) {
        #                 resolve(true);
        #             } else if (Date.now() - start > timeout) {
        #                 resolve(false);
        #             } else {
        #                 setTimeout(check, 1000);
        #             }
        #         };
        #         check();
        #     })""",
        #     { "sel": INLINE_RESUME_SELECTORS[0], "timeout": timeout_ms }
        # )
        # print(f"发现inline resume handle: {INLINE_RESUME_SELECTORS[0]}: {result}")
        ''' non of the above methods worked, so we just wait for the timeout '''
        time.sleep(timeout_ms/1000)
        return {
            'mode': 'inline',
            'iframe_handle': iframe,
            'entry': overlay,
        }
    elif iframe.count() > 0:
        iframe.wait_for(state="attached", timeout=timeout_ms)
        tag = iframe.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == 'iframe':
            iframe_handle = iframe.first.element_handle()
            frame = iframe_handle.content_frame() if iframe_handle else None
            entry = frame.locator(RESUME_OVERLAY_SELECTOR)
            # entries = frame.wait_for_selector(RESUME_OVERLAY_SELECTOR, timeout=timeout_ms) if frame else None
            time.sleep(timeout_ms/1000)
            if entry.count() > 0:
                return {
                    'mode': 'inline',
                    'iframe_handle': iframe,
                    'frame': frame,
                    'entry': entry,
                }
            else:
                return {
                    'mode': 'iframe',
                    'iframe_handle': iframe,
                    'frame': frame,
                }
        else:
            return {
                'mode': 'unkown',
                'frame': iframe,
            }

    


def _create_error_result(open_result: Dict[str, Any], details: str) -> Dict[str, Any]:
    """Create a standardized error result."""
    return {
        'success': False,
        'mode': None,
        'details': details,
        'openResult': open_result,
    }


def _try_wasm_exports(frame, logger=None) -> Optional[Dict[str, Any]]:
    """Attempt to retrieve structured data from WASM module.
    Returns a dict if found; otherwise None.
    """
    payload = None
    try:
        payload = frame.evaluate(
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

                    let directResult = null;
                    try {
                        if (typeof mod.get_export_geek_detail_info === 'function') {
                            directResult = mod.get_export_geek_detail_info();
                            if (hasPayload(directResult)) {
                                return directResult;
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
        extras = None
        try:
            extras = frame.evaluate(
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
            extras = { 'error': str(extras_err) }

        store_state = {}
        try:
            store_state = frame.evaluate(
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
            store_state = { '__error': str(store_err) }

        
        data_obj = payload.get("data")
        if isinstance(data_obj, dict) and isinstance(extras, dict):
            data_obj.update(extras)

        if isinstance(data_obj, dict) and isinstance(store_state, dict):
            if '__error' in store_state:
                data_obj.setdefault('storeErrors', []).append(store_state['__error'])
            export_info = store_state.get('exportInfo')
            if isinstance(export_info, dict):
                data_obj.setdefault('exportInfo', export_info)
                if isinstance(export_info.get('geekDetailInfo'), dict):
                    data_obj.setdefault('geekDetailInfo', {}).update(export_info['geekDetailInfo'])
                if isinstance(export_info.get('geekWorkExpList'), list) and export_info['geekWorkExpList']:
                    data_obj['geekWorkExpList'] = export_info['geekWorkExpList']
                if isinstance(export_info.get('geekProjExpList'), list) and export_info['geekProjExpList']:
                    data_obj['geekProjExpList'] = export_info['geekProjExpList']

            geek_info = store_state.get('geekInfo')
            if isinstance(geek_info, dict) and geek_info:
                data_obj.setdefault('geekDetailInfo', {}).update(geek_info)

            trigger_details: Dict[str, Any] = {}
            for entry in store_state.get('triggerLogs') or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get('name') or '').strip()
                if not name:
                    continue
                result_payload = entry.get('result')
                if name in DETAIL_TRIGGER_NAMES or _has_resume_detail(result_payload):
                    if result_payload not in (None, '', [], {}):
                        trigger_details[name] = result_payload
            if trigger_details:
                data_obj.setdefault('triggerDetails', {}).update(trigger_details)
                for detail in trigger_details.values():
                    if isinstance(detail, dict):
                        if isinstance(detail.get('geekDetailInfo'), dict):
                            data_obj.setdefault('geekDetailInfo', {}).update(detail['geekDetailInfo'])
                        if isinstance(detail.get('geekWorkExpList'), list) and detail['geekWorkExpList']:
                            data_obj['geekWorkExpList'] = detail['geekWorkExpList']
                        if isinstance(detail.get('geekProjExpList'), list) and detail['geekProjExpList']:
                            data_obj['geekProjExpList'] = detail['geekProjExpList']
                        if isinstance(detail.get('geekWorkPositionExpDescList'), list) and detail['geekWorkPositionExpDescList']:
                            data_obj['geekWorkPositionExpDescList'] = detail['geekWorkPositionExpDescList']

            callback_details: Dict[str, Any] = {}
            for entry in store_state.get('callbackLogs') or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get('name') or '').strip()
                payload_data = entry.get('payload')
                if not name or payload_data in (None, '', []):
                    continue
                if name in {'FIRST_LAYOUT', 'SEGMENT_TEXT', 'SEND_ACTION'} or _has_resume_detail(payload_data):
                    callback_details.setdefault(name, []).append(payload_data)
                    if isinstance(payload_data, dict):
                        abstract = payload_data.get('abstractData')
                        if isinstance(abstract, dict) and _has_resume_detail(abstract):
                            if isinstance(abstract.get('geekProjExpList'), list) and abstract['geekProjExpList']:
                                data_obj['geekProjExpList'] = abstract['geekProjExpList']
                            if isinstance(abstract.get('geekWorkExpList'), list) and abstract['geekWorkExpList']:
                                data_obj['geekWorkExpList'] = abstract['geekWorkExpList']
                            if isinstance(abstract.get('geekDetailInfo'), dict):
                                data_obj.setdefault('geekDetailInfo', {}).update(abstract['geekDetailInfo'])
            if callback_details:
                data_obj.setdefault('callbackDetails', {}).update(callback_details)

        result = {
            'text': data_obj,
            'method': 'WASM导出'
            }
        if data_obj.get('geekBaseInfo'):
            result['success'] = True
        else:
            result['success'] = False
            result['error'] = data_obj.get('error') or extras.get('error') or 'WASM导出失败'
        return result
    except Exception as e:
        _log(logger, "error", f"WASM导出失败: {payload}, \nError: {e}")
    return None


def _install_canvas_text_hooks(frame, logger=None) -> bool:
    if frame is None:
        return False
    try:
        return bool(frame.evaluate(CANVAS_TEXT_HOOK_SCRIPT))
    except Exception as e:
        _log(logger, "error", f"安装fillText钩子失败: {e}")
        return False


def _install_parent_message_listener(page, logger=None) -> bool:
    if page is None:
        return False
    installed = False
    try:
        page.evaluate("() => { try { window.__resume_messages = []; } catch (_) {} }")
    except Exception:
        pass
    try:
        if page.evaluate(PARENT_MESSAGE_HOOK_SCRIPT):
            installed = True
    except Exception as e:
        _log(logger, 'error', f'安装父级消息监听失败: {e}')
    for frame in page.frames:
        if frame is page.main_frame:
            continue
        try:
            frame.evaluate(PARENT_MESSAGE_HOOK_SCRIPT)
            installed = True
        except Exception:
            continue
    return installed


def _collect_parent_messages(page, logger=None) -> Dict[str, Any]:
    """Collect iframe→parent resume messages captured by PARENT_MESSAGE_HOOK_SCRIPT."""
    if page is None:
        return {'success': False, 'text': {}, 'messages': [], 'error': '页面对象缺失', 'method': '消息捕获'}

    try:
        messages = []
        def _fetch_messages(frame):
            return frame.evaluate(
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

        base = _fetch_messages(page)
        if isinstance(base, dict) and '__error' in base:
            messages_info = base
        else:
            messages.extend(base if isinstance(base, list) else [])
            messages_info = None
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            try:
                frame_messages = _fetch_messages(frame)
            except Exception:
                continue
            if isinstance(frame_messages, dict) and '__error' in frame_messages:
                messages_info = frame_messages
                continue
            if isinstance(frame_messages, list):
                messages.extend(frame_messages)
    except Exception as e:
        _log(logger, "error", f"读取父级消息失败: {e}")
        return {'success': False, 'text': {}, 'messages': [], 'error': str(e), 'method': '消息捕获'}

    if isinstance(messages_info, dict) and '__error' in messages_info:
        return {'success': False, 'text': {}, 'messages': [], 'error': messages_info.get('__error') or '未知错误', 'method': '消息捕获'}

    messages = messages if isinstance(messages, list) else []

    abstract_data: Optional[Dict[str, Any]] = None
    for entry in messages:
        if not isinstance(entry, dict):
            continue
        data = entry.get('data')
        if not isinstance(data, dict):
            continue
        # Payload shape is { type: 'IFRAME_DONE', data: { abstractData: {...}, ... } }
        candidate = data.get('data') if isinstance(data.get('data'), dict) else data
        abstract = candidate.get('abstractData') if isinstance(candidate, dict) else None
        if isinstance(abstract, dict) and abstract:
            abstract_data = abstract
            break

    success = isinstance(abstract_data, dict) and bool(abstract_data)
    result: Dict[str, Any] = {
        'success': success,
        'text': abstract_data if isinstance(abstract_data, dict) else {},
        'messages': messages,
        'method': '消息捕获',
    }
    if not success:
        result['error'] = '未截获abstractData'
    return result


def _rebuild_text_from_logs(frame, logger=None) -> Optional[Dict[str, Any]]:
    if frame is None:
        return None
    try:
        frame.wait_for_selector("canvas#resume", timeout=5000)
    except Exception:
        pass
    try:
        rebuilt = frame.evaluate(CANVAS_REBUILD_SCRIPT)
        if isinstance(rebuilt, dict) and (rebuilt.get('text') or rebuilt.get('html')):
            return rebuilt
    except Exception as e:
        _log(logger, "error", f"canvas拦截失败: {e}")
    return None


def _install_clipboard_hooks(frame, logger=None) -> bool:
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
        return bool(frame.evaluate(code))
    except Exception as e:
        _log(logger, "error", f"安装剪贴板钩子失败: {e}")
        return False


def _read_clipboard_logs(frame, logger=None) -> Optional[str]:
    if frame is None:
        return None
    try:
        data = frame.evaluate("(function(){ try { return (window.__clipboardWrites||[]).slice(); } catch(e){ return []; } })()")
        if isinstance(data, list) and data:
            # Concatenate unique lines
            texts = []
            seen = set()
            for item in data:
                try:
                    t = str((item or {}).get('text') or '')
                    if t and t not in seen:
                        seen.add(t)
                        texts.append(t)
                except Exception:
                    continue
            if texts:
                return "\n".join(texts)
    except Exception:
        return None
    return None


def _try_trigger_copy_buttons(frame, logger=None) -> None:
    if frame is None:
        return
    # Best-effort: click common copy/export buttons inside the viewer
    selectors = [
        "button:has-text('复制')",
        "a:has-text('复制')",
        "button:has-text('复制简历')",
        "a:has-text('复制简历')",
        "button:has-text('导出')",
        "a:has-text('导出')",
    ]
    for s in selectors:
        try:
            loc = frame.locator(s).first
            if loc and loc.count() > 0:
                try:
                    loc.click()
                    try:
                        frame.wait_for_timeout(300)
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception:
            continue




def collect_resume_debug_info(page, logger=None) -> Dict[str, Any]:
    """Gather diagnostic information about frames/resources involved in resume rendering."""

    info: Dict[str, Any] = {
        'frames': [],
        'resources': [],
    }

    for frame in page.frames:
        frame_info: Dict[str, Any] = {
            'name': frame.name,
            'url': frame.url,
        }
        frame_info['canvasCount'] = frame.locator('canvas').count()
        frame_info['iframeCount'] = frame.locator('iframe').count()
        frame_info['scripts'] = frame.evaluate(
            "() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src)"
        )
        frame_info['resumeStore'] = frame.evaluate(
            "() => { try { return window.__resume_data_store || null; } catch (_) { return 'error'; } }"
        )
        info['frames'].append(frame_info)

    info['resources'] = page.evaluate(
        "() => (performance.getEntriesByType('resource') || [])"
    )

    return info



def _try_canvas_text_hooks(frame, logger=None) -> Dict[str, Any]:
    """Try canvas text hooks method."""
    hooked = _install_canvas_text_hooks(frame, logger)
    if hooked:
        rebuilt = _rebuild_text_from_logs(frame, logger)
    if rebuilt and (rebuilt.get('text') or rebuilt.get('html')):
                return {
                    'success': True,
            'text': rebuilt.get('text'),
            'html': rebuilt.get('html'),
            'method': "Canvas拦截"
        }
    return {'success': False, 'error': 'Canvas拦截失败', 'method': "Canvas拦截"}


def _try_clipboard_hooks(frame, logger=None) -> Dict[str, Any]:
    """Try clipboard hooks method."""
    _install_clipboard_hooks(frame, logger)
    _try_trigger_copy_buttons(frame, logger)
    clip_text = _read_clipboard_logs(frame, logger)
    if clip_text:
        return {
            'success': True,
            'text': clip_text,
    'method': '剪贴板拦截'
    }
    return {'success': False, 'error': '剪贴板拦截失败', 'method': '剪贴板拦截'}


def _process_resume_entry(page, context_info: Dict[str, Any], logger=None) -> Dict[str, Any]:
    mode = context_info.get('mode')
    frame = context_info.get('frame')

    if mode == 'inline':
        inline_data = _capture_inline_resume(
            frame or page,
            logger,
            max_attempts=5,
        )
        if inline_data:
            rect = inline_data.get('boundingRect') or {}
            text = inline_data.get('formattedText') or inline_data.get('text')
            html = inline_data.get('htmlSnippet') or inline_data.get('html')
            return {
                'success': True,
                'text': text,
                'textLenth': len(text),
                'htmlLenth': len(html),
                'width': int(rect.get('width') or 0),
                'height': int(rect.get('height') or 0),
                'details': "来自inline简历",
            }
        else:
            entry = context_info.get('entry')
            text = entry.inner_text()
            html = entry.inner_html()
            return {
                'success': True,
                'text': text,
                'textLenth': len(text),
                'htmlLenth': len(html),
                'details': "来自inner_text简历",
            }

    if mode == 'iframe' and frame:
        parent_result = _collect_parent_messages(page, logger)
        wasm_result = _try_wasm_exports(frame, logger)
        canvas_result = _try_canvas_text_hooks(frame, logger)
        hooks_result = _try_clipboard_hooks(frame, logger)

        results = [res for res in [parent_result, wasm_result, canvas_result, hooks_result] if isinstance(res, dict)]

        success = any(result.get('success') for result in results)
        methods = [result.get('method') for result in results]

        aggregated_text: Dict[str, Any] = {}
        for result in results:
            payload = result.get('text')
            if isinstance(payload, dict):
                aggregated_text.update(payload)
            elif isinstance(payload, str) and payload:
                aggregated_text[result.get('method', '文本')] = payload

        error = '\n'.join(filter(None, [result.get('error', '') for result in results]))
        if not isinstance(result, dict):
            debug_info = collect_resume_debug_info(frame)
            return {
                'success': False,
                'details': '未知错误: 简历结果异常',
                'debug': debug_info,
            }
        return {
            'success': success,
            'text': aggregated_text,
            'capture_method': methods,
            'error': error
        }


def extract_pdf_viewer_text(frame: 'Frame') -> Dict[str, Any]:
    """Return structured text extracted from a pdf.js viewer iframe."""

    try:
        frame.locator("div.textLayer").first.wait_for(state="visible", timeout=5000)
    except Exception:
        pass

    def _collect() -> Any:
        script = dedent(
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
        return {
                      text: item.str,
                      x,
                      y,
                      height,
                      width,
                    };
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
                    .replace(/\s+/g, ' ')
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
        ).strip()
        return frame.evaluate(script)

    try:
        pages: Any = _collect()
    except Exception:
        pages = []
        fallback = frame.evaluate("() => document.body.innerText || ''")
        fallback = clean_resume_text(fallback)
        return {'pages': [], 'text': fallback}

    if isinstance(pages, dict):
        if '__error' in pages:
            pages = []
        else:
            pages = [pages]

    combined: list[str] = []
    for page_data in pages:
        for line in page_data.get('lines', []) or []:
            if line:
                combined.append(line)


    cleaned_text = clean_resume_text('\n'.join(combined))
    return {'pages': pages, 'text': cleaned_text}


def clean_resume_text(text: str) -> str:
    # Replace triple or more newlines with a unique marker to preserve them
    text = re.sub(r'\n{3,}', '<TRIPLE_NL>', text)
    # Replace double newlines and single newlines with nothing (collapse)
    text = re.sub(r'\n{2,}', '', text)
    text = re.sub(r'\n\s\n', '', text)
    text = re.sub(r'\n', '', text)
    # Restore triple newlines
    text = text.replace('<TRIPLE_NL>', '\n\n')
    return text
