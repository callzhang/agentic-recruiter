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


def _fetch_recommendations(base_url: str, limit: int) -> List[Dict[str, Any]]:
    ok, payload = call_api(base_url, "GET", "/recommend/candidates", params={"limit": limit})
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


def main() -> None:
    st.title("推荐牛人")
    ensure_state()
    sidebar_controls(include_config_path=False)

    base_url = st.session_state["base_url"]
    jobs = _load_jobs()
    limit = st.sidebar.slider("每次获取数量", min_value=5, max_value=100, value=20, step=5)

    selected_job_idx = st.session_state.get("selected_job_index", 0)
    selected_job = jobs[selected_job_idx] if jobs and 0 <= selected_job_idx < len(jobs) else {}
    if selected_job:
        sync_key = (selected_job_idx, base_url)
        if st.session_state.get("_recommend_job_synced") != sync_key:
            call_api(base_url, "POST", "/recommend/select-job", json={"job": selected_job})
            st.session_state["_recommend_job_synced"] = sync_key

    if "recommend_candidates" not in st.session_state:
        _fetch_recommendations(base_url, limit)

    if st.button("刷新推荐牛人", key="refresh_recommend"):
        _fetch_recommendations(base_url, limit)

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
    st.dataframe(table_rows, use_container_width=True)

    selected_index = st.selectbox(
        "选择推荐牛人",
        options=[row["index"] for row in table_rows],
        format_func=lambda idx: f"#{idx} {table_rows[idx]['text'][:40]}",
    )

    action_col1, action_col2 = st.columns(2)

    if action_col1.button("查看在线简历", key="view_recommend_resume"):
        ok, payload = call_api(base_url, "GET", f"/recommend/candidate/{selected_index}")
        _render_response(ok, payload)

    with action_col2.form("greet_recommend_form_page"):
        greeting = st.text_area("打招呼内容 (留空使用默认话术)", key="recommend_greet_message")
        if st.form_submit_button("发送打招呼"):
            data = {"message": greeting} if greeting.strip() else None
            ok, payload = call_api(
                base_url,
                "POST",
                f"/recommend/candidate/{selected_index}/greet",
                json=data,
            )
            _render_response(ok, payload)


if __name__ == "__main__":
    main()
