"""Home page for the Streamlit multi-page console."""
from __future__ import annotations

import streamlit as st

from streamlit_shared import call_api, ensure_state, sidebar_controls


def main() -> None:
    st.set_page_config(page_title="Boss直聘控制台", layout="wide")
    ensure_state()
    sidebar_controls(include_config_path=True)

    st.title("Boss直聘智能招聘助手控制台")
    st.markdown(
        """
        欢迎使用可视化配置与控制面板：

        - 在 **Config Editor** 页面维护 `config/jobs.yaml` 中的公司与岗位信息；
        - 在 **岗位画像** 页面查看并调整岗位画像；
        - 在 **Service Console** 页面调用 Boss Service API 进行人工测试；
        - 在 **Automation Scheduler** 页面启动/停止自动化调度流程；
        - 在 **消息列表** 与 **推荐牛人** 页面直接执行常用动作。

        在开始前，请确认右侧侧边栏中的 API 地址与配置文件路径已经正确填写。
        """
    )

    base_url = st.session_state["base_url"]
    status_placeholder = st.container()
    ok, payload = call_api(base_url, "GET", "/status")
    login_payload = None
    stats_payload = None
    if ok and isinstance(payload, dict) and not payload.get("logged_in"):
        login_ok, login_payload = call_api(base_url, "POST", "/login")
        if login_ok and isinstance(login_payload, dict):
            payload["logged_in"] = login_payload.get("success", False)

    stats_ok, stats_payload = call_api(base_url, "GET", "/chat/stats")

    with status_placeholder:
        if ok and isinstance(payload, dict):
            st.success("服务状态已获取")
            cols = st.columns(4)
            cols[0].metric("状态", payload.get("status", "未知"))
            cols[1].metric("登录", "已登录" if payload.get("logged_in") else "未登录")
            cols[2].metric("通知数量", stats_payload.get("new_message_count", 0))
            cols[3].metric("通知数量", stats_payload.get("new_greet_count", 0))
            st.caption(f"数据时间: {payload.get('timestamp', '—')}")
            if login_payload and isinstance(login_payload, dict):
                st.caption(f"登录接口返回: {login_payload.get('message', login_payload)}")
        else:
            st.error(f"无法获取服务状态: {payload}")

    st.info("通过顶部页面切换不同功能区。")


if __name__ == "__main__":
    main()
