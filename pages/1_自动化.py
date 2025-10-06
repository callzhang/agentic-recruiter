"""Page: scheduler management with single toggle button."""
from __future__ import annotations

import streamlit as st

from streamlit_shared import (
    SessionKeys,
    call_api,
    ensure_state,
    sidebar_controls,
    load_jobs,
)


def main() -> None:
    st.title("Automation Scheduler")
    ensure_state()
    sidebar_controls(include_config_path=True)

    with st.spinner("获取调度器状态..."):
        status_ok, status_payload = call_api("GET", "/automation/scheduler/status")

    running = bool(status_ok and isinstance(status_payload, dict) and status_payload.get("running"))

    if running:
        st.success("调度器正在运行")
        st.subheader("配置信息")
        config = status_payload.get("config") if isinstance(status_payload, dict) else {}
        if config:
            st.json(config, expanded=False)
        
        st.subheader("实时状态")
        status_text = f"""
**时间**: {status_payload.get('timestamp', 'N/A')}
**状态**: {status_payload.get('status_message', 'N/A')}
        """
        st.text_area("调度器状态", value=status_text.strip(), disabled=True)
    
        
        # Manual refresh button for real-time updates
        from streamlit_autorefresh import st_autorefresh
        # count = st_autorefresh(interval=5000, key="scheduler_status_refresh")
        # st.write(f"刷新次数: {count}")
        
        if st.button("停止调度器", key="scheduler_toggle"):
            with st.spinner("停止调度器..."):
                ok, payload = call_api("POST", "/automation/scheduler/stop")
            if ok:
                st.success("调度器已停止")
                st.rerun()
            else:
                st.error(f"停止失败: {payload}")
    else:
        st.info("调度器未运行，配置参数后点击按钮启动。")
        selected_job_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
        jobs = load_jobs()
        job = jobs[selected_job_idx]
        st.markdown(f"**当前岗位: {job.get('position')}**")

        check_recommend_candidates = st.checkbox("检查推荐候选人", value=False)
        if check_recommend_candidates:
            check_recommend_candidates_limit = st.number_input(
                "推荐候选人数量",
                value=20,
                min_value=1,
                max_value=100,
                step=1,
            )
            match_threshold = st.number_input(
                "匹配阈值(1-10)",
                value=9.0,
                min_value=7.0,
                max_value=10.0,
                step=0.5,
            )
        else:
            check_recommend_candidates_limit = 20
            match_threshold = 0.9

        check_new_chats = st.checkbox("检查新聊天", value=job.get("check_new_chats", False))
        check_followups = st.checkbox("检查跟进", value=job.get("check_followups", False))
        any_checks = any([check_recommend_candidates, check_new_chats, check_followups])

        submitted = st.button("启动调度器", disabled=not any_checks)
        if submitted:
            payload = {
                "job": job,
                "check_recommend_candidates": check_recommend_candidates,
                "check_recommend_candidates_limit": check_recommend_candidates_limit,
                "match_threshold": match_threshold,
                "check_new_chats": check_new_chats,
                "check_followups": check_followups,
            }
            with st.spinner("启动调度器..."):
                ok, response = call_api("POST", "/automation/scheduler/start", json=payload)
            if ok:
                st.success(f"调度器已启动: {response}")
                st.rerun()
            else:
                st.error(f"启动失败: {response}")


if __name__ == "__main__":
    main()
