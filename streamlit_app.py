"""Streamlit console for Boss Zhipin automation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import streamlit as st
import yaml

DEFAULT_BASE_URL = os.environ.get("BOSS_SERVICE_BASE_URL", "http://127.0.0.1:5001")
DEFAULT_CRITERIA_PATH = Path(os.environ.get("BOSS_CRITERIA_PATH", "jobs/criteria.yaml"))


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        st.warning(f"配置文件未找到: {path}")
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"解析 {path} 失败: {exc}")
        return {}


def call_api(base_url: str, method: str, path: str, **kwargs) -> Optional[Any]:
    url = base_url.rstrip("/") + path
    try:
        response = requests.request(method, url, timeout=30, **kwargs)
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text
    except requests.RequestException as exc:
        st.error(f"API调用失败: {exc}")
        return None
    except json.JSONDecodeError:
        st.error("返回数据不是有效的JSON")
        return None


def render_yaml_section(data: Dict[str, Any]) -> None:
    st.header("岗位配置总览")
    if not data:
        st.info("暂无配置内容")
        return

    company = data.get("company")
    if company:
        with st.expander("公司信息", expanded=True):
            st.json(company)

    qa = data.get("qa")
    if qa:
        with st.expander("常见问题解答", expanded=False):
            st.json(qa)

    contacts = data.get("contacts")
    if contacts:
        with st.expander("联系人", expanded=False):
            st.json(contacts)

    roles = data.get("roles") or []
    if roles:
        role_names = [role.get("position") or role.get("id", f"role-{idx}") for idx, role in enumerate(roles)]
        idx = st.selectbox("选择岗位", options=list(range(len(role_names))), format_func=lambda i: role_names[i])
        role = roles[idx]
        st.subheader(f"岗位详情 - {role_names[idx]}")
        st.json(role)
    else:
        st.info("roles 未配置")


def render_service_controls(base_url: str) -> None:
    st.header("Boss Service 控制台")
    cols = st.columns(3)
    if cols[0].button("检查服务状态"):
        data = call_api(base_url, "GET", "/status")
        if data is not None:
            st.write(data)
    if cols[1].button("获取消息列表 (前10)"):
        data = call_api(base_url, "GET", "/chat/dialogs", params={"limit": 10})
        if data is not None:
            st.write(data)
    if cols[2].button("推荐候选人 (前10)"):
        data = call_api(base_url, "GET", "/recommend/candidates", params={"limit": 10})
        if data is not None:
            st.write(data)

    with st.expander("发送消息", expanded=False):
        with st.form("send_message_form"):
            chat_id = st.text_input("Chat ID")
            message = st.text_area("消息内容")
            submitted = st.form_submit_button("发送")
            if submitted:
                if not chat_id or not message:
                    st.warning("Chat ID 和消息内容均不能为空")
                else:
                    data = call_api(base_url, "POST", f"/chat/{chat_id}/send", json={"message": message})
                    if data is not None:
                        st.write(data)

    with st.expander("求简历 / 查看简历", expanded=False):
        with st.form("request_resume_form"):
            chat_id_req = st.text_input("Chat ID", key="request_resume_id")
            submitted_req = st.form_submit_button("求简历")
            if submitted_req:
                if not chat_id_req:
                    st.warning("Chat ID 不能为空")
                else:
                    data = call_api(base_url, "POST", "/resume/request", json={"chat_id": chat_id_req})
                    if data is not None:
                        st.write(data)
        with st.form("view_resume_form"):
            chat_id_view = st.text_input("Chat ID", key="view_resume_id")
            submitted_view = st.form_submit_button("查看在线简历")
            if submitted_view:
                if not chat_id_view:
                    st.warning("Chat ID 不能为空")
                else:
                    data = call_api(base_url, "POST", "/resume/online", json={"chat_id": chat_id_view})
                    if data is not None:
                        st.write(data)

    with st.expander("推荐候选人打招呼", expanded=False):
        with st.form("greet_recommend_form"):
            candidate_index = st.number_input("候选人索引", min_value=0, value=0, step=1)
            greeting = st.text_area("打招呼内容")
            submitted_greet = st.form_submit_button("发送打招呼")
            if submitted_greet:
                payload = {"message": greeting} if greeting else None
                data = call_api(base_url, "POST", f"/recommend/candidate/{int(candidate_index)}/greet", json=payload)
                if data is not None:
                    st.write(data)


def render_scheduler_controls(base_url: str) -> None:
    st.header("自动化调度器")
    cols = st.columns([1, 1, 1])
    if cols[0].button("查看调度器状态"):
        data = call_api(base_url, "GET", "/automation/scheduler/status")
        if data is not None:
            st.write(data)

    with st.form("scheduler_start_form"):
        st.subheader("启动调度器")
        role_id = st.text_input("岗位ID", value="default")
        criteria_path = st.text_input("画像配置路径", value=str(DEFAULT_CRITERIA_PATH))
        poll_interval = st.number_input("主动沟通轮询(秒)", min_value=30, value=120, step=30)
        recommend_interval = st.number_input("推荐轮询(秒)", min_value=120, value=600, step=60)
        followup_interval = st.number_input("跟进周期(秒)", min_value=600, value=3600, step=300)
        report_interval = st.number_input("报表周期(秒)", min_value=3600, value=604800, step=3600)
        inbound_limit = st.number_input("主动沟通批次", min_value=5, value=40, step=5)
        recommend_limit = st.number_input("推荐批次", min_value=5, value=20, step=5)
        greeting_template = st.text_area("自定义打招呼", placeholder="留空使用默认话术")
        submitted_sched = st.form_submit_button("启动调度")
        if submitted_sched:
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
            data = call_api(base_url, "POST", "/automation/scheduler/start", json=payload)
            if data is not None:
                st.write(data)

    if cols[1].button("停止调度器"):
        data = call_api(base_url, "POST", "/automation/scheduler/stop")
        if data is not None:
            st.write(data)


def main() -> None:
    st.set_page_config(page_title="Boss直聘自动化控制台", layout="wide")
    st.title("Boss直聘智能招聘助手控制台")

    base_url = st.sidebar.text_input("API 服务地址", value=DEFAULT_BASE_URL)
    criteria_path_input = st.sidebar.text_input("配置文件路径", value=str(DEFAULT_CRITERIA_PATH))

    config_path = Path(criteria_path_input).expanduser().resolve()
    yaml_data = load_yaml(config_path)
    render_yaml_section(yaml_data)

    st.divider()
    render_service_controls(base_url)

    st.divider()
    render_scheduler_controls(base_url)


if __name__ == "__main__":
    main()
