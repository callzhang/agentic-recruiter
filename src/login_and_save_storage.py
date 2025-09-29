from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
# Single selector for navigation to messages
nav_message_candidates = ["text=消息", "text=沟通", "a:has-text('消息')", "a:has-text('沟通')"]
from src.utils import try_exists, detect_and_pause_for_captcha
import json, time

def wait_until_logged_in(page) -> None:
    print("[*] 等待登录完成...")
    print("[*] 请在浏览器中完成登录操作（扫码或输入密码）")
    
    for attempt in range(60):  # 最多约60*3=180秒
        url = page.url
        print(f"[*] 当前页面: {url}")
        
        # 检查是否在登录页面
        if "login" in url or "signin" in url:
            print("[*] 检测到登录页面，请完成登录...")
            detect_and_pause_for_captcha(page)
            time.sleep(3)
            continue
            
        # 检查是否跳转到首页或其他页面
        if url == settings.BASE_URL or url == settings.BASE_URL + "/" or "zhipin.com" in url:
            print("[*] 已跳转到主站，检查登录状态...")
            
            # 尝试访问需要登录的页面来验证登录状态
            try:
                page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded", timeout=10000)
                time.sleep(2)
                
                # 检查是否能找到消息/沟通入口
                if try_exists(page, nav_message_candidates, 2000):
                    print("[+] 登录成功！检测到消息/沟通入口")
                    return
                else:
                    print("[*] 未找到消息入口，可能还未完全登录，继续等待...")
                    
            except Exception as e:
                print(f"[*] 访问消息页面失败: {e}")
                
        detect_and_pause_for_captcha(page)
        time.sleep(3)
    
    print("[!] 自动检测登录状态超时")
    print("[*] 请确认您已经完成登录，然后按回车继续...")
    print("[*] 如果还未登录，请按 Ctrl+C 退出，完成登录后重新运行")
    try:
        input("按回车继续...")
    except EOFError:
        print("[*] 非交互环境，继续执行...")

def main():
    os.makedirs(os.path.dirname(settings.STORAGE_STATE), exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.HEADLESS, slow_mo=settings.SLOWMO_MS)
        context = browser.new_context()
        page = context.new_page()
        
        print(f"[*] 启动浏览器，访问: {settings.BASE_URL}")
        # 先访问首页，让用户有机会登录
        page.goto(settings.BASE_URL, wait_until="load")
        print("[*] 浏览器已打开，请完成登录操作")
        
        wait_until_logged_in(page)
        
        # 最终验证：确保能访问消息页面
        print("[*] 进行最终登录状态验证...")
        try:
            page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            
            # 检查页面标题和内容
            title = page.title()
            print(f"[*] 当前页面标题: {title}")
            
            # 尝试点击消息入口
            message_clicked = False
            for sel in nav_message_candidates:
                try:
                    if page.locator(sel).first.is_visible(timeout=2000):
                        page.locator(sel).first.click(timeout=2000)
                        print("[+] 成功点击消息/沟通入口")
                        message_clicked = True
                        break
                except Exception:
                    continue
            
            if not message_clicked:
                print("[!] 警告：无法点击消息入口，登录状态可能不完整")
                print("[*] 请确认您已经完成登录，然后按回车继续...")
                try:
                    input("按回车继续...")
                except EOFError:
                    print("[*] 非交互环境，继续执行...")
            
        except Exception as e:
            print(f"[!] 验证登录状态时出错: {e}")
            print("[*] 请确认您已经完成登录，然后按回车继续...")
            try:
                input("按回车继续...")
            except EOFError:
                print("[*] 非交互环境，继续执行...")
        
        # 保存登录状态
        context.storage_state(path=settings.STORAGE_STATE)
        print(f"[+] 已保存登录状态到 {settings.STORAGE_STATE}")
        print("[*] 登录状态保存完成，可以关闭浏览器")
        
        # 保持浏览器打开一段时间，让用户确认
        print("[*] 浏览器将在10秒后自动关闭...")
        time.sleep(10)
        browser.close()

if __name__ == "__main__":
    main()
