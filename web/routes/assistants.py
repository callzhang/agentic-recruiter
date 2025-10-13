"""Assistant management routes for web UI."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

API_BASE_URL = settings.BOSS_SERVICE_BASE_URL


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
