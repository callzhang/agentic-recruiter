"""Enhanced message console with resume viewing, scoring, and AI drafting."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls, SessionKeys, get_selected_job

COMPANY_MD_PATH = Path("config/company.md")
DEFAULT_HISTORY_LIMIT = 10

# ---------------------------------------------------------------------------
# Data loaders and helpers
# ---------------------------------------------------------------------------



@st.cache_data(ttl=600, show_spinner="获取消息列表中...")
def _get_dialogs_cached(limit: int, tab: str = '新招呼', status: str = '未读', job_title: str = '全部') -> List[Dict[str, Any]]:
    """Cached message fetching - depends only on inputs, not session state."""
    params = {
        "limit": limit,
        "tab": tab,
        "status": status,
        "job_title": job_title
    }
    ok, payload = call_api("GET", "/chat/dialogs", params=params)
    if not ok:
        raise ValueError(f"获取消息列表失败: {payload}")
    if not isinstance(payload, list):
        raise ValueError("API 返回的消息格式不符合预期")
    return payload

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
    if not ok or not isinstance(payload, list):
        raise ValueError(f"获取聊天记录失败: {payload}")
    return payload


def _fetch_best_resume(chat_id: str) -> tuple[str, str]:
    """
    Fetch best available resume (full resume preferred, online as fallback).
    
    Cached for 10 minutes to improve performance.
    
    Returns:
        tuple[str, str]: (resume_text, source) where source is "附件简历" or "在线简历"
    """
    # Step 1: Check if full resume is available
    full_resume_available = check_full_resume(chat_id)
    
    # Step 2: Get full resume if available
    if full_resume_available:
        full_payload = _fetch_full_resume(chat_id)
        if full_payload.get("success"):
            resume_text = full_payload.get("text", "")
            if resume_text:
                return resume_text, "附件简历"
            else:
                st.error(f"获取附件简历失败: {full_payload}")
    
    # Step 3: Fallback to online resume
    online_payload = _fetch_online_resume(chat_id)
    if online_payload.get("success"):
        resume_text = online_payload.get("text", "")
        if resume_text:
            return resume_text, "在线简历"
        else:
            st.error(f"获取在线简历失败: {online_payload}")
    
    return "无简历数据", "无"

@st.cache_data(ttl=300, show_spinner="检查简历中...")
def check_full_resume(chat_id: str) -> bool:
    """Check if full resume is available."""
    ok, available = call_api("POST", "/resume/check_full_resume_available", json={"chat_id": chat_id})
    return ok and available

@st.cache_data(show_spinner="获取简历中...")
def _fetch_full_resume(chat_id: str) -> Dict[str, Any]:
    """Fetch full resume with Streamlit caching."""
    ok, payload = call_api("POST", "/resume/view_full", json={"chat_id": chat_id})
    if not ok or not payload.get('success'): 
        raise ValueError(f"获取简历失败: {payload}")
    return payload


@st.cache_data(show_spinner="获取在线简历中...")
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


def render_history_section(history: List[Dict[str, Any]]) -> None:
    """Render history section UI (separated from data fetching)"""
    with st.expander("对话记录", expanded=True):
        # Format history data for better table display
        formatted_history = []
        for item in history:
            type_emoji = "👤" if item.get('type') == 'candidate' else "🏢"
            status_emoji = "✅" if item.get('status') == 'processed' else "⏳" if item.get('status') else "❓"
            formatted_item = {
                '类型': f"{type_emoji} {'候选人' if item.get('type') == 'candidate' else 'HR'}",
                '时间': item.get('timestamp', ''),
                '消息内容': item.get('message', ''),
                '状态': f"{status_emoji} {item.get('status') if item.get('status') else '未处理'}"
            }
            formatted_history.append(formatted_item)
        import pandas as pd
        df = pd.DataFrame(history)
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


@st.cache_data(show_spinner="分析中...")
def _analyze_candidate(chat_id: str, assistant_id: str, history: list[dict]) -> Dict[str, Any]:
    context = {
        "chat_id": chat_id,
        "assistant_id": assistant_id,
        "chat_history": history,
        "purpose": "analyze",
        # "instruction": "请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。",
    }
    ok, payload = call_api(
        "POST", "/assistant/generate-message",
        json=context
        )
    if ok:
        get_thread_messages.clear()
        generated_message, thread_id = payload
        st.session_state.setdefault(SessionKeys.ANALYSIS_RESULTS, {})[chat_id] = generated_message
        return generated_message
    else:
        st.error(f"无法解析评分结果: {payload}")
        raise ValueError(f"无法解析评分结果: {payload}")

@st.cache_data(show_spinner="获取候选人中...")
def get_candidate_by_id(chat_id: str) -> Dict[str, Any]:
    """Get candidate by ID."""
    ok, payload = call_api("GET", f"/candidate/{chat_id}", params={"fields": None})
    if not ok or not isinstance(payload, dict):
        raise ValueError(f"获取候选人失败: {payload}")
    return payload


def init_chat(chat_id: str, job_info: dict, resume_text: str, chat_history: list[dict]) -> bool:
    """Init chat."""
    ok, payload = call_api("POST", "/thread/init-chat", json={
        "chat_id": chat_id,
        "job_info": job_info,
        "resume_text": resume_text,
        "chat_history": chat_history
    })
    get_candidate_by_id.clear()
    return ok

@st.cache_data(show_spinner="获取thread聊天记录中...")
def get_thread_messages(thread_id: str) -> list[dict]:
    """Get thread messages."""
    ok, payload = call_api("GET", f"/thread/{thread_id}/messages")
    if not ok or not isinstance(payload, list):
        raise ValueError(f"获取聊天记录失败: {payload}")
    return payload

# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("消息列表")
    ensure_state()
    sidebar_controls(include_config_path=False, include_job_selector=True)
    limit = st.sidebar.slider("每次获取对话数量", min_value=5, max_value=100, value=30, step=5)
    
    # Sync job selection
    selected_job_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
    selected_job = get_selected_job(selected_job_idx)
    # === Filter Controls ===
    col1, col2 = st.columns(2)
    
    with col1:
        tab_filter = st.radio(
            "聊天标签",
            options=['全部', '新招呼', '沟通中'],
            index=0,
            help="选择要查看的聊天标签",
            horizontal=True
        )
    
    with col2:
        status_filter = st.radio(
            "消息状态",
            options=['全部', '未读', '牛人已读未回'],
            index=0,
            help="选择要查看的消息状态",
            horizontal=True
        )
    
    
    # === Data Loading Phase (cached, fast) ===
    with st.spinner("获取聊天对话数据中..."):
        job_title = selected_job.get("position")
        dialogs = _get_dialogs_cached(limit, tab_filter, status_filter, job_title)

    if not dialogs:
        st.info("暂无聊天对话数据。。。")
        return
    # 对话下拉框
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
    # 选中对话
    selected_dialog = next((row for row in dialogs if row['id'] == chat_id), None)
    if col_refresh.button("🔄", key="refresh_messages_main"):
        _get_dialogs_cached.clear()
        st.rerun()

    # Null safety check
    if not selected_dialog:
        st.warning("未能找到选中的候选人，请刷新列表重试")
        return


    # === Data Fetching Phase (upfront, cached by Streamlit) ===
    try:
        candidate_object = get_candidate_by_id(chat_id)
        record_exists = True
    except Exception as e:
        # cannot create a new candidate without resume_text
        candidate_object = {
            "name": selected_dialog.get("name"), 
            "job_applied": job_title}

    resume_text = candidate_object.get("resume_text")
    if not resume_text:
        # Fetch resume data (cached by @st.cache_data for 10 minutes)
        resume_text, resume_source = _fetch_best_resume(chat_id)
    
    # Fetch history data (cached by @st.cache_data for 5 minutes)
    if not record_exists:
        history_lines = _fetch_history(chat_id)
        history_text = "\n".join([
            f"{item.get('type', 'unknown')}: {item.get('message', '')}"
            for item in history_lines
        ])
    else:
        history_lines = candidate_object.get("history")
        history_text = "\n".join([
            f"{item.get('type', 'unknown')}: {item.get('message', '')}"
            for item in history_lines
        ])
    
    if not record_exists:
        # init chat
        init_chat(chat_id, job_title, resume_text, history_lines)

    # === UI Rendering Phase (display data in expanders) ===
    # Resume expanders - now filled with cached data
    with st.expander("简历信息", expanded=bool(resume_text)):
        col1, col2 = st.columns(2)
        with col1:
            st.metric("简历来源", resume_source)
        with col2:
            if st.button("🔄 刷新简历", key=f"refresh_resume_{chat_id}"):
                # Clear Streamlit cache and reload
                _fetch_online_resume.clear()
                _fetch_full_resume.clear()
                st.rerun()
        
        if resume_text:
            st.text_area("简历内容", value=resume_text, height=300, key=f"resume_display_{chat_id}")
        else:
            st.warning("暂无简历数据")
    
    # History expander - now filled with fetched data
    render_history_section(history_lines)

    # === Scoring Section (user-triggered) ===
    st.subheader("自动评分")

    # Display analysis results
    # analysis_result = st.session_state.get(SessionKeys.ANALYSIS_RESULTS, {}).get(chat_id)
    analysis_result = candidate_object.get("scores")
    if analysis_result:
        cols = st.columns(4)
        cols[0].metric("技能匹配", analysis_result.get("skill"))
        cols[1].metric("创业契合", analysis_result.get("startup_fit"))
        cols[2].metric("加入意愿", analysis_result.get("willingness"))
        cols[3].metric("综合评分", analysis_result.get("overall"), help='1-10分, 如果需要调整评分，请修改助手配置')
        st.markdown(f"**分析总结：** {analysis_result.get('summary', '—')}")

    else:
        assistant_id = st.session_state.get(SessionKeys.SELECTED_ASSISTANT_ID)
        analysis_result = _analyze_candidate(chat_id, assistant_id, history_lines)
        update_candidate_object(chat_id, {"scores": analysis_result})
        st.rerun()

    # === Message Section (user-triggered) ===
    st.subheader("生成消息")
    message_state = st.session_state.setdefault(SessionKeys.GENERATED_MESSAGES, {})
    draft = message_state.get(chat_id, "")
    draft_message = st.empty()
    draft = draft_message.text_area("消息内容", value=draft, height=180, key=f"message_draft_{chat_id}")
    col_generate, col_send = st.columns(2)
    # Generate button
    if col_generate.button("生成建议", key=f"generate_msg_{chat_id}", disabled=bool(draft)):
        analysis_result = st.session_state.get(SessionKeys.ANALYSIS_RESULTS, {}).get(chat_id) or \
            _analyze_candidate(chat_id, selected_job, resume_text, history_text)
        assistant_id = st.session_state.get(SessionKeys.SELECTED_ASSISTANT_ID)
        # candidate_summary = (selected_dialog or {}).get("text", "")

        payload = {
            "chat_id": chat_id,
            "prompt": draft or "",
            "assistant_id": assistant_id,
            "chat_history": history_lines,
            "job_info": selected_job,
            # "candidate_summary": candidate_summary,
            "candidate_resume": resume_text,
            "analysis": analysis_result,
            "purpose": "chat",
        }

        with st.spinner("生成中..."):
            ok, payload = call_api(
                "POST", "/assistant/generate-message",
                json=payload,
            )
            message = payload if ok else None
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
