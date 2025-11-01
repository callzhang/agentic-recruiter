"""Assistant management page."""
from __future__ import annotations

from pathlib import Path
import time
import streamlit as st
from openai import OpenAI
from streamlit_shared import ensure_state, sidebar_controls, SessionKeys, load_assistants
# Use API calls instead of direct imports
from streamlit_shared import call_api

# Default templates
default_greetings = """{candidate} 你好，我是 Stardust 星尘数据的招聘顾问。我们正在打造企业级 AI 基础设施，希望与你聊聊 {position} 机会。
您好，我来自 Stardust 的 MorningStar 团队，对您在 {skill} 方面的实践非常感兴趣，想约个时间交流一下？"""

default_followups = """想确认一下我们之前的沟通是否方便继续？如需了解更多关于团队挑战或产品路线，随时告诉我。
如果您对 PB 级数据/大模型平台建设好奇，我们可以深入介绍 MorningStar & Rosetta 的真实场景。"""
    
default_assistant_instructions = f"""
你是一个专业的招聘顾问助理。你的职责是：
1. 根据候选人背景和公司需求，生成专业、真诚的招聘消息
2. 对于首次联系，生成友好的打招呼消息，突出公司亮点
3. 对于跟进消息，基于之前的对话历史，生成个性化的跟进内容
4. 保持专业、简洁、真诚的沟通风格
5. 突出候选人与岗位的匹配点
请始终使用中文回复，消息长度控制在100-200字。
【打招呼用语】：
{default_greetings}

【跟进用语】:
{default_followups}
"""

# Local helper to load company markdown from config/company.md

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


@st.dialog("确认删除助手")
def confirm_delete_dialog(assistant_name: str, assistant_id: str):
    """显示删除确认对话框"""
    st.warning(f"⚠️ 您确定要删除助手 **{assistant_name}** 吗？")
    st.write("此操作无法撤销！")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 确认删除", type="primary", width="stretch"):
            # Delete assistant via API
            ok, response = call_api("DELETE", f"/assistant/delete/{assistant_id}")
            if not ok:
                st.error(f"删除失败: {response}")
                return
            # Clear assistant cache after successful deletion
            load_assistants.clear()
            st.success(f"助手 '{assistant_name}' 已删除")
            time.sleep(1)
            st.rerun()
    with col2:
        if st.button("❌ 取消", width="stretch"):
            st.rerun()

def main() -> None:
    st.title("助手管理")
    st.info("助手是用于按照制定风格制作的AI模型。您可以创建新的助手或选择现有的助手。")
    st.markdown(
        """
:orange[“指令”用于设置AI模型的沟通风格, 公司信息都保存在“沟通设置里面”，用于回答助手的问题]

**描述** ：用于设置AI模型的描述, 不用于AI运行

**元数据** ：用于保存一些额外信息, 不用于AI模型运行
        """
    )
    ensure_state()
    sidebar_controls(include_config_path=False)

    # Get assistants via cached function
    assistants = load_assistants()
    if not assistants:
        st.error("无法加载助手列表")
        return
    new_assistant_label = "创建新的助手"

    idx = st.session_state.get(SessionKeys.SELECTED_ASSISTANT_ID, 0)  

    is_new = st.checkbox(new_assistant_label, value=False)
    
    # Available model options
    model_options = ["gpt-4o-mini", "gpt-5-mini"]

    if is_new:
        st.info("正在创建新的助手")
        selected_assistant = None
    else:
        selected_assistant = [a for a in assistants if a['id'] == idx][0]
    name = st.subheader(selected_assistant['name'] if selected_assistant else "新助手", help="左侧选择助理")
    # Get current model and find its index, default to gpt-4o-mini if not in list
    current_model = selected_assistant['model'] if selected_assistant else "gpt-5-mini"
    model_index = model_options.index(current_model) if current_model in model_options else 0
    model = st.selectbox("模型", options=model_options, index=model_index)
    description = st.text_area("描述", value=selected_assistant['description'] if selected_assistant else "")
    
    st.subheader("💬 沟通设置")
    instructions = st.text_area("指令", value=selected_assistant['instructions'] if selected_assistant else default_assistant_instructions, height=600)
    
    # Metadata editor for existing assistant
    st.subheader("元数据 (Metadata)", help="可用于保存一些额外信息, 不用于AI模型运行")
    existing_metadata = selected_assistant['metadata'] if selected_assistant else {}
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
    created_at = selected_assistant.get("created_at", 0) if selected_assistant else 0
    
    # Communication Settings Section
    st.divider()
    
    # Get existing templates from metadata
    greeting_templates = metadata_dict.get("greeting_templates", "")
    followup_templates = metadata_dict.get("followup_templates", "")
    
    
    if selected_assistant:
        import datetime
        created_time = datetime.datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M:%S') if created_at else "未知"
        st.write(f"创建时间: {created_time}")
        st.write(f"ID: {selected_assistant.get('id', 'N/A')}")

    col1, col2, col3 = st.columns(3)
    with col1:
        if not name:
            st.error("名称不能为空")
        elif selected_assistant:
            if st.button("💾 保存", type="primary", width="stretch"):
                    # Update assistant via API
                    ok, response = call_api("POST", f"/assistant/update/{selected_assistant['id']}", json={
                        "name": name,
                        "model": model,
                        "description": description,
                        "instructions": instructions,
                        "metadata": metadata_dict,
                    })
                    if not ok:
                        st.error(f"更新失败: {response}")
                        return
                    # Clear assistant cache after successful update
                    load_assistants.clear()
                    st.success("助手已更新")
                    time.sleep(1)
                    st.rerun()
    with col2:
        if selected_assistant:
            if st.button("🗑️ 删除助手", type="secondary", width="stretch"):
                confirm_delete_dialog(selected_assistant.get('name', 'Unknown'), selected_assistant.get('id', ''))
    with col3:
        if is_new and st.button("✨ 创建", type="primary", width="stretch"):
            if not name:
                st.error("名称不能为空")
            else:
                # Create assistant via API
                ok, response = call_api("POST", "/assistant/create", json={
                    "name": name,
                    "model": model,
                    "description": description,
                    "instructions": instructions,
                    "metadata": metadata_dict,
                })
                if not ok:
                    st.error(f"创建失败: {response}")
                    return
                # Clear assistant cache after successful creation
                load_assistants.clear()
                st.success("助手已创建")
                time.sleep(1)
                st.rerun()

if __name__ == "__main__":
    main()
