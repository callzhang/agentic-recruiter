"""Page: manage role profiles with tabbed editing."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, Set

import streamlit as st
import yaml

from streamlit_shared import (
    auto_save_config,
    ensure_dict,
    ensure_list,
    ensure_state,
    get_config_data,
    sidebar_controls,
    SessionKeys,
)


@st.dialog("确认删除岗位")
def confirm_delete_role_dialog(role_name: str, role_idx: int, roles: list):
    """显示删除岗位确认对话框"""
    st.warning(f"⚠️ 您确定要删除岗位 **{role_name}** 吗？")
    st.write("此操作无法撤销！")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 确认删除", type="primary", width="stretch"):
            roles.pop(role_idx)
            st.success(f"岗位 '{role_name}' 已删除")
            st.rerun()
    with col2:
        if st.button("❌ 取消", width="stretch"):
            st.rerun()


def _generate_role_id(position: str, existing_ids: Set[str]) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", position.strip()).strip("_").lower()
    if not slug:
        slug = "role"
    candidate = slug
    suffix = 1
    while candidate in existing_ids:
        candidate = f"{slug}_{suffix}"
        suffix += 1
    return candidate


def _create_role(position: str, desired_id: str | None, existing_ids: Set[str]) -> Dict[str, Any]:
    position_clean = position.strip()
    desired = (desired_id or "").strip()
    if desired and desired not in existing_ids:
        role_id = desired
    else:
        role_id = _generate_role_id(position_clean or desired or "role", existing_ids)
    existing_ids.add(role_id)
    return {
        "id": role_id,
        "position": position_clean,
        "background": "",
        "responsibilities": "",
        "requirements": "",
        "description": "",
        "target_profile": "",
        "keywords": {"positive": [], "negative": []},
    }


def _edit_role(role: Dict[str, Any], idx: int) -> None:
    # Use stable keys that don't change with role content
    role["id"] = st.text_input(
        "岗位 ID",
        value=str(role.get("id", "")),
        key=f"role_id_{idx}",  # More stable key
    )
    role["position"] = st.text_input(
        "岗位名称",
        value=str(role.get("position", "")),
        key=f"role_position_{idx}",  # More stable key
    )
    role["background"] = st.text_area(
        "岗位背景",
        value=str(role.get("background", "")),
        key=f"role_background_{idx}",  # More stable key
    )
    role["responsibilities"] = st.text_area(
        "岗位职责",
        value=str(role.get("responsibilities", "")),
        key=f"role_responsibilities_{idx}",  # More stable key
    )
    role["requirements"] = st.text_area(
        "任职要求",
        value=str(role.get("requirements", "")),
        key=f"role_requirements_{idx}",  # More stable key
    )
    role["description"] = st.text_area(
        "岗位概述",
        value=str(role.get("description", "")),
        key=f"role_description_{idx}",  # More stable key
    )
    role["target_profile"] = st.text_area(
        "理想人选画像",
        value=str(role.get("target_profile", "")),
        key=f"role_target_{idx}",  # More stable key
    )

    keywords = ensure_dict(role, "keywords")
    st.markdown("**关键词**")
    
    # Ensure keywords are lists of strings
    positive_keywords = keywords.get("positive", [])
    negative_keywords = keywords.get("negative", [])
    
    keywords["positive"] = st.multiselect(
        label="正向关键词",
        # text="输入关键词后回车",
        options=positive_keywords,
        default=positive_keywords,
        key=f"role_{idx}_keywords_positive",
        accept_new_options=True,
    )
    keywords["negative"] = st.multiselect(
        label="负向关键词",
        # text="输入关键词后回车", 
        options=negative_keywords,
        default=negative_keywords,
        key=f"role_{idx}_keywords_negative",
        accept_new_options=True,
    )

    st.markdown("**其它字段 (YAML)**")
    handled = {
        "id",
        "position",
        "background",
        "responsibilities",
        "requirements",
        "description",
        "target_profile",
        "keywords",
        "extra",
    }
    extra = {k: deepcopy(v) for k, v in role.items() if k not in handled}
    extra_yaml = yaml.safe_dump(extra, allow_unicode=True, sort_keys=False) if extra else ""
    updated_extra = st.text_area(
        "其它配置",
        value=extra_yaml,
        key=f"role_{idx}_extra",
        height=220,
        placeholder="请输入其它配置，格式为 YAML",
    )
    role['extra'] = updated_extra
    for key in list(role.keys()):
        if key not in handled:
            role.pop(key)


def main() -> None:
    st.title("岗位画像", help="岗位画像用于描述招聘岗位的背景、职责、要求、概述、理想人选画像等信息。")
    ensure_state()
    sidebar_controls(include_config_path=True)

    config, path = get_config_data()
    st.caption(f"配置文件: `{path}`")
    st.caption("提示：岗位信息编辑后将自动保存。")
    roles = ensure_list(config, "roles")
    existing_ids: Set[str] = {str(role.get("id", "")) for role in roles if role.get("id")}

    if not roles:
        st.info("尚未配置岗位画像。请填写信息后点击新增按钮。")
        new_position = st.text_input("新岗位名称", key="first_role_position")
        new_role_id = st.text_input("岗位 ID (可选)", key="first_role_id")
        if st.button("新增岗位", key="add_first_role"):
            if not new_position.strip():
                st.warning("岗位名称不能为空")
            else:
                roles.append(_create_role(new_position, new_role_id, existing_ids))
                st.rerun()
        return

    # Track active tab in session state
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = 0
    
    tab_titles = [
        role.get("position") or role.get("id") or f"岗位#{idx + 1}"
        for idx, role in enumerate(roles)
    ]
    tabs = st.tabs(tab_titles + ["➕ 新增岗位"])
    
    # Use session state to maintain active tab
    if st.session_state.active_tab >= len(tabs):
        st.session_state.active_tab = 0

    for idx, tab in enumerate(tabs[:-1]):
        with tab:
            # # Track if this tab was clicked
            # if st.session_state.get(f"tab_clicked_{idx}", False):
            #     st.session_state.active_tab = idx
            #     st.session_state[f"tab_clicked_{idx}"] = False
            
            _edit_role(roles[idx], idx)
            role_name = roles[idx].get("position") or roles[idx].get("id") or f"岗位#{idx + 1}"
            if st.button("💾 保存", key=f"role_save_{idx}", type="primary", width="stretch"):
                auto_save_config(config)
                st.success(f"岗位『{role_name}』已保存")

    with tabs[-1]:
        st.markdown("### 新增岗位画像")
        idx = len(roles)
        new_role = {}
        _edit_role(new_role, idx)
        if st.button("💾 保存新岗位", key="save_new_role", type="primary", width="stretch"):
            new_position = new_role.get("position")
            if not new_position.strip():
                st.warning("岗位名称不能为空")
            else:
                roles.append(_create_role(new_position, new_role_id, existing_ids))
                auto_save_config(config)
                st.success("新岗位已保存")


if __name__ == "__main__":
    main()
