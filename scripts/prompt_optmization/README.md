# 候选人筛选指南（滚动迭代：每次 10 份）

本指南用于“架构师/平台底座”岗位的离线可复盘筛选：把**岗位肖像 + 候选人样本 + 最近对话 history +（本次重新生成的）analysis** 固化成一个批次目录（默认 10 份），并在每次批次产出“完整优化版”的 `prompt_optimized.py` / `job_portrait_optimized.json`，用于下一批继续迭代验证。

核心目标：拒绝“简历匹配的伪高P”，优先筛出具备 **结构化思维** 与 **机制设计能力** 的真架构师/负责人（Level 2）。

> 安全提醒：`scripts/prompt_optmization/**/run_*` 下包含候选人简历/电话/邮箱等敏感信息，**不要提交到 git**（仓库通过 `.gitignore` 已忽略该目录，但仍请自查）。

---

## 0) 一句话工作流

1) 跑脚本拉最新 10 份候选人 → 2) 按本指南读 `优化报告.md` 复盘每个人 → 3) 修改本批次的 `prompt_optimized.py` / `job_portrait_optimized.json` → 4) 用新 prompt 重新跑分析（线上流程）→ 5) 再跑下一批验证“合规性/稳定性”是否提升。

---

## 1) 如何运行脚本（必看）

### 1.1 环境准备

- Python 3.11+，建议在虚拟环境中运行
- 安装依赖：`pip install -r requirements.txt`
- 确保本项目连接候选人库/岗位库所需的环境变量与配置已就绪（否则脚本无法拉取岗位/候选人）

### 1.2 运行命令（仓库根目录）

按岗位名称关键字选择（推荐）：

```bash
python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-position 架构师
```

按 `job_id/base_job_id` 选择：

```bash
python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-id <JOB_ID>
```

调整每批数量（默认 10，建议保持 10 便于快速迭代）：

```bash
python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-position 架构师 --batch-size 10
```

指定输出根目录（可选）：

```bash
python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-position 架构师 --prompt-opt-dir scripts/prompt_optmization
```

### 1.3 你会得到什么输出

每次运行都会新建一个目录：`scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/`，里面通常包含：

- `job_portrait.json`：本次导出的岗位肖像（原始/基线）
- `job_portrait_optimized.json`：本次“完整优化版”岗位肖像（你要编辑，下一批会作为基线）
- `prompt_optimized.py`：本次“完整优化版” prompt（你要编辑，下一批会作为基线）
- `candidates/*.json`：候选人样本（已过滤：简历已加载 + 有 assistant 对话；analysis 会在本次运行中重新生成）
- `excluded_candidates.json`：被过滤掉的候选人列表与原因
- `overall_distribution.txt`：本批次 overall 分数分布（**优先使用本次生成的 analysis；若生成失败才回退 legacy**）
- `优化报告.md`：复盘报告（含与上一批的对比指标）

> 重要：脚本默认会用 OpenAI **重新生成 analysis**（并保留原有的 `analysis_legacy` 方便排查历史污染）。  
> 如果你只想“纯下载不分析”，可加 `--skip-reanalyze`。

常用参数：

```bash
# 只下载不重跑分析
python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-position 架构师 --skip-reanalyze

# 重跑分析时，最多带入最近 30 条对话（用于更准的画像/追问）
python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-position 架构师 --history-max-messages 30
```

---

## 2) 先读哪些文件（按顺序）

1) 系统设计方案（决定关键场景 & 压测题）  
- `scripts/prompt_optmization/架构师/基于EDA架构的PreSeen HighLevel Design.md`

2) 本批次目录（脚本输出）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/优化报告.md`（先看结论与对比指标）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/job_portrait.json`（看现状画像）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/candidates/*.json`（逐个复盘样本）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/prompt_optimized.py`（你要改的 prompt）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/job_portrait_optimized.json`（你要改的画像）

3) 线上基线 prompt（对照用）  
- `src/prompts/assistant_actions_prompts.py`（重点看 `ANALYZE_ACTION` 与 `AnalysisSchema`）

---

## 3) 画像校准：我们要找 Level 2（真架构师/负责人）

请强制区分两类人（用“输出形态”而不是“title/年限”判断）：

**高级执行者（Senior IC / “高级工头”）**
- 讲“怎么做(How)”多：堆工具/堆方案（K8s、Redis、MQ…）
- 方案 Feature Rich，但缺少边界/取舍/机制（为什么选它、牺牲了什么）
- 管理靠“强调/督促/提醒”，而不是流程/门禁/指标

**真架构师/负责人（Architect/Lead）**
- 讲“为什么(Why)/如果换约束会怎样(What if)”多：能做减法、讲 trade-off
- 会把系统做成可治理：SLA/SLO、熔断、门禁、指标、回放/补偿闭环
- 能讲清失败/误判/故障复盘，并能量化影响与收益

红灯（快速淘汰/降档）：无法量化、只有顺境经验、路径依赖、管理靠吼。  
绿灯（核心加分）：结构化分层输出、承认局限、第一性原理、能讲取舍与机制。

---

## 4) 怎么筛：用“评分表（总分100）”稳定输出

统一用 **总分100** 的评分表再映射到 10 分制（写入 `AnalysisSchema`），降低“拍脑袋评分”的波动。

### 4.1 评分维度（不使用 A/B/C 等抽象符号）

- 硬门槛与角色真实性（40）
  - 年限与口径可信度（10）：按“代码+架构+负责人”总年限估算；年限是偏好区间，不一票否决
  - 0→1 大规模分布式落地（20）：规模/边界/关键故障/你负责模块
  - hands-on 主编码（10）：主编码占比 >=70% 才能拿高分；否则扣分并可能降档为“高级IC”
- 岗位关键场景能力（45）（与 HighLevel Design 对齐）
  - 编排与执行分离：state+command 持久化，Master 崩溃恢复（15）
  - At-least-once 幂等闭环：message_id/幂等键、毒丸、DLQ、回放（15）
  - 数据血缘与版本化：Git-like commit/回滚/追踪，记录 input/output（10）
  - 标准任务 IR/DSL：规范、校验、版本化、兼容性、可复现（5）
- 背景与契合（15）：基础(8) + 契合/owner(7)
- 潜力分（0-20）：仅用于信息缺失；按 50% 计入总分（潜力/2），并提示 HR 重点核实潜力来源

### 4.2 `analysis.summary` 的评分表格式（强制）

`summary` 必须包含一行评分表，例如：

- `门槛=28,场景=30,基础=6,契合=7,潜力=8(+4),总分=75/100=>8/10`

---

## 5) 怎么问：反废话压测（Anti-Platitude）

优先问能刺破“正确的废话”的开放性问题（不问能被 AI 搜到标准答案的问题）：

- 你最想推翻重写的一个设计决策是什么？为什么当时选它，现在觉得它错了？
- 如果你的系统流量/数据量暴涨 10 倍，哪个组件会最先爆？为什么？你会按什么顺序止血与改造？
- 讲一次你亲历的故障/事故：怎么发现→怎么止血→怎么长期治理？（给指标变化与关键取舍）
- 讲一次你不得不让项目延期的案例：你用什么数据/指标说服老板接受延期？
- 你推行过什么“得罪人但必须做”的机制化治理（门禁/熔断/指标），结果如何？

---

## 6) 结论怎么写（写进 analysis.summary / 优化报告）

`summary` 只写“概述”（不要写下一步 action 指令），但必须包含：

1) 匹配判断：不匹配/有潜力/匹配 + 阶段建议（PASS/CHAT/SEEK/CONTACT）  
2) 评分表一行：门槛/场景/基础/契合/潜力(按50%)/总分  
3) 画像判断一行（中文标签）：  
   - `技术深度=顶尖/优秀/合格/欠缺；抽象能力=顶尖/优秀/合格/欠缺；机制化=顶尖/优秀/合格/欠缺；建议=作为架构师推进/作为高级IC推进/不推进`
4) 若使用潜力分：提示 HR 重点核实 1-3 个点（潜力来源/信息缺失点）

`followup_tips`：只写 3 个开放性场景追问（亲历、过程、关键决策、量化结果），不要索取任何工作隐私材料（代码/图/PR 等）。

---

## 7) 每批怎么迭代（滚动版本）

每次运行会在新 `run_YYYYMMDD_HHMMSS/` 下生成两份“完整优化版”（你直接改它们即可）：

- `prompt_optimized.py`：下一批次会以它为基线
- `job_portrait_optimized.json`：下一批次会以它为基线

`优化报告.md` 会展示与上一批次的对比指标（分数分布 + “评分表/画像判断”的合规性占比），用于判断迭代是否有效。  
建议的迭代节奏：每批只改 1-3 个关键点（例如“评分表格式约束”或“关键场景题”），否则很难归因哪一条改动带来了收益/退化。
