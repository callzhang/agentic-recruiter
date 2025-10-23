"""Page: recommended talents list with actions."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls, SessionKeys, get_selected_job

@st.spinner("切换职位中...")
def _select_recommend_job(job_title: str) -> None:
    # @self.app.post('/recommend/select-job')
    ok, payload = call_api("POST", "/recommend/select-job", json={"job_title": job_title})
    if not ok:
        st.error(f"选择职位失败: {payload}")
        raise ValueError(f"选择职位失败: {payload}")
    # Job selection completed

@st.cache_data(ttl=300, show_spinner="获取推荐牛人中...")
def _fetch_recommended_candidate(limit: int) -> List[Dict[str, Any]]:
    ok, payload = call_api("GET", "/recommend/candidates", params={"limit": limit})
    if not ok:
        st.error(f"获取推荐牛人失败: {payload}")
        raise ValueError(f"获取推荐牛人失败: {payload}")
    return payload if isinstance(payload, list) else []


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
    """Fetch candidate resume. API now returns dict with 'text' directly."""
    ok, payload = call_api("GET", f"/recommend/candidate/{index}/resume")
    if not ok:
        raise ValueError(f"API 调用失败")
    if not isinstance(payload, dict):
        raise ValueError(f"响应格式错误: {payload}")
    return payload.get('text', '')

def main() -> None:
    st.title("推荐牛人")
    ensure_state()
    sidebar_controls(include_config_path=False, include_job_selector=True)

    # Get selected job from cached functions
    selected_job_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
    selected_job_info = get_selected_job(selected_job_idx)
    if not selected_job_info:
        st.error("请先选择职位")
        return

    limit = st.sidebar.slider("推荐牛人获取数量", min_value=5, max_value=100, value=20, step=5)

    # Sync job selection with backend
    job_title = selected_job_info.get("position")
    
    # Always sync job selection with backend
    _select_recommend_job(job_title)

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


    with st.form("analyze_recommend_form_page"):
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.form_submit_button("🤖 AI分析", key="analyze_candidate"):
                if not online_resume:
                    online_resume = _fetch_candidate_resume(selected_index)
                
                # Prepare analysis context
                context = {
                    "job_info": selected_job_info,
                    "candidate_summary": candidates[selected_index].get("text", ""),
                    "candidate_resume": online_resume,
                    "chat_history": "无",  # No chat history for recommended candidates
                }
                
                with st.spinner("AI正在分析候选人..."):
                    ok, payload = call_api(
                        "POST",
                        "/assistant/analyze-candidate",
                        json=context
                    )
                
                if ok:
                    # Store analysis results in session state
                    st.session_state.setdefault(SessionKeys.ANALYSIS_RESULTS, {})[selected_index] = payload
                    st.success("AI分析完成！")
                    st.rerun()  # Refresh to show the analysis results
                else:
                    st.error(f"AI分析失败: {payload}")
        
        with col2:
            if st.form_submit_button("发送打招呼"):
                # Use default greeting since we're now focused on analysis
                data = {"message": ""}  # Empty message will use default greeting
                ok, payload = call_api(
                    "POST",
                    f"/recommend/candidate/{selected_index}/greet",
                    json=data,
                )
                _render_response(ok, payload)
    
    # Display analysis results if available
    analysis_result = st.session_state.get(SessionKeys.ANALYSIS_RESULTS, {}).get(selected_index)
    if analysis_result:
        st.subheader("🤖 AI分析结果")
        cols = st.columns(4)
        cols[0].metric("技能匹配", analysis_result.get("skill", "—"))
        cols[1].metric("创业契合", analysis_result.get("startup_fit", "—"))
        cols[2].metric("基础背景", analysis_result.get("background", "—"))
        cols[3].metric("综合评分", analysis_result.get("overall", "—"))
        st.markdown(f"**分析总结：** {analysis_result.get('summary', '—')}")
        st.markdown(f"**后续沟通策略：** {analysis_result.get('followup_tips', '—')}")


if __name__ == "__main__":
    main()
