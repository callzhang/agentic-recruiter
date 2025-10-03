"""Page: recommended talents list with actions."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls


def _load_jobs() -> List[Dict[str, Any]]:
    cache = st.session_state.get("_jobs_cache")
    if isinstance(cache, list):
        return cache
    return []


def _fetch_recommendations(limit: int) -> List[Dict[str, Any]]:
    ok, payload = call_api("GET", "/recommend/candidates", params={"limit": limit})
    if not ok:
        st.error(f"获取推荐牛人失败: {payload}")
        return []
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        st.warning("API 返回的推荐数据格式不符合预期")
        return []
    st.session_state["recommend_candidates"] = candidates
    return candidates


def _render_response(ok: bool, payload: Any) -> None:
    if ok:
        st.success("操作成功")
        if isinstance(payload, (dict, list)):
            st.json(payload)
        else:
            st.code(str(payload))
    else:
        st.error(f"操作失败: {payload}")

@st.cache_data(show_spinner="获取在线简历中...")
def _fetch_candidate_resume(index: int) -> str:
    ok, payload = call_api("GET", f"/recommend/candidate/{index}")
    if ok and payload.get("success"):
        return payload['text']
    return ""

def main() -> None:
    st.title("推荐牛人")
    ensure_state()
    sidebar_controls(include_config_path=False, include_job_selector=True)

    jobs = _load_jobs()
    limit = st.sidebar.slider("每次获取数量", min_value=5, max_value=100, value=20, step=5)

    # selected_job is now set by sidebar_controls
    selected_job = st.session_state.get("selected_job")
    selected_job_idx = st.session_state.get("selected_job_index", 0)
    
    if selected_job:
        sync_key = selected_job_idx
        if st.session_state.get("_recommend_job_synced") != sync_key:
            call_api("POST", "/recommend/select-job", json={"job": selected_job})
            st.session_state["_recommend_job_synced"] = sync_key

    if "recommend_candidates" not in st.session_state:
        _fetch_recommendations(limit)

    if st.button("刷新推荐牛人", key="refresh_recommend"):
        _fetch_recommendations(limit)

    candidates = st.session_state.get("recommend_candidates", [])
    if not candidates:
        st.info("暂无推荐牛人")
        return

    table_rows = []
    for idx, item in enumerate(candidates):
        table_rows.append(
            {
                "index": idx,
                "viewed": item.get("viewed"),
                "text": item.get("text", "").strip()[:200],
            }
        )
    st.dataframe(table_rows, width="stretch", hide_index=True)

    selected_index = st.selectbox(
        "选择推荐牛人",
        options=[row["index"] for row in table_rows],
        format_func=lambda idx: f"#{idx+1} {table_rows[idx]['text'][:40]}",
    )
    online_resume = None
    if st.button("查看在线简历", key="view_recommend_resume"):
        with st.spinner("获取在线简历中..."):
            online_resume = _fetch_candidate_resume(selected_index)
            
        st.text_area("在线简历", value=online_resume, height=300)

    with st.form("greet_recommend_form_page"):
        # Initialize greeting with session state or empty string
        greeting_key = "recommend_greet_message"
        if greeting_key not in st.session_state:
            st.session_state[greeting_key] = ""
        
        greeting = st.text_area(
            "打招呼内容 (留空使用默认话术)", 
            value=st.session_state[greeting_key],
            key=greeting_key
        )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.form_submit_button("🤖 AI生成", key="generate_greeting"):
                if not online_resume:
                    online_resume = _fetch_candidate_resume(selected_index)
                
                candidate_info = {
                    "name": table_rows[selected_index].get("name", "候选人"),
                    "title": table_rows[selected_index].get("title", ""),
                    "summary": table_rows[selected_index].get("text", "")[:200] + "...",
                    "online_resume": online_resume
                }
                
                job_info = {
                    "title": st.session_state.get("selected_job", {}).get("title", ""),
                    "company_description": st.session_state.get("selected_job", {}).get("company_description", ""),
                    "target_profile": st.session_state.get("selected_job", {}).get("target_profile", "")
                }
                
                with st.spinner("AI正在生成个性化打招呼消息..."):
                    ok, payload = call_api(
                        "POST",
                        f"/recommend/candidate/{selected_index}/generate-greeting",
                        json={
                            "candidate_info": candidate_info,
                            "job_info": job_info
                        }
                    )
                
                if ok and payload.get("success"):
                    # Store generated greeting in session state for next render
                    st.session_state[greeting_key] = payload.get("greeting", "")
                    st.success("AI生成完成！")
                    st.rerun()
                else:
                    st.error(f"AI生成失败: {payload.get('error', '未知错误')}")
        
        with col2:
            if st.form_submit_button("发送打招呼"):
                data = {"message": greeting} if greeting.strip() else None
                ok, payload = call_api(
                    "POST",
                    f"/recommend/candidate/{selected_index}/greet",
                    json=data,
                )
                _render_response(ok, payload)


if __name__ == "__main__":
    main()
