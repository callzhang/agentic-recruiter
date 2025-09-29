"""Company introduction page with Markdown editing."""
from __future__ import annotations

from pathlib import Path
import time

import streamlit as st

from streamlit_shared import ensure_state, sidebar_controls

COMPANY_PATH = Path("config/company.md")


def load_company_markdown() -> str:
    if COMPANY_PATH.exists():
        return COMPANY_PATH.read_text(encoding="utf-8")
    COMPANY_PATH.parent.mkdir(parents=True, exist_ok=True)
    return ""


def save_company_markdown(content: str) -> None:
    COMPANY_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPANY_PATH.write_text(content, encoding="utf-8")


def main() -> None:
    st.title("公司介绍")
    ensure_state()
    sidebar_controls(include_config_path=False)

    if "company_md_content" not in st.session_state:
        original = load_company_markdown()
        st.session_state["company_md_content"] = original
        st.session_state["_company_md_last_saved"] = original
        st.session_state["_company_md_last_rendered"] = original
        st.session_state.setdefault("company_md_editor", original)
    if "company_md_edit_toggle" not in st.session_state:
        st.session_state["company_md_edit_toggle"] = True

    content = st.session_state["company_md_content"]

    preview_container = st.container()

    def render_preview(text: str) -> None:
        if text.strip():
            preview_container.markdown(text)
        else:
            preview_container.info("暂无公司介绍内容，请在下方编辑。")

    render_preview(st.session_state.get("_company_md_last_rendered", content))

    edit_mode = st.toggle("编辑模式", key="company_md_edit_toggle")

    if edit_mode:
        new_content = st.text_area(
            "公司介绍 (Markdown)",
            key="company_md_editor",
            height=600,
        )
        if new_content != st.session_state["company_md_content"]:
            st.session_state["company_md_content"] = new_content
            time.sleep(1)
            render_preview(new_content)
            st.session_state["_company_md_last_rendered"] = new_content
            if new_content != st.session_state.get("_company_md_last_saved"):
                save_company_markdown(new_content)
                st.session_state["_company_md_last_saved"] = new_content
                st.toast("公司介绍已自动保存", icon="💾")
    else:
        st.info("切换到编辑模式以修改内容。")
        st.text_area(
            "公司介绍 (Markdown)",
            value=st.session_state["company_md_content"],
            height=600,
            disabled=True,
            key="company_md_readonly",
        )
        render_preview(st.session_state["company_md_content"])

    if st.button("重新加载文件", key="company_md_reload"):
        refreshed = load_company_markdown()
        st.session_state["company_md_content"] = refreshed
        st.session_state["_company_md_last_saved"] = refreshed
        st.session_state["_company_md_last_rendered"] = refreshed
        st.session_state["company_md_editor"] = refreshed
        render_preview(refreshed)


if __name__ == "__main__":
    main()
