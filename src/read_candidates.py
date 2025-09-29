import argparse, time, re, random
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
# Single selectors (replace with actual selectors as needed)
nav_message_candidates = ["text=消息", "text=沟通", "a:has-text('消息')", "a:has-text('沟通')"]
filter_greeting_candidates = ["text=打招呼", "button:has-text('打招呼')"]
conversation_list_items = ["xpath=//li[contains(@class, 'conversation') or contains(@class, 'chat') or contains(@class, 'item')]"]
open_resume_actions = ["text=查看简历", "a:has-text('简历')", "button:has-text('简历')"]
from src.utils import human_delay, try_click, try_exists, detect_and_pause_for_captcha, extract_resume_blocks, export_records

def open_messages_and_filter_greetings(page) -> None:
    # 进入“消息/沟通”并点击“打招呼”筛选（若有）
    if not try_click(page, nav_message_candidates, timeout_ms=2500):
        page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded")
    detect_and_pause_for_captcha(page)
    try_click(page, filter_greeting_candidates, timeout_ms=1500)  # 若无该入口会忽略

def iter_conversations(page, limit: int) -> List[Any]:
    # 获取左侧会话条目
    items = []
    for sel in conversation_list_items:
        try:
            loc = page.locator(sel)
            count = loc.count()
            if count > 0:
                for i in range(min(count, limit)):
                    items.append(loc.nth(i))
                break
        except Exception:
            continue
    return items

def open_resume(page) -> bool:
    # 在会话里尝试打开“查看简历”
    if try_click(page, open_resume_actions, timeout_ms=1200):
        return True
    # 兜底：查找包含“简历”的链接/按钮
    try:
        link = page.get_by_text("简历").first
        link.click(timeout=1000)
        human_delay()
        return True
    except Exception:
        return False

def scrape_one(page, idx: int) -> Dict[str, Any]:
    record: Dict[str, Any] = {"index": idx, "ts": int(time.time())}
    # 尝试从当前右侧候选人卡片读取基本字段
    # 这些选择器需要按实际页面调整
    candidates = [
        ("name", "xpath=(//div[contains(@class,'name')])[1]"),
        ("age",  "xpath=(//span[contains(., '岁')])[1]"),
        ("edu",  "xpath=//span[contains(., '本科') or contains(., '硕士') or contains(., '大专')][1]"),
        ("exp",  "xpath=//span[contains(., '年') and contains(., '经验')][1]"),
        ("title","xpath=(//div[contains(@class,'title') or contains(@class,'job')])[1]"),
        ("city", "xpath=//span[contains(., '市') or contains(., '区')][1]"),
    ]
    for key, sel in candidates:
        try:
            record[key] = page.locator(sel).inner_text(timeout=800).strip()
        except Exception:
            pass

    # 打开简历抽屉/新页并抓取块文本
    opened = open_resume(page)
    if opened:
        detect_and_pause_for_captcha(page)
        time.sleep(1.2)
        blocks = extract_resume_blocks(page)
        record.update({f"section_{k}": v for k, v in blocks.items()})
    else:
        record["note"] = "未找到查看简历按钮，保留会话侧信息"
    return record

def check_login_status(page):
    """检查登录状态"""
    try:
        page_text = page.locator("body").inner_text()
        
        # 检查是否有登录按钮（如果有说明未登录）
        if "登录" in page_text and "立即登录" in page_text:
            return False
        
        # 检查是否有用户相关元素
        user_indicators = ["我的", "个人中心", "企业中心", "招聘管理", "消息", "沟通"]
        for indicator in user_indicators:
            if indicator in page_text:
                return True
        
        # 检查是否有候选人相关内容
        candidate_indicators = ["候选人", "简历", "打招呼", "投递", "面试", "聊天"]
        for indicator in candidate_indicators:
            if indicator in page_text:
                return True
        
        return len(page_text) > 100  # 如果页面内容足够丰富，可能已登录
        
    except Exception as e:
        print(f"[!] 检查登录状态时出错: {e}")
        return False

def wait_for_page_ready(page, max_wait_time=30):
    """等待页面完全加载"""
    print("[*] 等待页面完全加载...")
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            page_text = page.locator("body").inner_text()
            
            # 检查是否有加载中的提示
            if "加载中" in page_text or "请稍候" in page_text:
                print("[*] 页面仍在加载中...")
                time.sleep(2)
                continue
            
            # 检查是否有错误信息
            if "错误" in page_text or "404" in page_text:
                print("[!] 页面显示错误信息")
                return False
            
            # 页面内容足够丰富，认为加载完成
            if len(page_text) > 50:
                print("[+] 页面加载完成")
                return True
            
            time.sleep(2)
            
        except Exception as e:
            print(f"[!] 检查页面状态时出错: {e}")
            time.sleep(2)
    
    print("[!] 等待页面加载超时")
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="最多读取多少个候选人")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.HEADLESS, slow_mo=settings.SLOWMO_MS)
        context = browser.new_context(storage_state=settings.STORAGE_STATE)
        page = context.new_page()
        
        print("[*] 访问消息页面...")
        page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded")
        
        # 等待页面完全加载
        if not wait_for_page_ready(page):
            print("[!] 页面加载失败，退出")
            browser.close()
            return
        
        # 检查登录状态
        if not check_login_status(page):
            print("[!] 登录状态失效，请重新登录")
            print("[*] 运行命令: python improved_login.py")
            browser.close()
            return
        
        print("[+] 登录状态正常，开始读取候选人...")
        open_messages_and_filter_greetings(page)

        items = iter_conversations(page, args.limit)
        print(f"[*] 发现候选会话 {len(items)} 条（将按顺序打开）")
        records: List[Dict[str, Any]] = []

        for i, item in enumerate(items, 1):
            try:
                item.scroll_into_view_if_needed(timeout=1500)
                item.click()
                human_delay()
                detect_and_pause_for_captcha(page)
                rec = scrape_one(page, i)
                records.append(rec)
                # 尝试返回上一层（若简历在新页/抽屉）
                try:
                    page.go_back(timeout=1000)
                except Exception:
                    pass
                # 人类节奏
                time.sleep(random.uniform(1.0, 2.2))
            except PlaywrightTimeoutError:
                continue
            except Exception as e:
                print(f"[!] 第 {i} 条处理失败：{e}")
                continue

        json_path, csv_path = export_records(records, prefix="candidates")
        print(f"[+] 导出：{json_path}\n[+] 导出：{csv_path}")
        browser.close()

if __name__ == "__main__":
    main()
