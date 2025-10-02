"""Enhanced message console with resume viewing, scoring, and AI drafting."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls

COMPANY_MD_PATH = Path("config/company.md")
DEFAULT_HISTORY_LIMIT = 10

# ---------------------------------------------------------------------------
# Data loaders and helpers
# ---------------------------------------------------------------------------



@st.cache_data(ttl=600, show_spinner="获取消息列表中...")
def _get_dialogs_cached(base_url: str, limit: int) -> List[Dict[str, Any]]:
    """Cached message fetching - depends only on inputs, not session state."""
    ok, payload = call_api(base_url, "GET", "/chat/dialogs", params={"limit": limit})
    if not ok:
        raise ValueError(f"获取消息列表失败: {payload}")
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        raise ValueError("API 返回的消息格式不符合预期")
    return messages

@st.cache_data(ttl=300, show_spinner="获取简历中...")
def _fetch_resume(base_url: str, chat_id: str, endpoint: str) -> Optional[Dict[str, Any]]:
    """Fetch resume data with Streamlit caching."""
    ok, payload = call_api(base_url, "POST", endpoint, json={"chat_id": chat_id})
    if not ok or not isinstance(payload, dict):
        # Don't cache errors - raise exception to skip caching
        raise ValueError(f"获取简历失败: {payload}")
    return payload


@st.cache_data(ttl=300, show_spinner="获取聊天记录中...")
def _fetch_history(base_url: str, chat_id: str) -> List[str]:
    """Fetch chat history with Streamlit caching."""
    ok, payload = call_api(base_url, "GET", f"/chat/{chat_id}/messages")
    messages: List[str] = []
    if ok and isinstance(payload, dict):
        raw = payload.get("messages") 
        for item in raw[-DEFAULT_HISTORY_LIMIT:]:
            messages.append(item)
    else:
        raise ValueError(f"获取聊天记录失败: {payload}")
    return messages[-DEFAULT_HISTORY_LIMIT:]






# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------

def render_resume_section(
    title: str,
    base_url: str,
    chat_id: str,
    endpoint: str,
    cache_key: str,
    request_when_missing: bool = False,
    check_endpoint: Optional[str] = None,
) -> str:
    """
    渲染简历展示区块，支持加载、刷新、可选的可用性检查和简历请求。

    参数:
        title (str): 展开区块标题。
        base_url (str): 后端服务基础URL。
        chat_id (str): 聊天会话ID。
        endpoint (str): 获取简历的API端点。
        cache_key (str): 用于缓存的唯一键。
        request_when_missing (bool): 若简历不可用时是否允许请求简历。
        check_endpoint (Optional[str]): 检查简历可用性的API端点（可选）。

    返回:
        str: 简历文本内容（如有），否则为空字符串。
    """
    text = ""
    load_state_key = f"loaded_{cache_key}_{chat_id}"
    with st.expander(title, expanded=False):
        cols = st.columns([1, 1, 3])
        if cols[0].button("加载", key=f"load_{cache_key}_{chat_id}"):
            st.session_state[load_state_key] = True
        if cols[1].button("刷新", key=f"refresh_{cache_key}_{chat_id}"):
            st.session_state.setdefault(cache_key, {}).pop(chat_id, None)
            st.session_state[load_state_key] = False

        load_state = st.session_state.get(load_state_key, False)
        if not load_state:
            st.caption("点击“加载”以获取内容。")
            return text

        if check_endpoint:
            check_ok, check_payload = call_api(
                base_url,
                "POST",
                check_endpoint,
                json={"chat_id": chat_id},
            )
            if not (check_ok and isinstance(check_payload, dict) and check_payload.get("available")):
                detail = (check_payload or {}).get("details") if check_payload else None
                st.warning(detail or "暂无附件简历，请稍后重试。")
                if request_when_missing and st.button("请求简历", key=f"request_resume_{chat_id}"):
                    with st.spinner("请求简历中..."):
                        ok, payload = call_api(
                            base_url,
                            "POST",
                            "/resume/request",
                            json={"chat_id": chat_id},
                        )
                    if ok:
                        st.success("已发送简历请求")
                    else:
                        st.error(f"请求失败: {payload}")
                return text

        try:
            data = _fetch_resume(base_url, chat_id, endpoint)
        except ValueError as e:
            st.error(str(e))
            return text

        success = bool(data and data.get("success", True))
        if not success:
            details = data.get("details") if data else None
            st.warning(details or "无法获取简历。")
            return text

        text = data.get("text") or data.get("content") or ""
        if text:
            st.text_area("内容", value=text, height=300)
        else:
            st.info("暂无可显示的简历文本。")
        return text


def render_history_section(base_url: str, chat_id: str) -> List[str]:
    try:
        history = _fetch_history(base_url, chat_id)
    except ValueError as e:
        st.error(str(e))
        history = []
    
    with st.expander("最近 10 条对话", expanded=False):
        if history:
            # Format history data for better table display
            formatted_history = []
            for item in history:
                type_emoji = "👤" if item.get('type') == 'candidate' else "🏢"
                status_emoji = "✅" if item.get('status') == 'processed' else "⏳" if item.get('status') else "❓"
                formatted_item = {
                    '类型': f"{type_emoji} {'候选人' if item.get('type') == 'candidate' else 'HR'}",
                    '时间': item.get('timestamp', ''),
                    '消息内容': item.get('message', ''),
                    '状态': f"{status_emoji} {item.get('status', '未处理') if item.get('status') else '未处理'}"
                }
                formatted_history.append(formatted_item)
            import pandas as pd
            df = pd.DataFrame(formatted_history)
            st.dataframe(
                df, 
                width="stretch", 
                hide_index=True,
                column_config={
                    "类型": st.column_config.TextColumn("类型", width="small"),
                    "时间": st.column_config.TextColumn("时间", width="medium"),
                    "消息内容": st.column_config.TextColumn("消息内容", width="large"),
                    "状态": st.column_config.TextColumn("状态", width="small")
                }
            )
        else:
            st.info("暂无聊天记录")
    return history




# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("消息列表")
    ensure_state()
    sidebar_controls(include_config_path=False)
    
    # Get base_url from session state
    base_url = st.session_state["base_url"]

    # === Data Loading Phase (cached, fast) ===
    limit = st.sidebar.slider("每次获取对话数量", min_value=5, max_value=100, value=30, step=5)
    with st.spinner("获取聊天对话数据中..."):
        dialogs = _get_dialogs_cached(base_url, limit)

    if not dialogs:
        st.info("暂无聊天对话数据。。。")
        return

    col_select, col_refresh = st.columns([9, 1])
    chat_id = col_select.selectbox(
        'None',
        options=[row["id"] for row in dialogs],
        format_func=lambda cid: next(
            (f"{row['name']}({row['job_title']}):{row['text']}" for row in dialogs if row['id'] == cid),
            cid,
        ),
        key="chat_selector",
        index=1,
        label_visibility="collapsed",
    )
    selected_dialog = next((row for row in dialogs if row['id'] == chat_id), None)
    if col_refresh.button("🔄", key="refresh_messages_main"):
        _get_dialogs_cached.clear()
        st.rerun()
    
    # Null safety check
    if not selected_dialog:
        st.warning("未能找到选中的候选人，请刷新列表重试")
        return

    # Sync job selection (non-blocking, wrapped in try-except)
    selected_job = st.session_state["selected_job"]

    # === Lazy Data Loading (only when expanders are opened) ===
    online_resume = render_resume_section(
        title="在线简历", 
        base_url=base_url, 
        chat_id=chat_id, 
        endpoint="/resume/online", 
        cache_key="online_resume_cache")
    full_resume = render_resume_section(
        title="附件简历",
        base_url=base_url,
        chat_id=chat_id,
        endpoint="/resume/view_full",
        cache_key="full_resume_cache",
        request_when_missing=True,
        check_endpoint="/resume/check_full",
    )
    resume_text = full_resume or online_resume

    # History - loaded on demand
    history_lines = render_history_section(base_url, chat_id)
    history_text = "\n".join([
        f"{item.get('type', 'unknown')}: {item.get('message', '')}"
        for item in history_lines
    ])

    # === Scoring Section (user-triggered) ===
    st.subheader("自动评分")
    notes = st.text_area(
        "补充说明", 
        placeholder="补充说明 (可选)", 
        value="", 
        key=f"score_notes_{chat_id}", 
        label_visibility="collapsed"
    )
    if st.button("Analyze", key=f"analyze_{chat_id}"):
        context = {
            "job_description": selected_job.get("description", ""),
            "target_profile": selected_job.get("target_profile", ""),
            "candidate_resume": resume_text or "无",
            "chat_history": history_text or "无",
            "notes": notes,
        }
        with st.spinner("分析中..."):
            ok, payload = call_api(
                base_url, "POST", "/assistant/analyze-candidate",
                json={"chat_id": chat_id, "context": context}
            )
            if ok and payload.get("success"):
                result = payload.get("analysis")
                st.session_state.setdefault("analysis_results", {})[chat_id] = result
            else:
                error = payload.get("error") if isinstance(payload, dict) else str(payload)
                st.error(f"无法解析评分结果: {error}")
        st.rerun()

    # Display analysis results
    result = st.session_state.get("analysis_results", {}).get(chat_id)
    if result:
        cols = st.columns(4)
        cols[0].metric("技能匹配", result.get("skill"))
        cols[1].metric("创业契合", result.get("startup_fit"))
        cols[2].metric("加入意愿", result.get("willingness"))
        cols[3].metric("综合评分", result.get("overall"))
        st.markdown(f"**分析总结：** {result.get('summary', '—')}")

    # === Message Section (user-triggered) ===
    st.subheader("生成消息")
    message_state = st.session_state.setdefault("generated_messages", {})
    draft = message_state.get(chat_id, "")
    draft = st.text_area("消息内容", value=draft, height=180, key=f"message_draft_{chat_id}")
    col_generate, col_send = st.columns(2)
    # Generate button
    if col_generate.button("生成建议", key=f"generate_msg_{chat_id}"):
        context = {
            "job_description": selected_job.get("description", ""),
            "target_profile": selected_job.get("target_profile", ""),
            "candidate_resume": resume_text or "无",
            "chat_history": history_text or "无",
            "notes": draft,
        }
        with st.spinner("生成中..."):
            ok, payload = call_api(
                base_url, "POST", "/assistant/generate-followup",
                json={
                    "chat_id": chat_id,
                    "prompt": draft or "",
                    "context": context
                }
            )
            message = payload.get("message") if ok else None
        if message:
            message_state[chat_id] = message
            st.success("生成完成！")
            st.rerun()
        else:
            st.error("生成失败")
    # Send button
    if col_send.button("发送消息", key=f"send_msg_{chat_id}"):
        content = draft.strip()
        if not content:
            st.warning("消息内容不能为空")
        else:
            with st.spinner("发送中..."):
                ok, payload = call_api(
                    base_url,
                    "POST",
                    f"/chat/{chat_id}/send",
                    json={"message": content},
                )
                success = ok
            if success:
                st.success("消息已发送")
                message_state[chat_id] = content
            else:
                st.error("发送失败")

if __name__ == "__main__":
    main()
