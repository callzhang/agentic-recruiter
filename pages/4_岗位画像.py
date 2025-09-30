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
)
from streamlit_tags import st_tags


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
        "communication": {
            "greeting_templates": [],
            "followup_templates": [],
        },
        "keywords": {"positive": [], "negative": []},
    }


def _edit_role(role: Dict[str, Any], idx: int) -> None:
    role["id"] = st.text_input(
        "岗位 ID",
        value=str(role.get("id", "")),
        key=f"role_{idx}_id",
    )
    role["position"] = st.text_input(
        "岗位名称",
        value=str(role.get("position", "")),
        key=f"role_{idx}_position",
    )
    role["background"] = st.text_area(
        "岗位背景",
        value=str(role.get("background", "")),
        key=f"role_{idx}_background",
    )
    role["responsibilities"] = st.text_area(
        "岗位职责",
        value=str(role.get("responsibilities", "")),
        key=f"role_{idx}_responsibilities",
    )
    role["requirements"] = st.text_area(
        "任职要求",
        value=str(role.get("requirements", "")),
        key=f"role_{idx}_requirements",
    )
    role["description"] = st.text_area(
        "岗位概述",
        value=str(role.get("description", "")),
        key=f"role_{idx}_description",
    )
    role["target_profile"] = st.text_area(
        "理想人选画像",
        value=str(role.get("target_profile", "")),
        key=f"role_{idx}_target",
    )

    comms = ensure_dict(role, "communication")
    st.markdown("**沟通设置**")
    comms["greeting_templates"] = [
        line.strip()
        for line in st.text_area(
            "打招呼模板 (每行一条)",
            value="\n".join(comms.get("greeting_templates", [])),
            key=f"role_{idx}_greetings",
        ).splitlines()
        if line.strip()
    ]
    comms["followup_templates"] = [
        line.strip()
        for line in st.text_area(
            "跟进模板 (每行一条)",
            value="\n".join(comms.get("followup_templates", [])),
            key=f"role_{idx}_followups",
        ).splitlines()
        if line.strip()
    ]

    keywords = ensure_dict(role, "keywords")
    st.markdown("**关键词**")
    keywords["positive"] = st_tags(
        label="正向关键词",
        text="输入关键词后回车",
        value=keywords["positive"],
        maxtags=None,
        key=f"role_{idx}_keywords_positive",
    )
    keywords["negative"] = st_tags(
        label="负向关键词",
        text="输入关键词后回车",
        value=keywords["negative"],
        maxtags=None,
        key=f"role_{idx}_keywords_negative",
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
        "communication",
    }
    extra = {k: deepcopy(v) for k, v in role.items() if k not in handled}
    extra_yaml = yaml.safe_dump(extra, allow_unicode=True, sort_keys=False) if extra else ""
    updated_extra = st.text_area(
        "其它配置",
        value=extra_yaml,
        key=f"role_{idx}_extra",
        height=220,
    )
    try:
        parsed = yaml.safe_load(updated_extra) or {}
        for key in list(role.keys()):
            if key not in handled:
                role.pop(key)
        role.update(parsed)
    except yaml.YAMLError as exc:
        st.error(f"解析其它字段失败: {exc}")


def main() -> None:
    st.title("岗位画像")
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
                st.session_state["first_role_position"] = ""
                st.session_state["first_role_id"] = ""
                st.rerun()
        return

    tab_titles = [
        role.get("position") or role.get("id") or f"岗位#{idx + 1}"
        for idx, role in enumerate(roles)
    ]
    tabs = st.tabs(tab_titles + ["➕ 新增岗位"])

    for idx, tab in enumerate(tabs[:-1]):
        with tab:
            _edit_role(roles[idx], idx)
            if st.button("删除该岗位", key=f"role_delete_{idx}"):
                roles.pop(idx)
                st.rerun()

    with tabs[-1]:
        st.markdown("### 新增岗位画像")
        new_position = st.text_input("岗位名称", key="new_role_position")
        new_role_id = st.text_input("岗位 ID (可选)", key="new_role_id")
        if st.button("新增岗位", key="roles_add_tab"):
            if not new_position.strip():
                st.warning("岗位名称不能为空")
            else:
                roles.append(_create_role(new_position, new_role_id, existing_ids))
                st.session_state["new_role_position"] = ""
                st.session_state["new_role_id"] = ""
                st.rerun()

    auto_save_config(config)


if __name__ == "__main__":
    main()
