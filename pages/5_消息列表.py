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
def _get_dialogs_cached(limit: int) -> List[Dict[str, Any]]:
    """Cached message fetching - depends only on inputs, not session state."""
    ok, payload = call_api("GET", "/chat/dialogs", params={"limit": limit})
    if not ok:
        raise ValueError(f"获取消息列表失败: {payload}")
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        raise ValueError("API 返回的消息格式不符合预期")
    return messages

@st.cache_data(ttl=300, show_spinner="获取简历中...")
def _fetch_resume(chat_id: str, endpoint: str) -> Optional[Dict[str, Any]]:
    """Fetch resume data with Streamlit caching."""
    ok, payload = call_api("POST", endpoint, json={"chat_id": chat_id})
    if not ok or not isinstance(payload, dict):
        # Don't cache errors - raise exception to skip caching
        raise ValueError(f"获取简历失败: {payload}")
    return payload


@st.cache_data(ttl=300, show_spinner="获取聊天记录中...")
def _fetch_history(chat_id: str) -> List[str]:
    """Fetch chat history with Streamlit caching."""
    ok, payload = call_api("GET", f"/chat/{chat_id}/messages")
    messages: List[str] = []
    if ok and isinstance(payload, dict):
        raw = payload.get("messages") 
        for item in raw[-DEFAULT_HISTORY_LIMIT:]:
            messages.append(item)
    else:
        raise ValueError(f"获取聊天记录失败: {payload}")
    return messages


def _fetch_best_resume(chat_id: str) -> tuple[str, str]:
    """
    Fetch best available resume (full resume preferred, online as fallback).
    
    Cached for 10 minutes to improve performance.
    
    Returns:
        tuple[str, str]: (resume_text, source) where source is "附件简历" or "在线简历"
    """
    # Step 1: Check if full resume is available
    ok_check, check_payload = call_api(
        "POST", "/resume/check_full",
        json={"chat_id": chat_id}
    )
    
    if ok_check and check_payload.get("available"):
        # Step 2: Get full resume if available
        full_payload = _fetch_full_resume(chat_id)
        if full_payload.get("success"):
            resume_text = full_payload.get("text", "")
            if resume_text:
                return resume_text, "附件简历"
    
    # Step 3: Fallback to online resume
    online_payload = _fetch_online_resume(chat_id)
    if online_payload.get("success"):
        resume_text = online_payload.get("text", "")
        if resume_text:
            return resume_text, "在线简历"
    
    return "无简历数据", "无"


@st.cache_data(show_spinner="获取简历中...")
def _fetch_full_resume(chat_id: str) -> Dict[str, Any]:
    """Fetch full resume with Streamlit caching."""
    ok, payload = call_api("POST", "/resume/view_full", json={"chat_id": chat_id})
    if not ok or not isinstance(payload, dict):
        raise ValueError(f"获取简历失败: {payload}")
    return payload


@st.cache_data(show_spinner="获取简历中...")
def _fetch_online_resume(chat_id: str) -> Dict[str, Any]:
    """Fetch online resume with Streamlit caching."""
    ok, payload = call_api("POST", "/resume/online", json={"chat_id": chat_id})
    if not ok or not isinstance(payload, dict):
        raise ValueError(f"获取简历失败: {payload}")
    return payload



# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------

def render_resume_section(
    title: str,
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

        load_state = st.session_state.get(load_state_key, False)
        if not load_state:
            st.caption("点击“加载”以获取内容。")
            return text

        if st.session_state[load_state_key]:
            data = _fetch_resume(chat_id, endpoint)

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


def _get_history_data(chat_id: str) -> List[Dict[str, Any]]:
    """Fetch history data (separated from UI rendering)"""
    try:
        return _fetch_history(chat_id)
    except ValueError as e:
        st.error(str(e))
        return []


def render_history_section(history: List[Dict[str, Any]]) -> None:
    """Render history section UI (separated from data fetching)"""
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




# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("消息列表")
    ensure_state()
    sidebar_controls(include_config_path=False, include_job_selector=True)
    
    # === Data Loading Phase (cached, fast) ===
    limit = st.sidebar.slider("每次获取对话数量", min_value=5, max_value=100, value=30, step=5)
    with st.spinner("获取聊天对话数据中..."):
        dialogs = _get_dialogs_cached(limit)

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

    # Sync job selection
    selected_job = st.session_state["selected_job"]

    # === Data Fetching Phase (upfront, cached by Streamlit) ===
    # Fetch resume data (cached by @st.cache_data for 10 minutes)
    resume_text, resume_source = _fetch_best_resume(chat_id)
    
    # Fetch history data (cached by @st.cache_data for 5 minutes)
    history_lines = _get_history_data(chat_id)
    history_text = "\n".join([
        f"{item.get('type', 'unknown')}: {item.get('message', '')}"
        for item in history_lines
    ])
    
    # === UI Rendering Phase (display data in expanders) ===
    # Resume expanders - now filled with cached data
    with st.expander("简历信息", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.metric("简历来源", resume_source)
        with col2:
            if st.button("🔄 刷新简历", key=f"refresh_resume_{chat_id}"):
                # Clear Streamlit cache and reload
                _fetch_best_resume.clear()
                st.rerun()
        
        if resume_text and resume_text != "无简历数据":
            st.text_area("简历内容", value=resume_text, height=300, key=f"resume_display_{chat_id}")
        else:
            st.warning("暂无简历数据")
    
    # History expander - now filled with fetched data
    render_history_section(history_lines)

    # === Scoring Section (user-triggered) ===
    st.subheader("自动评分")
    notes = st.text_input(
        "自动评分", 
        placeholder="补充说明 (可选)", 
        value="", 
        key=f"score_notes_{chat_id}", 
        label_visibility="collapsed"
    )
    if st.button("Analyze", key=f"analyze_{chat_id}"):
        # Use cached resume data
        context = {
            "job_description": selected_job.get("description", ""),
            "target_profile": selected_job.get("target_profile", ""),
            "candidate_resume": resume_text,
            "chat_history": history_text or "无",
            "notes": notes,
        }
        with st.spinner("分析中..."):
            ok, payload = call_api(
                "POST", "/assistant/analyze-candidate",
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
    draft_message = st.empty()
    draft = draft_message.text_area("消息内容", value=draft, height=180, key=f"message_draft_{chat_id}")
    col_generate, col_send = st.columns(2)
    # Generate button
    if col_generate.button("生成建议", key=f"generate_msg_{chat_id}"):
        # Use cached resume data
        context = {
            "job_description": selected_job.get("description", ""),
            "target_profile": selected_job.get("target_profile", ""),
            "candidate_resume": resume_text,
            "chat_history": history_text or "无",
            "notes": draft,
        }
        with st.spinner("生成中..."):
            ok, payload = call_api(
                "POST", "/assistant/generate-followup",
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
            draft_message.text_area("消息内容", value=message, height=180)
            st.rerun()
        else:
            st.error(f"生成失败: {payload}")
    # Send button
    if col_send.button("发送消息", key=f"send_msg_{chat_id}"):
        content = draft.strip()
        if not content:
            st.warning("消息内容不能为空")
        else:
            with st.spinner("发送中..."):
                ok, payload = call_api(
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
