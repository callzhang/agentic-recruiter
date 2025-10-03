"""Page: recommended talents list with actions."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls


@st.cache_data(ttl=600, show_spinner="获取推荐牛人中...")
def _fetch_recommendations(limit: int) -> List[Dict[str, Any]]:
    ok, payload = call_api("GET", "/recommend/candidates", params={"limit": limit})
    if not ok:
        st.error(f"获取推荐牛人失败: {payload}")
        return []
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        st.warning("API 返回的推荐数据格式不符合预期")
        return []
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

    # Get selected job from sidebar
    selected_job = st.session_state.get("selected_job")
    if not selected_job:
        st.error("请先选择职位")
        return

    limit = st.slider("每次获取数量", min_value=5, max_value=100, value=20, step=5)

    # Sync job selection with backend
    selected_job_idx = st.session_state.get("selected_job_index", 0)
    if st.session_state.get("_recommend_job_synced") != selected_job_idx:
        call_api("POST", "/recommend/select-job", json={"job": selected_job})
        st.session_state["_recommend_job_synced"] = selected_job_idx

    # Fetch candidates
    candidates = _fetch_recommendations(limit)
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
    online_resume = None
    if st.button("查看在线简历", key="view_recommend_resume"):
        with st.spinner("获取在线简历中..."):
            online_resume = _fetch_candidate_resume(selected_index)
            
        st.text_area("在线简历", value=online_resume, height=300)

    # Extract job data for use in forms
    job_title = selected_job.get("title", "")
    company_description = selected_job.get("company_description", "")
    target_profile = selected_job.get("target_profile", "")

    with st.form("greet_recommend_form_page"):
        greeting = st.text_area("打招呼内容 (留空使用默认话术)")
        
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
                            "job_title": job_title,
                            "company_description": company_description,
                            "target_profile": target_profile
                        }
                    )
                
                if ok and payload.get("success"):
                    st.success("AI生成完成！")
                    st.info(f"生成的打招呼消息：\n{payload.get('greeting', '')}")
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
