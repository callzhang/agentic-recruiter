"""Enhanced message console with resume viewing, scoring, and AI drafting."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls
from src.assistant_actions import assistant_actions, OPENAI_DEFAULT_MODEL

COMPANY_MD_PATH = Path("config/company.md")
DEFAULT_HISTORY_LIMIT = 10


# ---------------------------------------------------------------------------
# Data loaders and helpers
# ---------------------------------------------------------------------------

def _load_jobs() -> List[Dict[str, Any]]:
    cache = st.session_state.get("_jobs_cache")
    if isinstance(cache, list):
        return cache
    return []


def _load_company_description() -> str:
    if "_company_md_cache" not in st.session_state:
        try:
            st.session_state["_company_md_cache"] = COMPANY_MD_PATH.read_text(encoding="utf-8")
        except Exception:
            st.session_state["_company_md_cache"] = ""
    return st.session_state["_company_md_cache"]


def _fetch_messages(base_url: str, limit: int) -> List[Dict[str, Any]]:
    ok, payload = call_api(base_url, "GET", "/chat/dialogs", params={"limit": limit})
    if not ok:
        st.error(f"获取消息列表失败: {payload}")
        return []
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        st.warning("API 返回的消息格式不符合预期")
        return []
    st.session_state.setdefault("messages_cache", {})
    st.session_state["messages_cache"] = messages
    return messages


def _get_messages(limit: int) -> List[Dict[str, Any]]:
    cache = st.session_state.get("messages_cache")
    if cache is None:
        base_url = st.session_state["base_url"]
        return _fetch_messages(base_url, limit)
    return cache


def _normalize_chat_id(item: Dict[str, Any], fallback: int) -> str:
    for key in ("chat_id", "id", "chatId"):
        value = item.get(key)
        if value:
            return str(value)
    return str(fallback)


def _cache_get(store_key: str, chat_id: str) -> Optional[Dict[str, Any]]:
    cache = st.session_state.setdefault(store_key, {})
    return cache.get(chat_id)


def _cache_set(store_key: str, chat_id: str, value: Dict[str, Any]) -> None:
    cache = st.session_state.setdefault(store_key, {})
    cache[chat_id] = value


def _fetch_resume(base_url: str, chat_id: str, endpoint: str, cache_key: str) -> Optional[Dict[str, Any]]:
    cached = _cache_get(cache_key, chat_id)
    if cached:
        return cached
    ok, payload = call_api(base_url, "POST", endpoint, json={"chat_id": chat_id})
    if not ok or not isinstance(payload, dict):
        st.error(f"获取简历失败: {payload}")
        return None
    _cache_set(cache_key, chat_id, payload)
    return payload


def _fetch_history(base_url: str, chat_id: str) -> List[str]:
    cached = _cache_get("history_cache", chat_id)
    if cached is not None:
        return cached
    ok, payload = call_api(base_url, "GET", f"/chat/{chat_id}/messages")
    messages: List[str] = []
    if ok and isinstance(payload, dict):
        raw = payload.get("messages")
        if isinstance(raw, list):
            for item in raw[-DEFAULT_HISTORY_LIMIT:]:
                messages.append(str(item))
        elif isinstance(raw, str):
            for line in raw.splitlines():
                if line.strip():
                    messages.append(line.strip())
    else:
        st.error(f"获取聊天记录失败: {payload}")
    _cache_set("history_cache", chat_id, messages[-DEFAULT_HISTORY_LIMIT:])
    return messages[-DEFAULT_HISTORY_LIMIT:]


def _prepare_history_text(history: List[str]) -> str:
    return "\n".join(history[-DEFAULT_HISTORY_LIMIT:])


# ---------------------------------------------------------------------------
# OpenAI interactions
# ---------------------------------------------------------------------------

def _require_openai_client() -> Optional[Any]:
    if not getattr(assistant_actions, "client", None):
        st.warning("OpenAI 客户端未配置，无法使用自动评分或消息生成功能。")
        return None
    return assistant_actions.client


def analyze_candidate(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Analyze candidate using assistant_actions."""
    result = assistant_actions.analyze_candidate(context)
    if not result:
        st.error("无法解析评分结果")
    return result


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
        available = True
        check_payload: Dict[str, Any] | None = None
        if load_state:
            if check_endpoint:
                check_ok, check_payload = call_api(
                    base_url,
                    "POST",
                    check_endpoint,
                    json={"chat_id": chat_id},
                )
                available = bool(check_ok and isinstance(check_payload, dict) and check_payload.get("available"))
            if available:
                data = _fetch_resume(base_url, chat_id, endpoint, cache_key)
                success = bool(data and data.get("success", True))
                if success:
                    text = data.get("text") or data.get("content") or ""
                    if text:
                        st.text_area("内容", value=text, height=300)
                    else:
                        st.info("暂无可显示的简历文本。")
                else:
                    st.warning(data.get("details") or "无法获取简历。")
                    available = False
            if not available:
                detail = (check_payload or {}).get("details") if check_payload else None
                st.warning(detail or "暂无附件简历，请稍后重试。")
                if request_when_missing:
                    if st.button("请求简历", key=f"request_resume_{chat_id}"):
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
        else:
            st.caption("点击“加载”以获取内容。")
        return text


def render_history_section(base_url: str, chat_id: str) -> List[str]:
    history = _fetch_history(base_url, chat_id)
    with st.expander("最近 10 条对话", expanded=False):
        if history:
            df = pd.DataFrame({"消息": history})
            st.dataframe(df, use_container_width=True)
        else:
            st.info("暂无聊天记录")
    return history


def render_scoring_section(chat_id: str, candidate_info: Dict[str, Any], resume_text: str,
                           job_role: Dict[str, Any], company_desc: str, history_text: str) -> None:
    st.subheader("自动评分")
    notes = st.text_area("补充说明 (可选)", value="", key=f"score_notes_{chat_id}")
    if st.button("Analyze", key=f"analyze_{chat_id}"):
        context = {
            "company_description": company_desc,
            "job_description": job_role.get("description", ""),
            "target_profile": job_role.get("target_profile", ""),
            "candidate_resume": resume_text or "无",
            "chat_history": history_text or "无",
            "notes": notes,
        }
        with st.spinner("分析中..."):
            result = analyze_candidate(context)
        if result:
            st.session_state.setdefault("analysis_results", {})[chat_id] = result
            assistant_actions.upsert_candidate(
                chat_id,
                name=candidate_info.get("candidate"),
                job_applied=job_role.get("position"),
                last_message=candidate_info.get("message"),
                resume_text=resume_text,
                scores=result,
            )
    result = st.session_state.get("analysis_results", {}).get(chat_id)
    if result:
        cols = st.columns(4)
        cols[0].metric("技能匹配", result.get("skill"))
        cols[1].metric("创业契合", result.get("startup_fit"))
        cols[2].metric("加入意愿", result.get("willingness"))
        cols[3].metric("综合评分", result.get("overall"))
        st.markdown(f"**分析总结：** {result.get('summary', '—')}")


def render_message_section(base_url: str, chat_id: str, resume_text: str, job_role: Dict[str, Any],
                           company_desc: str, history_text: str, candidate_info: Dict[str, Any]) -> None:
    st.subheader("生成消息")
    message_state = st.session_state.setdefault("generated_messages", {})
    draft = message_state.get(chat_id, "")
    draft = st.text_area("消息内容", value=draft, height=180, key=f"message_draft_{chat_id}")
    col_generate, col_send = st.columns(2)

    if col_generate.button("生成建议", key=f"generate_msg_{chat_id}"):
        context = {
            "company_description": company_desc,
            "job_description": job_role.get("description", ""),
            "target_profile": job_role.get("target_profile", ""),
            "candidate_resume": resume_text or "无",
            "chat_history": history_text or "无",
            "notes": draft,
        }
        assistant_actions.upsert_candidate(
            chat_id,
            name=candidate_info.get("candidate"),
            job_applied=job_role.get("position"),
            last_message=candidate_info.get("message"),
            resume_text=resume_text,
        )
        with st.spinner("生成中..."):
            message = assistant_actions.generate_followup_message(chat_id, prompt=draft or "", context=context)
        if message:
            message_state[chat_id] = message
            st.session_state[f"message_draft_{chat_id}"] = message
            st.rerun()

    if col_send.button("发送消息", key=f"send_msg_{chat_id}"):
        content = st.session_state.get(f"message_draft_{chat_id}", "").strip()
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
            if ok:
                st.success("消息已发送")
                message_state[chat_id] = content
                assistant_actions.upsert_candidate(chat_id, last_message=content)
            else:
                st.error(f"发送失败: {payload}")


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("消息列表")
    ensure_state()
    sidebar_controls(include_config_path=False)

    base_url = st.session_state["base_url"]
    jobs = _load_jobs()
    company_desc = _load_company_description()
    limit = st.sidebar.slider("每次获取数量", min_value=5, max_value=100, value=30, step=5)

    selected_job_idx = st.session_state.get("selected_job_index", 0)
    selected_job = jobs[selected_job_idx] if jobs and 0 <= selected_job_idx < len(jobs) else {}
    if selected_job:
        sync_key = (selected_job_idx, base_url)
        if st.session_state.get("_chat_job_synced") != sync_key:
            call_api(base_url, "POST", "/chat/select-job", json={"job": selected_job})
            st.session_state["_chat_job_synced"] = sync_key

    messages = _get_messages(limit)

    if st.sidebar.button("刷新列表", key="refresh_messages_sidebar"):
        messages = _fetch_messages(base_url, limit)

    if not messages:
        st.info("暂无消息数据")
        return

    display_rows = []
    st.write(messages)

    col_select, col_refresh = st.columns([4, 1])
    chat_id = col_select.selectbox(
        "选择候选人",
        options=[row["chat_id"] for row in display_rows],
        format_func=lambda cid: next(
            (row['candidate'] for row in display_rows if row['chat_id'] == cid),
            cid,
        ),
        key="chat_selector",
    )
    if col_refresh.button("🔄", key="refresh_messages_main"):
        st.session_state.pop("messages_cache", None)
        st.session_state.pop("history_cache", None)
        st.session_state.pop("online_resume_cache", None)
        st.session_state.pop("full_resume_cache", None)
        st.rerun()

    selected_row = next((row for row in display_rows if row["chat_id"] == chat_id), None)
    if not selected_row:
        st.warning("未找到对应的候选人信息")
        return

    st.markdown(
        f"**候选人：** {selected_row['candidate'] or '未知'}  |  "
        f"**岗位：** {selected_row['job_title'] or '未填写'}  |  "
        f"**最新消息：** {selected_row['message'] or '—'}"
    )

    # Resume sections
    online_resume = render_resume_section("在线简历", base_url, chat_id, "/resume/online", "online_resume_cache")
    full_resume = render_resume_section(
        "附件简历",
        base_url,
        chat_id,
        "/resume/view_full",
        "full_resume_cache",
        request_when_missing=True,
        check_endpoint="/resume/check_full",
    )
    resume_text = "\n\n".join(filter(None, [online_resume, full_resume]))

    history_lines = render_history_section(base_url, chat_id)
    history_text = _prepare_history_text(history_lines)

    if jobs:
        job_options = [f"{role.get('id', '')} - {role.get('position', '')}" for role in jobs]
        job_index = st.selectbox(
            "选择岗位画像",
            options=list(range(len(job_options))),
            format_func=lambda i: job_options[i],
            index=st.session_state.get("selected_job_index", 0),
        )
        if job_index != st.session_state.get("selected_job_index"):
            st.session_state["selected_job_index"] = job_index
            selected_job = jobs[job_index]
            call_api(base_url, "POST", "/chat/select-job", json={"job": selected_job})
            st.session_state["_chat_job_synced"] = (job_index, base_url)
        selected_job = jobs[job_index]
    else:
        st.warning("未找到岗位配置，将使用空的岗位描述。")
        selected_job = {"description": "", "target_profile": ""}

    assistant_actions.upsert_candidate(
        chat_id,
        name=selected_row.get("candidate"),
        job_applied=selected_job.get("position"),
        last_message=selected_row.get("message"),
        resume_text=resume_text,
    )

    render_scoring_section(chat_id, selected_row, resume_text, selected_job, company_desc, history_text)
    render_message_section(base_url, chat_id, resume_text, selected_job, company_desc, history_text, selected_row)


if __name__ == "__main__":
    main()
