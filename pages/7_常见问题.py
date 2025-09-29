"""FAQ management backed by Zilliz QA store."""
from __future__ import annotations

from pathlib import Path
from typing import List

import streamlit as st

from streamlit_shared import ensure_state, sidebar_controls
from src.qa_workflow import qa_workflow


def render_search_section() -> None:
    st.subheader("查询测试")
    query = st.text_input("输入候选人提问或上下文", key="faq_query")
    if st.button("检索", key="faq_query_btn"):
        with st.spinner("检索中..."):
            results = qa_workflow.retrieve_relevant_answers(query)
        if not results:
            st.info("未检索到匹配记录")
        else:
            for item in results:
                with st.container(border=True):
                    st.markdown(f"**Score:** {item.get('score', 0):.4f}")
                    st.markdown(f"**Question:** {item.get('question', '-')}")
                    st.markdown(f"**Answer:** {item.get('answer', '-')}")
                    keywords = item.get('keywords') or []
                    if keywords:
                        st.caption("关键词: " + ", ".join(map(str, keywords)))


def _keywords_to_text(keywords: List[str] | None) -> str:
    return ", ".join(kw for kw in (keywords or []) if kw)


def _text_to_keywords(text: str) -> List[str]:
    return [kw.strip() for kw in text.split(',') if kw.strip()]


def render_entries() -> None:
    entries = qa_workflow.list_entries(limit=500)
    if not entries:
        st.info("当前没有 QA 记录")
        return

    st.subheader("QA 列表")
    table_rows = [
        {
            'qa_id': entry.get('qa_id'),
            'question': entry.get('question', ''),
            'answer': entry.get('answer', ''),
            'keywords': entry.get('keywords') or [],
        }
        for entry in entries
    ]

    st.dataframe(
        [
            {
                'qa_id': row['qa_id'],
                'question': row['question'],
                'answer': row['answer'][:120] + ('...' if len(row['answer']) > 120 else ''),
                'keywords': _keywords_to_text(row['keywords']),
            }
            for row in table_rows
        ],
        use_container_width=True,
    )

    id_map = {row['qa_id']: row for row in table_rows if row['qa_id']}
    if not id_map:
        return

    selected_id = st.selectbox(
        "选择要编辑的记录",
        options=list(id_map.keys()),
        format_func=lambda rid: f"{rid} - {id_map[rid]['question'][:20]}...",
        key="faq_edit_select",
    )
    selected = id_map[selected_id]
    with st.form("faq_edit_form"):
        question = st.text_area("问题", value=selected['question'])
        answer = st.text_area("回答", value=selected['answer'])
        keywords_text = st.text_input("关键词 (逗号分隔)", value=_keywords_to_text(selected['keywords']))
        submitted = st.form_submit_button("保存修改")
        if submitted:
            if not question.strip() or not answer.strip():
                st.warning("问题与回答均不能为空")
            else:
                with st.spinner("更新中..."):
                    qa_workflow.record_qa(
                        qa_id=selected_id,
                        question=question.strip(),
                        answer=answer.strip(),
                        keywords=_text_to_keywords(keywords_text),
                    )
                st.success("记录已更新")
                st.rerun()
    if st.button("删除该记录", key=f"faq_delete_{selected_id}"):
        with st.spinner("删除中..."):
            ok = qa_workflow.delete_entry(selected_id)
        if ok:
            st.success("已删除")
        else:
            st.warning("删除失败")
        st.rerun()


def render_create_form() -> None:
    st.subheader("新增 QA")
    with st.form("faq_create_form"):
        question = st.text_area("问题")
        answer = st.text_area("回答")
        keywords_text = st.text_input("关键词 (逗号分隔)", value="")
        submitted = st.form_submit_button("创建")
        if submitted:
            if not question.strip() or not answer.strip():
                st.warning("问题与回答均不能为空")
            else:
                qa_id = qa_workflow.generate_id()
                with st.spinner("写入中..."):
                    qa_workflow.record_qa(
                        qa_id=qa_id,
                        question=question.strip(),
                        answer=answer.strip(),
                        keywords=_text_to_keywords(keywords_text),
                    )
                st.success(f"已新增 QA 记录: {qa_id}")
                st.rerun()


def generate_company_faq() -> None:
    source = Path("config/company.md")
    if not source.exists():
        st.warning("未找到公司介绍文件 config/company.md")
        return

    samples = [
        (
            "Stardust 的核心使命是什么？",
            "Stardust 旨在打造企业级 AI 的“操作系统”，通过 MorningStar 平台把企业内混沌的私有数据转化为可持续迭代的 AI 飞轮，让每个企业真正拥有自己的 AI 未来。",
            ["使命", "MorningStar"],
        ),
        (
            "MorningStar 与 Rosetta 分别解决什么问题？",
            "MorningStar 管理数据整合、清洗、挖掘到模型训练部署的全生命周期；Rosetta 是自动化数据标注引擎，为数据驱动的模型迭代提供高质量原料。",
            ["平台", "数据标注"],
        ),
        (
            "团队背景如何？",
            "团队成员来自 Google、MIT、清华等顶尖机构，曾帮助 70+ 款自动驾驶车型量产，并服务华为、比亚迪、上汽等行业领军者。",
            ["团队", "自动驾驶"],
        ),
        (
            "为什么值得加入 Stardust？",
            "我们以第一性原理重新构建企业数据基础设施，面对 PB 级数据与高可靠性场景，给予成员极强的所有权与工程挑战。",
            ["加入理由", "挑战"],
        ),
    ]

    with st.spinner("生成示例 QA..."):
        for question, answer, keywords in samples:
            qa_workflow.record_qa(
                qa_id=qa_workflow.generate_id(),
                question=question,
                answer=answer,
                keywords=keywords,
            )
    st.success("已写入示例 QA 记录")
    st.rerun()


def main() -> None:
    st.title("常见问题 (QA)")
    ensure_state()
    sidebar_controls(include_config_path=False)

    if not getattr(qa_workflow, 'enabled', False):
        st.warning("QA Store 未启用，请检查 Zilliz 配置和 OPENAI_API_KEY")
        return

    render_search_section()
    st.divider()
    with st.container():
        col1, col2 = st.columns([2, 1])
        with col1:
            render_create_form()
        with col2:
            if st.button("根据公司介绍生成示例 QA", key="faq_generate_company"):
                generate_company_faq()
    st.divider()
    render_entries()


if __name__ == "__main__":
    main()
