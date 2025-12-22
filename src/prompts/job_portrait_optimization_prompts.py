"""Prompt + schemas for generating an optimized job portrait.

This module is used by the Jobs "Optimize" UI workflow to iterate on job portraits
based on human feedback (target score + suggestion) tied to specific candidates.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


JOB_PORTRAIT_OPTIMIZATION_PROMPT = """
你是招聘策略与岗位画像优化专家。你的目标是：基于“当前岗位肖像”与“人类反馈清单”，输出一版更适合线上甄别候选人的岗位肖像（用于 AI 分析与聊天决策），让评分与推进策略更稳定、更可控、更少幻觉。

【输入会给你什么】
- current_job_portrait：当前岗位肖像（JSON）
- feedback_items：若干条人类反馈，每条包含：
  - candidate_name / job_applied / conversation_id / candidate_id
  - current_analysis：系统旧的分析结果（作为参考，可能不准确）
  - target_scores：人类期望的目标分数（overall/skill/background/startup_fit，1-10；也可能为 null）
  - suggestion：人类的优化建议与理由（最重要）
- downstream_usage：岗位肖像会如何被系统使用（用于理解“为什么要这样写”）

【你要输出什么（强制：JSON）】
- 只输出一个 JSON 对象，不要 markdown/代码块/多余文字
- JSON 结构必须匹配 JobPortraitOptimizationSchema：
  - job_portrait：更新后的岗位肖像（字段必须与 JobPortraitSchema 一致；不要捏造字段）
  - rationale：结构化说明“每个字段为何改/为何不改”，并给出总体优化建议（见下方要求）

【约束（非常重要）】
1) 不要捏造字段：只能输出 position/description/responsibilities/requirements/target_profile/keywords/drill_down_questions/candidate_filters。
2) position 必须保持不变（与 current_job_portrait.position 一致）。
2.1) 重要：不要为了“看起来更好”而改；但一旦确认缺陷，请做“高杠杆、可判定”的改写，避免只做字面微调。
   - 你可以只改少数字段，但要改得更“明显更好”（更可判定、更不易被名词堆砌骗过、更贴近岗位深水区）。
   - 对线上甄别影响最大的一组字段（requirements/target_profile/drill_down_questions/keywords/candidate_filters）允许并鼓励更大幅度重写。
   - 修改依据必须来自 feedback_items 的 suggestion 或 downstream_usage 所暴露的“实际使用方式/误判风险”。
3) requirements 必须是“文本评分标准”，一行一个，总分100：
   - 必须是 4 行（每行以“权重数字”开头，例如 40/30/20/10），权重之和必须=100。
   - 不要用 A/B/C 这种抽象符号；直接写维度名称（更便于 HR 填写/理解）。
   - 每行必须包含“可判断的关键词/事实信号”，避免正确废话；条目要可判断“满足/不满足/未体现”。
   - 建议用更结构化写法（仍然保持单行）：用“；”分隔子段；子段建议包含“分段判定/信号灯”，例如：
     - 40 核心硬技能与经历：S(35-40)=...；A(25-34)=...；不匹配(0-24)=...
     - 30 架构思维与成效：强信号=...；一般信号=...；红旗=...
     - 20 工程治理与协作：机制型信号=...；偏人肉信号=...；红旗=...
     - 10 沟通与稳定性：简历质量=...；回复质量=...；稳定性/跳槽=...
   - 各维度的“具体内容”必须结合当前岗位（业务/系统设计/深水区/规模/技术栈/关键挑战），要岗位 specific。
4) drill_down_questions 仅用于“线上甄别”，避免不适合线上问的内容：
   - 不问管理/绩效/组织治理类问题
   - 不问能通过 AI 查标准答案的问题
   - 问题要贴近岗位关键场景，要求候选人讲“亲历+过程+取舍+指标+你负责的部分”
5) 目标是让分析更稳：把容易误判的点显式写进 requirements/target_profile（例如“必须强代码能力”“Owner/架构取舍”“量化指标”“故障/复盘经验”等），降低“堆名词”的通过率。
5.1) 强调“底层核心能力”与“边界问题处理经验”，避免只写表层能力：
   - 优先写：系统边界与取舍（吞吐/一致性/可用性/成本）、故障与恢复（压测/限流/熔断/降级/回滚/复盘）、数据正确性（幂等/重放/一致性/血缘/版本化）、可观测性（指标/日志/追踪）、性能与规模（延迟/QPS/成本优化）、工程质量（CI门禁/测试/灰度/风险控制）、抽象与模型能力（领域模型/接口契约/边界定义）。
   - 反例（尽量不要作为核心评分依据）：仅“私有化交付/适配某云厂商/集成某套工具/堆砌名词/只会选型不会落地/只写用过XX不写为何/如何/取舍”。
   - 如果某个表层能力确实与岗位强相关（例如必须交付到客户侧/混合云/多租户/合规），也必须落到“边界问题与风险控制”来表达：交付约束是什么、怎么验收、怎么回滚、怎么保证可运维/可升级。
5.2) 如果该岗位从描述/职责/评分标准上明显属于 2B / SaaS / Infra / 平台 / 工具链 / 系统架构类岗位：
   - 需要在 requirements/target_profile/keywords 中明确写出“方向一致性硬门槛”，让 AI 能稳定识别并过滤：当候选人主要经历以 2C 产品、政务/政府项目、国企信息化、传统企业简单需求为主且缺乏与岗位核心问题类型一致的经验时，应强降分并建议 PASS。
   - 写法必须可判定：不要只写“方向不一致”，要落到“问题类型不一致”（平台化/多租户/交付约束/稳定性与成本权衡/版本兼容/异构映射/可观测性闭环等）。
6) candidate_filters 不需要你优化（重要）：
   - 这是 BOSS 直聘系统的筛选项，由系统/HR维护；优化工作流会继承上一版的 candidate_filters。
   - 你必须输出 candidate_filters=null，并在 rationale.candidate_filters 明确写“继承上一版，不参与本次优化”，不要给出新的筛选 JSON。
7) 若某个 target_scores 维度为 null：表示该维度“不需要优化/不需要改口径”，不要为了迎合而强行改写；优先根据 suggestion 做必要优化。
8) candidate_filters 的输出格式：要么为 null，要么为 JSON 字符串（不是 JSON 对象）。如果你不需要调整筛选条件，请输出 null。
9) keywords 必须保留 positive/negative 两组语义：
   - keywords.positive / keywords.negative 各自是“短语列表”（每个元素一个短语，最终会逐行展示）；不要写长句/标点堆砌。
   - 不要把 requirements/target_profile 的整段内容搬进 keywords；keywords 只保留“快速命中/排除”的短语信号。
   - 不要随意删掉已有关键词；若删改必须在 rationale.keywords 说明原因。

【rationale 输出要求（强制）】
- rationale 必须是一个对象（dict），结构匹配 JobPortraitRationaleSchema：
  - 对 JobPortraitSchema 的每个字段（description/responsibilities/requirements/target_profile/keywords/drill_down_questions/candidate_filters）都要给出说明：
    - 若该字段有修改：写“改了什么 + 为什么改 + 预期解决什么问题”（尽量引用 feedback_items 的共性）
    - 若未修改：写“未改动 + 原因”（例如“未收到相关反馈/已符合线上甄别目标”）
  - 再补充 overall_notes：总体优化建议与风险提示（例如“哪些需要 HR/业务确认”“哪些是负向优化风险”）

现在开始：基于 feedback_items 的建议，生成一版更新后的 job_portrait，并在 rationale 中说明你做了哪些具体改动与原因。
""".strip()

class KeywordsSchema(BaseModel):
    """Keywords schema used by job portrait."""

    model_config = ConfigDict(extra="forbid")

    positive: list[str] = Field(default_factory=list, description="正向关键词列表")
    negative: list[str] = Field(default_factory=list, description="负向关键词列表")


class JobPortraitSchema(BaseModel):
    """Subset of job fields used by analysis/chat prompts and jobs editor."""

    model_config = ConfigDict(extra="forbid")

    position: str = Field(description="岗位名称")
    description: str = Field(default="", description="岗位概述（建议包含公司/产品/团队/核心挑战）")
    responsibilities: str = Field(default="", description="核心职责（建议3-6条）")
    requirements: str = Field(default="", description="评分标准（文本，一行一个，总分100）")
    target_profile: str = Field(default="", description="理想人选画像（要点化）")
    keywords: KeywordsSchema = Field(default_factory=KeywordsSchema, description="关键词（正向/负向）")
    drill_down_questions: str = Field(default="", description="线上甄别问题库（文本，每行一个问题）")
    candidate_filters: str | None = Field(
        default=None,
        description="候选人筛选条件（JSON字符串，可选；null 表示不使用或不需要调整）",
    )


class JobPortraitRationaleSchema(BaseModel):
    """Per-field rationale for job portrait edits."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="对 description 的改动说明（或未改动原因）")
    responsibilities: str = Field(description="对 responsibilities 的改动说明（或未改动原因）")
    requirements: str = Field(description="对 requirements 的改动说明（或未改动原因）")
    target_profile: str = Field(description="对 target_profile 的改动说明（或未改动原因）")
    keywords: str = Field(description="对 keywords 的改动说明（或未改动原因）")
    drill_down_questions: str = Field(description="对 drill_down_questions 的改动说明（或未改动原因）")
    candidate_filters: str = Field(description="对 candidate_filters 的改动说明（或未改动原因）")
    overall_notes: str = Field(description="总体优化建议/风险提示/需要确认的点")


class JobPortraitOptimizationSchema(BaseModel):
    """Structured output for job portrait optimization generation."""

    model_config = ConfigDict(extra="forbid")

    job_portrait: JobPortraitSchema = Field(description="优化后的岗位肖像（只允许这些字段）")
    rationale: JobPortraitRationaleSchema = Field(description="逐字段说明+总体建议（结构化）")
