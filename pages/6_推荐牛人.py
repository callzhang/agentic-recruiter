"""Page: recommended talents list with actions."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls, SessionKeys

@st.spinner("选择职位中...")
def _select_recommend_job(job_title: str) -> None:
    # @self.app.post('/chat/select-job')
    ok, payload = call_api("POST", "/recommend/select-job", json={"job_title": job_title})
    if not ok:
        st.error(f"选择职位失败: {payload}")
        raise ValueError(f"选择职位失败: {payload}")
    st.session_state["_recommend_job_synced"] = job_title

@st.cache_data(ttl=300, show_spinner="获取推荐牛人中...")
def _fetch_recommended_candidate(limit: int) -> List[Dict[str, Any]]:
    ok, payload = call_api("GET", "/recommend/candidates", params={"limit": limit})
    if not ok:
        st.error(f"获取推荐牛人失败: {payload}")
        raise ValueError(f"获取推荐牛人失败: {payload}")
    candidates = payload.get("candidates") or []
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
    raise ValueError(f"获取在线简历失败: {payload}")

def main() -> None:
    st.title("推荐牛人")
    ensure_state()
    sidebar_controls(include_config_path=False, include_job_selector=True)

    # Get selected job from sidebar
    selected_job_info = st.session_state.get(SessionKeys.SELECTED_JOB)
    if not selected_job_info:
        st.error("请先选择职位")
        return
    
    _select_recommend_job(selected_job_info.get("position"))

    limit = st.slider("每次获取数量", min_value=5, max_value=100, value=20, step=5)

    # Sync job selection with backend
    selected_job_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
    job_title = selected_job_info.get("position")
    
    if st.session_state.get(SessionKeys.RECOMMEND_JOB_SYNCED) != selected_job_idx:
        call_api("POST", "/recommend/select-job", json={"job": selected_job_info})
        st.session_state[SessionKeys.RECOMMEND_JOB_SYNCED] = selected_job_idx

    # Fetch candidates
    candidates = _fetch_recommended_candidate(limit)
    if not candidates:
        st.info("暂无推荐牛人")
        return

    # Display candidates
    st.dataframe(candidates, width="stretch", hide_index=True)

    # Select candidate
    selected_index = st.selectbox(
        "选择推荐牛人",
        options=list(range(len(candidates))),
        format_func=lambda idx: f"#{idx+1} {candidates[idx].get('text', '')[:40]}",
    )
    online_resume = st.session_state.get(SessionKeys.CACHED_ONLINE_RESUME, None)
    if st.button("查看在线简历", key="view_recommend_resume"):
        with st.spinner("获取在线简历中..."):
            online_resume = _fetch_candidate_resume(selected_index)
            st.session_state[SessionKeys.CACHED_ONLINE_RESUME] = online_resume
        st.text_area("在线简历", value=online_resume, height=300)


    with st.form("greet_recommend_form_page"):
        # Initialize greeting from session state or empty
        greeting_key = SessionKeys.RECOMMEND_GREET_MESSAGE
        if greeting_key not in st.session_state:
            st.session_state[greeting_key] = ""
        
        greeting = st.text_area(
            'greet_text', 
            value=st.session_state[greeting_key],
            placeholder="打招呼内容 (留空使用默认话术)", 
            label_visibility="collapsed"
        )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.form_submit_button("🤖 AI生成", key="generate_greeting"):
                if not online_resume:
                    online_resume = _fetch_candidate_resume(selected_index)
                
                with st.spinner("AI正在生成个性化打招呼消息..."):
                    ok, payload = call_api(
                        "POST",
                        f"/recommend/candidate/{selected_index}/generate-greeting",
                        json={
                            "candidate_name": candidates[selected_index].get("name"),
                            "candidate_title": candidates[selected_index].get("title"),
                            "candidate_summary": candidates[selected_index].get("text"),
                            "candidate_resume": online_resume,
                            "job_info": selected_job_info,
                        }
                    )
                
                if ok and payload.get("success"):
                    # Store generated greeting in session state
                    generated_greeting = payload.get('greeting', '')
                    st.session_state[greeting_key] = generated_greeting
                    st.success("AI生成完成！")
                    st.rerun()  # Refresh to show the greeting in the text area
                else:
                    st.error(f"AI生成失败: {payload}")
        
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
