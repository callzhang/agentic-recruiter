"""Assistant management page."""
from __future__ import annotations

from pathlib import Path
import time
import os
import yaml

import streamlit as st

from openai import OpenAI
from streamlit_shared import ensure_state, sidebar_controls
from src.config import settings


# Local helper to load company markdown from config/company.md
def load_company_markdown() -> str:
    path = Path("config/company.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""

def parse_metadata(metadata_str: str) -> dict:
    """Parse metadata string to dictionary. Returns empty dict if invalid."""
    if not metadata_str or not metadata_str.strip():
        return {}
    try:
        import json
        parsed = json.loads(metadata_str)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except Exception:
        return {}

def format_json(obj: dict | str) -> str:
    """Format dictionary or JSON string into pretty-printed JSON."""
    import json
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

def dict_to_dataframe(metadata: dict) -> list[dict]:
    """Convert metadata dict to list of key-value dicts for dataframe."""
    if not metadata:
        return [{"键 (Key)": "", "值 (Value)": ""}]
    return [{"键 (Key)": k, "值 (Value)": v} for k, v in metadata.items()]

def dataframe_to_dict(df_data: list[dict]) -> dict:
    """Convert dataframe data back to metadata dict."""
    result = {}
    for row in df_data:
        key = str(row.get("键 (Key)", "")).strip()
        value = row.get("值 (Value)", "")
        if key:  # Only include non-empty keys
            result[key] = value
    return result

def load_openai_key() -> str | None:
    """Load OpenAI API key from settings."""
    return settings.OPENAI_API_KEY if settings.OPENAI_API_KEY else None

# Initialize OpenAI client with API key
api_key = load_openai_key()

client = OpenAI(api_key=api_key)

@st.dialog("确认删除助手")
def confirm_delete_dialog(assistant_name: str, assistant_id: str):
    """显示删除确认对话框"""
    st.warning(f"⚠️ 您确定要删除助手 **{assistant_name}** 吗？")
    st.write("此操作无法撤销！")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 确认删除", type="primary", width="stretch"):
            try:
                client.beta.assistants.delete(assistant_id=assistant_id)
                st.success(f"助手 '{assistant_name}' 已删除")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"删除失败: {e}")
    with col2:
        if st.button("❌ 取消", width="stretch"):
            st.rerun()

def main() -> None:
    st.title("助手管理")
    st.info("助手是用于按照制定风格制作的AI模型。您可以创建新的助手或选择现有的助手。")
    ensure_state()
    sidebar_controls(include_config_path=False)

    assistants = client.beta.assistants.list().data
    assistant_options = {a.name: a for a in assistants}

    selected_name = st.selectbox("选择助手", options= list(assistant_options.keys()) + ["创建新的助手"], index=0)
    selected_assistant = assistant_options.get(selected_name) if selected_name else None

    is_new = selected_assistant is None and selected_name == "创建新的助手"
    
    # Available model options
    model_options = ["gpt-4o-mini", "gpt-5-mini"]

    if is_new:
        st.info("正在创建新的助手")
        name = st.text_input("名称", value="新助手")
        model = st.selectbox("模型", options=model_options, index=0)
        description = st.text_area("描述", value="")
        instructions = st.text_area("指令", value=load_company_markdown(), height=600)
        
        # Metadata editor for new assistant
        st.subheader("元数据 (Metadata)")
        metadata_df = st.data_editor(
            dict_to_dataframe({}),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            column_config={
                "键 (Key)": st.column_config.TextColumn("键 (Key)", required=True, width="medium"),
                "值 (Value)": st.column_config.TextColumn("值 (Value)", width="medium"),
            }
        )
        metadata_dict = dataframe_to_dict(metadata_df)
        created_at = 0
    else:
        name = st.text_input("名称", value=selected_assistant.name if selected_assistant else "新助手")
        # Get current model and find its index, default to gpt-4o-mini if not in list
        current_model = selected_assistant.model if selected_assistant else "gpt-4o-mini"
        model_index = model_options.index(current_model) if current_model in model_options else 0
        model = st.selectbox("模型", options=model_options, index=model_index)
        description = st.text_area("描述", value=selected_assistant.description if selected_assistant else "")
        instructions = st.text_area("指令", value=selected_assistant.instructions if selected_assistant else "", height=600)
        
        # Metadata editor for existing assistant
        st.subheader("元数据 (Metadata)")
        existing_metadata = selected_assistant.metadata if selected_assistant else {}
        metadata_df = st.data_editor(
            dict_to_dataframe(existing_metadata),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            column_config={
                "键 (Key)": st.column_config.TextColumn("键 (Key)", required=True, width="medium"),
                "值 (Value)": st.column_config.TextColumn("值 (Value)", width="medium"),
            }
        )
        metadata_dict = dataframe_to_dict(metadata_df)
        created_at = selected_assistant.created_at if selected_assistant else 0
    
    # Communication Settings Section
    st.divider()
    st.subheader("💬 沟通设置")
    
    # Get existing templates from metadata
    greeting_templates = metadata_dict.get("greeting_templates", "")
    followup_templates = metadata_dict.get("followup_templates", "")
    
    # Default templates
    default_greetings = """{candidate} 你好，我是 Stardust 星尘数据的招聘顾问。我们正在打造企业级 AI 基础设施，希望与你聊聊 {position} 机会。
您好，我来自 Stardust 的 MorningStar 团队，对您在 {skill} 方面的实践非常感兴趣，想约个时间交流一下？"""
    
    default_followups = """想确认一下我们之前的沟通是否方便继续？如需了解更多关于团队挑战或产品路线，随时告诉我。
如果您对 PB 级数据/大模型平台建设好奇，我们可以深入介绍 MorningStar & Rosetta 的真实场景。"""
    
    col_greet, col_follow = st.columns(2)
    
    with col_greet:
        st.markdown("**打招呼模板** (每行一条)")
        st.caption("可用变量: {candidate}, {position}, {skill}")
        greeting_text = st.text_area(
            "打招呼模板",
            value=greeting_templates if greeting_templates else default_greetings,
            height=150,
            label_visibility="collapsed",
            help="每行一个模板，系统会随机选择一个使用"
        )
        greeting_count = len([line for line in greeting_text.strip().split('\n') if line.strip()])
        st.info(f"📝 {greeting_count} 个打招呼模板")
    
    with col_follow:
        st.markdown("**跟进模板** (每行一条)")
        st.caption("可用变量: {candidate}, {position}, {skill}")
        followup_text = st.text_area(
            "跟进模板",
            value=followup_templates if followup_templates else default_followups,
            height=150,
            label_visibility="collapsed",
            help="每行一个模板，用于后续跟进沟通"
        )
        followup_count = len([line for line in followup_text.strip().split('\n') if line.strip()])
        st.info(f"📝 {followup_count} 个跟进模板")
    
    # Update metadata with templates
    metadata_dict["greeting_templates"] = greeting_text
    metadata_dict["followup_templates"] = followup_text

    if selected_assistant:
        import datetime
        created_time = datetime.datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M:%S') if created_at else "未知"
        st.write(f"创建时间: {created_time}")
        st.write(f"ID: {selected_assistant.id}")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("💾 保存", type="primary", width="stretch"):
            if not name:
                st.error("名称不能为空")
            else:
                try:
                    client.beta.assistants.update(
                        assistant_id=selected_assistant.id,
                        name=name,
                        model=model,
                        description=description,
                        instructions=instructions,
                        metadata=metadata_dict,
                    )
                    st.success("助手已更新")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"更新失败: {e}")
    with col2:
        if selected_assistant:
            if st.button("🗑️ 删除助手", type="secondary", width="stretch"):
                confirm_delete_dialog(selected_assistant.name, selected_assistant.id)
    with col3:
        if is_new and st.button("✨ 创建", type="primary", width="stretch"):
            if not name:
                st.error("名称不能为空")
            else:
                try:
                    client.beta.assistants.create(
                        name=name,
                        model=model,
                        description=description,
                        instructions=instructions,
                        metadata=metadata_dict,
                    )
                    st.success("助手已创建")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"创建失败: {e}")

if __name__ == "__main__":
    main()
