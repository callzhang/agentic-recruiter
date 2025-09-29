import asyncio, random, time, re, csv, json, os
from typing import Dict, Any, List, Optional, Tuple
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from .config import click_delay_range_ms, settings

def human_delay():
    lo, hi = click_delay_range_ms()
    time.sleep(random.uniform(lo/1000, hi/1000))

def try_click(page: Page, selectors: List[str], timeout_ms: int = 2500) -> bool:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout_ms)
            el.click()
            human_delay()
            return True
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return False

def try_exists(page: Page, selectors: List[str], timeout_ms: int = 2000) -> bool:
    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False

def detect_and_pause_for_captcha(page: Page) -> bool:
    # Single selector for captcha iframes
    captcha_selectors = [
        "iframe[src*='geetest']",
        "iframe[src*='captcha']",
        "iframe[id*='captcha']"
    ]
    try:
        if try_exists(page, captcha_selectors, timeout_ms=1000):
            print("[!] 可能出现验证码，请在浏览器中完成验证后，回到终端按回车继续...")
            input()
            return True
    except Exception:
        pass
    return False

def safe_inner_text(page: Page, selector: str, default: str = "") -> str:
    try:
        return page.locator(selector).first.inner_text(timeout=2000).strip()
    except Exception:
        return default

def export_records(records: List[Dict[str, Any]], prefix: str) -> Tuple[str, str]:
    ts = time.strftime("%Y%m%d_%H%M")
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(settings.OUTPUT_DIR, f"{prefix}_{ts}.jsonl")
    csv_path = os.path.join(settings.OUTPUT_DIR, f"{prefix}_{ts}.csv")
    with open(json_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if records:
        keys = sorted({k for r in records for k in r.keys()})
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in records:
                w.writerow(r)
    return json_path, csv_path

def extract_resume_blocks(page: Page) -> Dict[str, str]:
    # 兜底：通过标题定位块，然后抓取相邻容器文本
    resume_sections = ["基本信息", "工作经历", "教育经历", "项目经历", "技能特长", "自我评价"]
    result = {}
    for title in resume_sections:
        try:
            h = page.get_by_text(title, exact=True).first
            # 往上找卡片容器，再取文本
            container = h.locator("xpath=ancestor::*[self::section or self::div][1]")
            text = container.inner_text(timeout=1500).strip()
            result[title] = re.sub(r"\n{2,}", "\n", text)
        except Exception:
            continue
    # 兜底：页面整体提取
    if not result:
        try:
            body_txt = page.locator("body").inner_text(timeout=2000)
            result["全文"] = re.sub(r"\n{2,}", "\n", body_txt)
        except Exception:
            pass
    return result
