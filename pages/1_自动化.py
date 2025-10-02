"""Page: scheduler management with single toggle button."""
from __future__ import annotations

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls


def main() -> None:
    st.title("Automation Scheduler")
    ensure_state()
    sidebar_controls(include_config_path=True)

    with st.spinner("获取调度器状态..."):
        status_ok, status_payload = call_api("GET", "/automation/scheduler/status")

    running = bool(status_ok and isinstance(status_payload, dict) and status_payload.get("running"))

    if running:
        st.success("调度器正在运行")
        config = status_payload.get("config") if isinstance(status_payload, dict) else {}
        if config:
            st.json(config)
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
        with st.form("scheduler_start_form"):
            role_id = st.text_input("岗位 ID", value="default", key="scheduler_role_id")
            criteria_path = st.text_input(
                "画像配置路径",
        value=st.session_state.get("criteria_path", "config/jobs.yaml"),
                key="scheduler_criteria",
            )
            poll_interval = st.number_input("主动沟通轮询 (秒)", min_value=30, value=120, step=30)
            recommend_interval = st.number_input("推荐轮询 (秒)", min_value=120, value=600, step=60)
            followup_interval = st.number_input("跟进周期 (秒)", min_value=600, value=3600, step=300)
            report_interval = st.number_input("报表周期 (秒)", min_value=3600, value=604800, step=3600)
            inbound_limit = st.number_input("主动沟通批次", min_value=5, value=40, step=5)
            recommend_limit = st.number_input("推荐批次", min_value=5, value=20, step=5)
            greeting_template = st.text_area("打招呼模板 (可选)", key="scheduler_greeting")

            submitted = st.form_submit_button("启动调度器")
            if submitted:
                payload = {
                    "role_id": role_id,
                    "criteria_path": criteria_path,
                    "poll_interval": int(poll_interval),
                    "recommend_interval": int(recommend_interval),
                    "followup_interval": int(followup_interval),
                    "report_interval": int(report_interval),
                    "inbound_limit": int(inbound_limit),
                    "recommend_limit": int(recommend_limit),
                }
                if greeting_template.strip():
                    payload["greeting_template"] = greeting_template.strip()
                with st.spinner("启动调度器..."):
                    ok, response = call_api(
                        base_url,
                        "POST",
                        "/automation/scheduler/start",
                        json=payload,
                    )
                if ok:
                    st.success("调度器已启动")
                    st.rerun()
                else:
                    st.error(f"启动失败: {response}")


if __name__ == "__main__":
    main()
