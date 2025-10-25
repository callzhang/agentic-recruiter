"""Assistant management routes for web UI."""

from __future__ import annotations

from typing import Any
import json
from datetime import datetime

import httpx
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

# Add custom filter for timestamp formatting
def format_timestamp(timestamp):
    """Format timestamp to readable date."""
    if not timestamp:
        return "未知"
    try:
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return "未知"

templates.env.filters["format_timestamp"] = format_timestamp

API_BASE_URL = settings.BOSS_SERVICE_BASE_URL

# Default assistant instructions
DEFAULT_INSTRUCTIONS = """
你是一个专业的招聘顾问助理。你的职责是：
1. 根据候选人背景和公司需求，生成专业、真诚的招聘消息
2. 对于首次联系，生成友好的打招呼消息，突出公司亮点
3. 对于跟进消息，基于之前的对话历史，生成个性化的跟进内容
4. 保持专业、简洁、真诚的沟通风格
5. 突出候选人与岗位的匹配点
请始终使用中文回复，消息长度控制在100-200字。

【打招呼用语】：
{candidate} 你好，我是 Stardust 星尘数据的招聘顾问。我们正在打造企业级 AI 基础设施，希望与你聊聊 {position} 机会。
您好，我来自 Stardust 的 MorningStar 团队，对您在 {skill} 方面的实践非常感兴趣，想约个时间交流一下？

【跟进用语】:
想确认一下我们之前的沟通是否方便继续？如需了解更多关于团队挑战或产品路线，随时告诉我。
如果您对 PB 级数据/大模型平台建设好奇，我们可以深入介绍 MorningStar & Rosetta 的真实场景。
"""


async def call_api(method: str, path: str, timeout: float = 30.0, **kwargs) -> tuple[bool, Any]:
    """Make HTTP request to internal API without blocking the event loop."""
    base_url = API_BASE_URL or "http://127.0.0.1:5001"
    url = f"{base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method.upper(), url, **kwargs)
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            return True, response.json()
        return True, response.text
    except httpx.HTTPError as exc:
        return False, str(exc)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def assistants_page(request: Request):
    """Main assistants management page."""
    return templates.TemplateResponse("assistants.html", {"request": request})


@router.get("/list", response_class=HTMLResponse)
async def list_assistants():
    """Get assistants list as HTML."""
    ok, data = await call_api("GET", "/assistant/list")
    
    if not ok or not isinstance(data, list):
        return HTMLResponse(
            content=f'<div class="p-6 text-center text-red-500">获取助手列表失败: {data}</div>'
        )
    
    if not data:
        return HTMLResponse(
            content='<div class="p-6 text-center text-gray-500">暂无助手</div>'
        )
    
    # Render assistants table
    html = '<table class="w-full"><thead><tr class="bg-gray-50"><th class="p-4 text-left">名称</th><th class="p-4 text-left">模型</th><th class="p-4 text-left">描述</th><th class="p-4">操作</th></tr></thead><tbody class="divide-y">'
    
    for assistant in data:
        html += f'''
        <tr class="hover:bg-gray-50">
            <td class="p-4 font-medium">{assistant.get("name", "未知")}</td>
            <td class="p-4 text-sm text-gray-600">{assistant.get("model", "")}</td>
            <td class="p-4 text-sm text-gray-600">{(assistant.get("description", "") or "")[:100]}</td>
            <td class="p-4 text-center">
                <a href="/web/assistants/{assistant.get("id")}" class="text-blue-600 hover:text-blue-800">编辑</a>
            </td>
        </tr>
        '''
    
    html += '</tbody></table>'
    
    return HTMLResponse(content=html)


@router.get("/list-simple", response_class=HTMLResponse)
async def list_assistants_simple():
    """Get assistants as HTML options for select."""
    ok, data = await call_api("GET", "/assistant/list")
    
    if not ok or not isinstance(data, list):
        return HTMLResponse(content='<option>加载失败</option>')
    
    if not data:
        return HTMLResponse(content='<option>无助手</option>')
    
    html = ""
    for assistant in data:
        html += f'<option value="{assistant.get("id")}">{assistant.get("name", "未知")}</option>'
    
    return HTMLResponse(content=html)


@router.get("/new", response_class=HTMLResponse)
async def new_assistant_page(request: Request):
    """Create new assistant page."""
    return templates.TemplateResponse("assistant_edit.html", {
        "request": request,
        "assistant": None,
        "default_instructions": DEFAULT_INSTRUCTIONS
    })


@router.get("/{assistant_id}", response_class=HTMLResponse)
async def edit_assistant_page(request: Request, assistant_id: str):
    """Edit assistant page."""
    ok, data = await call_api("GET", "/assistant/list")
    
    if not ok or not isinstance(data, list):
        raise HTTPException(status_code=404, detail="无法加载助手列表")
    
    assistant = next((a for a in data if a.get("id") == assistant_id), None)
    if not assistant:
        raise HTTPException(status_code=404, detail="助手不存在")
    
    return templates.TemplateResponse("assistant_edit.html", {
        "request": request,
        "assistant": assistant,
        "default_instructions": DEFAULT_INSTRUCTIONS
    })


@router.post("/create", response_class=JSONResponse)
async def create_assistant(
    name: str = Form(...),
    model: str = Form(...),
    description: str = Form(""),
    instructions: str = Form(...),
    metadata_key: list = Form([]),
    metadata_value: list = Form([])
):
    """Create new assistant."""
    # Build metadata dict from form data
    metadata = {}
    for i, key in enumerate(metadata_key):
        # Only include non-empty keys and values
        if key and key.strip() and i < len(metadata_value):
            value = metadata_value[i] if i < len(metadata_value) else ""
            if value and value.strip():  # Only include non-empty values
                metadata[key.strip()] = value.strip()
    
    payload = {
        "name": name,
        "model": model,
        "description": description,
        "instructions": instructions,
        "metadata": metadata
    }
    
    ok, response = await call_api("POST", "/assistant/create", json=payload)
    
    if not ok:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"创建失败: {response}"}
        )
    
    return JSONResponse(content={"success": True, "data": response})


@router.post("/{assistant_id}/update", response_class=JSONResponse)
async def update_assistant(
    assistant_id: str,
    request: Request
):
    """Update existing assistant."""
    # Get form data
    form_data = await request.form()
    
    # Extract basic fields
    name = form_data.get("name", "")
    model = form_data.get("model", "")
    description = form_data.get("description", "")
    instructions = form_data.get("instructions", "")
    
    # Build metadata dict from form data
    metadata = {}
    metadata_keys = form_data.getlist("metadata_key")
    metadata_values = form_data.getlist("metadata_value")
    
    for i, key in enumerate(metadata_keys):
        # Only include non-empty keys and values
        if key and key.strip():
            value = metadata_values[i] if i < len(metadata_values) else ""
            if value and value.strip():  # Only include non-empty values
                metadata[key.strip()] = value.strip()
    
    payload = {
        "name": name,
        "model": model,
        "description": description,
        "instructions": instructions,
        "metadata": metadata
    }
    
    ok, response = await call_api("POST", f"/assistant/update/{assistant_id}", json=payload)
    
    if not ok:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"更新失败: {response}"}
        )
    
    return JSONResponse(content={"success": True, "data": response})


@router.delete("/{assistant_id}/delete", response_class=JSONResponse)
async def delete_assistant(assistant_id: str):
    """Delete assistant."""
    ok, response = await call_api("DELETE", f"/assistant/delete/{assistant_id}")
    
    if not ok:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"删除失败: {response}"}
        )
    
    return JSONResponse(content={"success": True, "data": response})


# API endpoints for external access
@router.get("/api/list", response_class=JSONResponse)
async def api_list_assistants():
    """API endpoint to list all assistants."""
    ok, data = await call_api("GET", "/assistant/list")
    
    if not ok:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"获取助手列表失败: {data}"}
        )
    
    return JSONResponse(content={"success": True, "data": data})


@router.get("/api/{assistant_id}", response_class=JSONResponse)
async def api_get_assistant(assistant_id: str):
    """API endpoint to get specific assistant."""
    ok, data = await call_api("GET", "/assistant/list")
    
    if not ok:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"获取助手列表失败: {data}"}
        )
    
    assistant = next((a for a in data if a.get("id") == assistant_id), None)
    if not assistant:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "助手不存在"}
        )
    
    return JSONResponse(content={"success": True, "data": assistant})
