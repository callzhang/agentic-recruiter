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

    content = load_company_markdown()

    edit_mode = st.toggle("编辑模式", key="company_md_edit_toggle", value=False)

    if edit_mode:
        new_content = st.text_area(
            "公司介绍 (Markdown)",
            value=content,
            key="company_md_editor",
            height=600,
        )
        if new_content != content:
            content = new_content
            time.sleep(1)
            save_company_markdown(new_content)
            st.toast("公司介绍已自动保存", icon="💾")
    else:
        st.markdown(content)


if __name__ == "__main__":
    main()
