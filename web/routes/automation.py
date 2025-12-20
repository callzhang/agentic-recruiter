"""Automation workflow routes with SSE for web UI."""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src import assistant_actions
from src.config import get_service_config
from src.global_logger import get_logger
from src.scheduler import BRDWorkScheduler

logger = get_logger()

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

# Global scheduler instance (singleton pattern)
_scheduler: Optional[BRDWorkScheduler] = None
_event_queue: Optional[asyncio.Queue] = None
# =========================================================================
# On-demand Cloudflare Tunnel Controls
# =========================================================================
_tunnel_url: Optional[str] = None
_tunnel_process: Optional[asyncio.subprocess.Process] = None
_tunnel_drain_tasks: list[asyncio.Task] = []

def _is_executable_available(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None

@router.get("/tunnel-url", response_class=JSONResponse)
async def get_tunnel_url() -> JSONResponse:
    return JSONResponse({"tunnel_url": _tunnel_url})

@router.post("/tunnel/start", response_class=JSONResponse)
async def start_tunnel(request: Request) -> JSONResponse:
    global _tunnel_url, _tunnel_process
    # Check if tunnel is already running
    if _tunnel_process:
        # Check if process is still alive
        if _tunnel_process.returncode is None:
            if _tunnel_url:
                return JSONResponse({"success": True, "tunnel_url": _tunnel_url})
        else:
            # Process died, reset it
            _tunnel_process = None
            _tunnel_url = None
    if not _is_executable_available("cloudflared"):
        return JSONResponse(status_code=400, content={"success": False, "error": "cloudflared not installed"})
    # Determine port from service base URL
    service_config = get_service_config()
    base_url = service_config.get("base_url") or "http://127.0.0.1:5001"
    try:
        port = int(base_url.rsplit(":", 1)[-1])
    except Exception:
        port = 5001

    # Start cloudflared
    try:
        _tunnel_process = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Parse URL from stderr lines
        url_pattern = r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"

        async def _drain_pipe(pipe, log_prefix: str):
            """Continuously drain a pipe until EOF or process exits."""
            if not pipe:
                return
            try:
                while True:
                    line = await pipe.readline()
                    if not line:
                        break
                    try:
                        text = line.decode("utf-8", errors="ignore").strip()
                        if text:
                            logger.debug(f"{log_prefix}: {text}")
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"{log_prefix}: Error draining pipe: {e}")

        async def _read_stderr_for_url():
            """Read stderr to extract tunnel URL, then continue draining."""
            global _tunnel_url
            assert _tunnel_process and _tunnel_process.stderr
            url_found = False
            while True:
                line = await _tunnel_process.stderr.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="ignore")
                except Exception:
                    text = str(line)
                if not url_found:
                    m = re.search(url_pattern, text)
                    if m:
                        _tunnel_url = m.group(0)
                        logger.info(f"Cloudflare tunnel URL detected: {_tunnel_url}")
                        url_found = True
                # Continue draining after URL is found
                if text.strip():
                    logger.debug(f"cloudflared[stderr]: {text.strip()}")

        # Spawn background tasks to drain both pipes continuously
        global _tunnel_drain_tasks
        # Cancel any existing drain tasks
        for task in _tunnel_drain_tasks:
            if not task.done():
                task.cancel()
        _tunnel_drain_tasks = []
        
        # Task to read stderr for URL (will continue draining after finding URL)
        if _tunnel_process.stderr:
            stderr_task = asyncio.create_task(_read_stderr_for_url())
            _tunnel_drain_tasks.append(stderr_task)
        
        # Task to drain stdout
        if _tunnel_process.stdout:
            stdout_task = asyncio.create_task(_drain_pipe(_tunnel_process.stdout, "cloudflared[stdout]"))
            _tunnel_drain_tasks.append(stdout_task)
        
        # Wait a short time for URL to be detected
        try:
            await asyncio.wait_for(stderr_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Tunnel URL not detected within 5 seconds, but tunnel may still be starting")

        return JSONResponse({"success": True, "tunnel_url": _tunnel_url})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@router.post("/tunnel/stop", response_class=JSONResponse)
async def stop_tunnel() -> JSONResponse:
    global _tunnel_process, _tunnel_url, _tunnel_drain_tasks
    if _tunnel_process:
        try:
            # Cancel drain tasks
            for task in _tunnel_drain_tasks:
                if not task.done():
                    task.cancel()
            _tunnel_drain_tasks = []
            
            _tunnel_process.terminate()
            try:
                await asyncio.wait_for(_tunnel_process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                _tunnel_process.kill()
        except Exception:
            pass
        finally:
            _tunnel_process = None
            _tunnel_url = None
            _tunnel_drain_tasks = []
    return JSONResponse({"success": True})


# ============================================================================
# Helper functions
# ============================================================================

def get_scheduler() -> Optional[BRDWorkScheduler]:
    """Get the current scheduler instance."""
    global _scheduler
    return _scheduler


def get_event_queue() -> asyncio.Queue:
    """Get or create the global event queue for SSE."""
    global _event_queue
    if _event_queue is None:
        _event_queue = asyncio.Queue()
    return _event_queue


async def emit_event(message: str, level: str = "info"):
    """Emit an event to the SSE stream."""
    queue = get_event_queue()
    await queue.put({
        "timestamp": datetime.now().isoformat(),
        "message": message,
        "level": level
    })


# ============================================================================
# Main page
# ============================================================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def automation_page(request: Request):
    """Main automation page."""
    # Get tunnel URL from environment
    import os
    tunnel_url = os.environ.get('BOSS_TUNNEL_URL')
    service_config = get_service_config()
    local_url = service_config.get("base_url") or f"http://127.0.0.1:5001"
    
    return templates.TemplateResponse("automation.html", {
        "request": request,
        "tunnel_url": tunnel_url,
        "local_url": local_url
    })


# ============================================================================
# SSE stream endpoint
# ============================================================================

@router.get("/stream")
async def automation_stream(request: Request):
    """Server-Sent Events stream for real-time automation updates."""
    async def event_generator():
        queue = get_event_queue()
        
        # Send initial connection message
        yield f"data: {json.dumps({'timestamp': datetime.now().isoformat(), 'message': 'SSE 连接已建立', 'level': 'info'})}\n\n"
        
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break
            
            try:
                # Wait for next event with timeout
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield f": heartbeat\n\n"
                continue
            except Exception as e:
                print(f"SSE error: {e}")
                break
        
        # Cleanup on disconnect
        print("SSE client disconnected")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


# ============================================================================
# Control endpoints
# ============================================================================

@router.post("/start")
async def start_automation(
    enable_recommend: bool = Form(False),
    enable_new_chats: bool = Form(False),
    enable_active_chats: bool = Form(False),
    enable_followups: bool = Form(False),
    job_id: str = Form(...),
    assistant_id: str = Form(...),
    threshold_borderline: float = Form(7.0),
    threshold_seek: float = Form(9.0),
    limit: int = Form(20),
):
    """Start the automation workflow."""
    global _scheduler
    
    # Check if scheduler is already running
    if _scheduler and _scheduler._running:
        return JSONResponse({
            "success": False,
            "error": "工作流已在运行中"
        })
    
    # Validate at least one workflow is enabled
    if not any([enable_recommend, enable_new_chats, enable_active_chats, enable_followups]):
        return JSONResponse({
            "success": False,
            "error": "请至少选择一个工作流"
        })

    if not job_id or job_id in {"加载中...", "无岗位"}:
        return JSONResponse({
            "success": False,
            "error": "请选择有效的岗位"
        })

    if not assistant_id or assistant_id in {"加载中...", "无助手"}:
        return JSONResponse({
            "success": False,
            "error": "请选择有效的助手"
        })
    
    # Load job configuration
    try:
        jobs = load_jobs()
    except ValueError as exc:
        return JSONResponse({
            "success": False,
            "error": str(exc)
        })

    if not jobs:
        return JSONResponse({
            "success": False,
            "error": "未找到任何岗位配置，请先在「岗位画像」中创建岗位"
        })

    job = next(
        (
            j
            for j in jobs
            if str(j.get("id")) == job_id or j.get("position") == job_id
        ),
        None,
    )

    if not job:
        return JSONResponse({
            "success": False,
            "error": f"未找到岗位: {job_id}"
        })
    
    # Create scheduler with configuration
    try:
        await emit_event(f"🚀 启动工作流: {job.get('position', '未知岗位')}", "info")
        await emit_event(f"配置: borderline={threshold_borderline}, seek={threshold_seek}, limit={limit}", "info")

        # Clear existing events to avoid replaying stale logs
        queue = get_event_queue()
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        _scheduler = BRDWorkScheduler(
            job=job,
            recommend_limit=limit,
            enable_recommend=enable_recommend,
            enable_chat_processing=enable_new_chats or enable_active_chats,
            enable_followup=enable_followups,
            assistant=assistant_actions,
            overall_threshold=threshold_seek,
            threshold_greet=threshold_borderline,
            threshold_borderline=threshold_borderline,
            base_url=get_service_config().get("base_url"),
        )
        
        # Inject event emitter into scheduler
        _scheduler.emit_event = emit_event
        _scheduler.attach_event_loop(asyncio.get_running_loop())
        
        # Start scheduler
        _scheduler.start()
        
        await emit_event("✅ 工作流已启动", "success")
        
        return JSONResponse({"success": True})
    
    except Exception as e:
        await emit_event(f"❌ 启动失败: {str(e)}", "error")
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@router.post("/pause")
async def pause_automation():
    """Pause the running automation."""
    scheduler = get_scheduler()
    
    if not scheduler or not scheduler._running:
        return JSONResponse({
            "success": False,
            "error": "工作流未运行"
        })
    
    try:
        scheduler.pause()
        await emit_event("⏸️ 工作流已暂停", "warning")
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@router.post("/next")
async def next_step():
    """Process next candidate (step mode)."""
    scheduler = get_scheduler()
    
    if not scheduler or not scheduler._running:
        return JSONResponse({
            "success": False,
            "error": "工作流未运行"
        })
    
    try:
        scheduler.resume()
        await emit_event("⏭️ 处理下一个候选人...", "info")
        # In step mode, scheduler will pause after processing one candidate
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@router.post("/stop")
async def stop_automation():
    """Stop the running automation."""
    global _scheduler
    
    scheduler = get_scheduler()
    
    if not scheduler or not scheduler._running:
        return JSONResponse({
            "success": False,
            "error": "工作流未运行"
        })
    
    try:
        scheduler.stop()
        await emit_event("⏹️ 工作流已停止", "warning")
        _scheduler = None
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@router.get("/status")
async def get_status():
    """Get current automation status."""
    scheduler = get_scheduler()
    
    if not scheduler:
        return JSONResponse({
            "running": False,
            "status": "未启动"
        })
    
    status = scheduler.get_status()
    return JSONResponse(status)
# ============================================================================
# Configuration helpers
# ============================================================================

def load_jobs() -> list[dict[str, Any]]:
    """Load job configurations from YAML."""
    service_config = get_service_config()
    path = Path(service_config["criteria_path"])
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - configuration error
        raise RuntimeError(f"解析岗位配置失败: {exc}") from exc

    roles = data.get("roles")
    if isinstance(roles, list):
        return roles
    return []
