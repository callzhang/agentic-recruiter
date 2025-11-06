#!/usr/bin/env python3
"""
启动Boss直聘后台服务
"""
import argparse
import subprocess
import sys
import os
import time
import signal
import threading
from typing import Any, Dict, Optional
import requests
from src.global_logger import logger

def install_dependencies():
    """安装依赖"""
    print("[*] 检查并安装依赖...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("[+] 依赖安装完成")
    except subprocess.CalledProcessError as e:
        print(f"[!] 依赖安装失败: {e}")
        return False
    return True

def free_port(port: str):
    """释放占用端口的进程 - 只清理我们自己的服务进程"""
    try:
        # 验证端口号
        port_num = int(port)
        if not (1 <= port_num <= 65535):
            print(f"[!] 无效端口号: {port}")
            return
    except ValueError:
        print(f"[!] 端口号必须是数字: {port}")
        return
    
    try:
        if sys.platform == "win32":
            # Windows: 只清理uvicorn和boss_service相关进程
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True
            )
            for line in result.stdout.split('\n'):
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if len(parts) > 4:
                        pid = parts[-1]
                        # 检查进程是否是我们自己的服务
                        try:
                            tasklist_result = subprocess.run(
                                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                                capture_output=True, text=True
                            )
                            if "uvicorn" in tasklist_result.stdout or "python" in tasklist_result.stdout:
                                subprocess.run(["taskkill", "/F", "/PID", pid], 
                                             capture_output=True)
                                print(f'[+] 清理了端口 {port} 上的服务进程')
                        except Exception:
                            pass
        else:
            # Unix-like systems: 只清理uvicorn和boss_service相关进程
            try:
                pids = subprocess.check_output(["lsof", "-ti", f":{port}"]).decode().strip().splitlines()
                if pids and pids[0]:
                    for pid in pids:
                        if pid:
                            try:
                                # 检查进程是否是我们自己的服务
                                ps_result = subprocess.run(
                                    ["ps", "-p", pid, "-o", "comm="],
                                    capture_output=True, text=True
                                )
                                if "uvicorn" in ps_result.stdout or "python" in ps_result.stdout:
                                    os.kill(int(pid), signal.SIGTERM)
                                    time.sleep(1)
                                    os.kill(int(pid), signal.SIGKILL)
                                    print(f'[+] 清理了端口 {port} 上的服务进程')
                                else:
                                    print(f'[!] 端口 {port} 被其他进程占用，跳过清理')
                            except Exception:
                                pass
                    print(f'[+] 端口 {port} 检查完成')
                else:
                    print(f'[+] 端口 {port} 可用')
            except subprocess.CalledProcessError:
                print(f'[+] 端口 {port} 可用')
    except Exception as e:
        print(f"[!] 检查端口失败: {e}")

def is_chrome_running(cdp_port: str) -> bool:
    """检查Chrome是否已经在运行"""
    try:
        import requests
        response = requests.get(f"http://localhost:{cdp_port}/json/version", timeout=2)
        return response.status_code == 200
    except Exception:
        return False

def kill_existing_chrome(user_data: str):
    """杀死现有的Chrome进程（基于user-data-dir）"""
    try:
        if sys.platform == "win32":
            # Windows: 使用tasklist和taskkill
            result = subprocess.run(
                ["tasklist", "/FI", f"WINDOWTITLE eq *Chrome*", "/FO", "CSV"],
                capture_output=True, text=True
            )
            if result.returncode == 0 and "chrome.exe" in result.stdout:
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], 
                             capture_output=True)
                print(f"[*] 已清理现有Chrome进程")
        else:
            # Unix-like systems: 使用pgrep
            result = subprocess.run(
                ["pgrep", "-f", f"--user-data-dir={user_data}"],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                            time.sleep(0.5)
                            os.kill(int(pid), signal.SIGKILL)
                        except Exception:
                            pass
                print(f"[*] 已清理现有Chrome进程")
    except Exception:
        pass


def _wait_for_service_ready(base_url: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/status", timeout=5)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_scheduler_payload(base_url: str, options: Dict[str, Any]) -> Dict[str, Any]:
    opts = dict(options)
    criteria_path = opts.get('criteria_path', 'config/jobs.yaml')
    payload: Dict[str, Any] = {
        'base_url': base_url,
        'criteria_path': os.path.abspath(criteria_path),
        'role_id': opts.get('role_id', 'default'),
        'poll_interval': _coerce_int(opts.get('poll_interval', 120), 120),
        'recommend_interval': _coerce_int(opts.get('recommend_interval', 600), 600),
        'followup_interval': _coerce_int(opts.get('followup_interval', 3600), 3600),
        'report_interval': _coerce_int(opts.get('report_interval', 604800), 604800),
        'inbound_limit': _coerce_int(opts.get('inbound_limit', 40), 40),
        'recommend_limit': _coerce_int(opts.get('recommend_limit', 20), 20),
    }
    greeting_template = opts.get('greeting_template')
    if greeting_template:
        payload['greeting_template'] = greeting_template
    return payload

def start_service(*, scheduler_options: Optional[Dict[str, Any]] | None = None):
    """启动服务"""
    print("[*] 启动Boss直聘后台服务...")
    scheduler_config = dict(scheduler_options or {})
    scheduler_started = False
    
    # 安装依赖
    # if not install_dependencies():
    #     return False
    
    # 启动服务
    try:
        env = os.environ.copy()
        env['BOSS_SERVICE_RUNNING'] = 'true'
        host = env.get('BOSS_SERVICE_HOST', '127.0.0.1')
        port = env.get('BOSS_SERVICE_PORT', '5001')
        cdp_port = env.get('CDP_PORT', '9222')
        user_data = env.get('BOSSZP_USER_DATA', '/tmp/bosszhipin_profile')
        force_cleanup = env.get('FORCE_CLEANUP_PORT', 'true').lower() == 'true'
        base_url = scheduler_config.pop('base_url', None) or f"http://{host}:{port}"
        env['BOSS_SERVICE_BASE_URL'] = base_url


        # 检查端口是否被占用
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', int(port)))
            sock.close()
            if result == 0:
                print(f"[!] 端口 {port} 已被占用")
                print(f"[*] 如果这是您的主服务，请使用不同的端口:")
                if force_cleanup:
                    free_port(port)
                    # 启动前释放端口（只清理我们自己的服务）
                    # 确保不存在残留的 uvicorn 进程（例如上一次reloader未退出干净）
                    try:
                        subprocess.run(["pkill", "-f", "uvicorn.*boss_service:app"], check=False)
                        time.sleep(0.5)
                    except Exception:
                        pass
                else:
                    return False
        except Exception:
            pass
        


        # 检查Chrome是否已经在运行
        if is_chrome_running(cdp_port):
            print(f"[*] Chrome已在端口 {cdp_port} 运行，跳过启动")
        else:
            print(f"[*] 启动Chrome (CDP端口: {cdp_port})...")
            # 清理可能存在的旧Chrome进程
            kill_existing_chrome(user_data)
            
            # 启动独立的 Chrome (CDP)，确保浏览器长驻，与 API 进程解耦
            # 检测Chrome路径
            if sys.platform == "darwin":
                chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            elif sys.platform == "win32":
                chrome_path = "chrome.exe"  # 假设Chrome在PATH中
            else:
                chrome_path = "google-chrome"  # Linux
            
            # Get BASE_URL from config for app mode
            from src.config import settings
            chat_url = settings.CHAT_URL or "about:blank"
            
            chrome_cmd = [
                chrome_path,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--disable-features=VizDisplayCompositor",
                "--window-size=1200,800",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                # Launch in app mode - creates dedicated window without address bar
                # This makes it clear the browser is for automation only
                f"--app={chat_url}"
            ]
            try:
                subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                time.sleep(2.0)  # 增加等待时间确保Chrome完全启动
                print(f"[+] Chrome启动完成")
            except Exception as e:
                print(f"[!] Chrome启动失败: {e}")
                return False

        # 使用 uvicorn 启动（可开启 --reload；CDP模式下重载不会中断浏览器）
        # 直接使用 Python API 以支持 reload_excludes (uvicorn 0.21.0+)
        print("[+] 服务启动成功!")
        print(f"[*] 服务地址: http://{host}:{port}")
        print("[*] 按 Ctrl+C 停止服务")
        
        # Start uvicorn in a thread so we can open browser after it's ready
        service_url = f"http://{host}:{port}"
        import uvicorn
        
        def open_browser_after_ready():
            """Open browser after service is ready."""
            if _wait_for_service_ready(service_url, timeout=15):
                try:
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", service_url])
                    elif sys.platform == "win32":
                        subprocess.Popen(["start", service_url], shell=True)
                    else:
                        subprocess.Popen(["xdg-open", service_url])
                    
                    logger.info(f"[+] 已在浏览器中打开: {service_url}")
                except Exception as e:
                    logger.error(f"[!] 无法自动打开浏览器: {e}")
                    logger.info(f"[*] 请手动访问本地 URL: {service_url}")
            else:
                print(f"[!] 服务启动超时")
                print(f"[*] 请手动访问本地 URL: {service_url}")
        
        # Start browser opener in background thread
        browser_thread = threading.Thread(target=open_browser_after_ready, daemon=True)
        browser_thread.start()
        
        # Start uvicorn directly with reload_excludes
        # Only watch src/ directory + boss_service.py, exclude everything else
        # Note: uvicorn.run() blocks here until server stops (Ctrl+C or error)
        uvicorn.run(
            "boss_service:app",
            host=host,
            port=int(port),
            reload=True,
            reload_dirs=["src", "web/routes/"],  # Only watch src/ directory
            reload_includes=["boss_service.py"],  # Also watch boss_service.py specifically
            reload_excludes=[
                "pages/**",
                "scripts/**", 
                "test/**",
                "config/**",
                "data/**",
                "docs/**",
                "examples/**",
                "wasm/**",
                "web/templates/**",  # Exclude web UI files to prevent unnecessary reloads
                "streamlit_shared.py",
                "boss_app.py",
                "start_service.py",
                "*.ipynb",
                "*.md",
                "__pycache__/**"
            ],
            reload_delay=5.0  # Increased from 3.0 to reduce rapid reload cycles
        )
        
        # Cleanup after uvicorn stops gracefully (e.g., Ctrl+C)
        print("\n[*] 正在停止服务...")
        if scheduler_started:
            try:
                requests.post(f"{base_url}/automation/scheduler/stop", timeout=10)
            except Exception:
                pass
        
        # 可选：清理Chrome进程（通常保留以便下次使用）
        cleanup_chrome = os.environ.get('CLEANUP_CHROME_ON_EXIT', 'false').lower() == 'true'
        # if cleanup_chrome:
        #     print("[*] 清理Chrome进程...")
        #     kill_existing_chrome(user_data)
        
        print("[+] 服务已停止")
        
    except KeyboardInterrupt:
        print("\n[*] 正在停止服务...")
        if scheduler_started:
            try:
                requests.post(f"{base_url}/automation/scheduler/stop", timeout=10)
            except Exception:
                pass
        print("[+] 服务已停止")
    except Exception as e:
        print(f"[!] 启动服务失败: {e}")
        if scheduler_started:
            try:
                requests.post(f"{base_url}/automation/scheduler/stop", timeout=10)
            except Exception:
                pass
        return False
    
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Boss直聘自动化服务")
    subparsers = parser.add_subparsers(dest="command")
    parser.set_defaults(command="start")

    subparsers.add_parser("start", help="仅启动API服务")

    schedule_parser = subparsers.add_parser("schedule", help="启动API服务并运行BRD调度")
    schedule_parser.add_argument("--base-url", help="FastAPI服务地址，默认基于HOST/PORT推断")

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    start_service()


if __name__ == "__main__":
    main()
