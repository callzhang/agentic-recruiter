"""Page: recommended talents list with actions."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls, SessionKeys

@st.spinner("切换职位中...")
def _select_recommend_job(job_title: str) -> None:
    # @self.app.post('/recommend/select-job')
    ok, payload = call_api("POST", "/recommend/select-job", json={"job_title": job_title})
    if not ok:
        st.error(f"选择职位失败: {payload}")
        raise ValueError(f"选择职位失败: {payload}")
    st.session_state[SessionKeys.RECOMMEND_JOB_SYNCED] = job_title

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

    limit = st.slider("每次获取数量", min_value=5, max_value=100, value=20, step=5)

    # Sync job selection with backend
    selected_job_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
    job_title = selected_job_info.get("position")
    
    if st.session_state.get(SessionKeys.RECOMMEND_JOB_SYNCED) != selected_job_idx:
        _select_recommend_job(job_title)
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


    with st.form("analyze_recommend_form_page"):
        
        analysis_notes = st.text_area(
            'analysis_notes', 
            value=st.session_state.get("analysis_notes", ""),
            placeholder="分析说明 (可选)", 
            label_visibility="collapsed"
        )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.form_submit_button("🤖 AI分析", key="analyze_candidate"):
                if not online_resume:
                    online_resume = _fetch_candidate_resume(selected_index)
                
                # Prepare analysis context
                context = {
                    "job_info": selected_job_info,
                    "candidate_description": candidates[selected_index].get("text", ""),
                    "candidate_resume": online_resume,
                    "chat_history": "无",  # No chat history for recommended candidates
                    "notes": analysis_notes,
                }
                
                with st.spinner("AI正在分析候选人..."):
                    ok, payload = call_api(
                        "POST",
                        "/assistant/analyze-candidate",
                        json=context
                    )
                
                if ok and payload.get("success"):
                    # Store analysis results in session state
                    analysis_result = payload.get("analysis")
                    st.session_state.setdefault("analysis_results", {})[selected_index] = analysis_result
                    st.success("AI分析完成！")
                    st.rerun()  # Refresh to show the analysis results
                else:
                    error = payload.get("error") if isinstance(payload, dict) else str(payload)
                    st.error(f"AI分析失败: {error}")
        
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
    analysis_result = st.session_state.get("analysis_results", {}).get(selected_index)
    if analysis_result:
        st.subheader("🤖 AI分析结果")
        cols = st.columns(4)
        cols[0].metric("技能匹配", analysis_result.get("skill", "—"))
        cols[1].metric("创业契合", analysis_result.get("startup_fit", "—"))
        cols[2].metric("加入意愿", analysis_result.get("willingness", "—"))
        cols[3].metric("综合评分", analysis_result.get("overall", "—"))
        st.markdown(f"**分析总结：** {analysis_result.get('summary', '—')}")


if __name__ == "__main__":
    main()
