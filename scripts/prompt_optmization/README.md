# 候选人筛选指南（滚动迭代：每次 10 份）

本指南用于“架构师/平台底座”岗位的离线可复盘筛选：把**岗位肖像 + 候选人样本 + 最近对话 history +（数据库已有的）analysis** 固化成一个批次目录（默认 10 份），并在每次批次产出“完整优化版”的 `prompt_optimized.py` / `job_portrait_optimized.json`，用于下一批继续迭代验证。

核心目标：拒绝“简历匹配的伪高P”，优先筛出具备 **结构化思维** 与 **机制设计能力** 的真架构师/负责人（Level 2）。

> 安全提醒：`scripts/prompt_optmization/**/run_*` 下包含候选人简历/电话/邮箱等敏感信息，**不要提交到 git**（仓库通过 `.gitignore` 已忽略该目录，但仍请自查）。

---

## 0) 一句话工作流

1) 跑脚本拉最新 10 份候选人 → 2) 先读 `优化报告.md` 的“问题清单/引用示例/对比指标”，按引用抽样查看候选人 → 3) 修改本批次的 `prompt_optimized.py` / `job_portrait_optimized.json` → 4) 挑 2-5 个“有问题的候选人”回放验证（`generate_optimized.py --start-index/--limit`）→ 5) 满意后发布岗位肖像（Vercel UI/API 或本地 API）并验证 → 6) 再跑下一批验证“合规性/稳定性”是否提升。

> 如果你不需要离线回放验证，优先使用线上闭环：候选人详情页点击“评分不准” → `/jobs/optimize` → 生成并发布（详见 `vercel/README.md`）。

---

## 1) 如何运行脚本（必看）

### 1.1 环境准备

- Python 3.11+，建议在虚拟环境中运行
- 安装依赖：`pip install -r requirements.txt`
- 确保本项目连接候选人库/岗位库所需的环境变量与配置已就绪（否则脚本无法拉取岗位/候选人）
- 回放生成需要 OpenAI：确保 `config/secrets.yaml` 的 `openai` 配置可用（或使用环境变量覆盖）

### 1.2 运行命令（必须在 `scripts/prompt_optmization/` 目录）

按岗位名称关键字选择（推荐）：

```bash
cd scripts/prompt_optmization
python download_data_for_prompt_optimization.py --job-position 架构师
```

按 `job_id/base_job_id` 选择：

```bash
cd scripts/prompt_optmization
python download_data_for_prompt_optimization.py --job-id <JOB_ID>
```

调整每批数量（默认 10，建议保持 10 便于快速迭代）：

```bash
cd scripts/prompt_optmization
python download_data_for_prompt_optimization.py --job-position 架构师 --batch-size 10
```

指定输出根目录（可选）：

```bash
cd scripts/prompt_optmization
python download_data_for_prompt_optimization.py --job-position 架构师 --prompt-opt-dir .
```

### 1.3 你会得到什么输出

每次运行都会新建一个目录：`scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/`，里面通常包含：

- `job_portrait.json`：本次导出的岗位肖像（原始/基线）
- `job_portrait_optimized.json`：本次“完整优化版”岗位肖像（你要编辑，下一批会作为基线）
- `prompt_optimized.py`：本次“完整优化版” prompt（你要编辑，下一批会作为基线）
- `candidates/*.json`：候选人样本（已过滤：简历已加载 + 有 assistant 对话；analysis 使用数据库已有口径/legacy）
- `excluded_candidates.json`：被过滤掉的候选人列表与原因
- `overall_distribution.txt`：本批次 overall 分数分布（基于 candidates 文件里的 analysis）
- `优化报告.md`：轻量复盘报告（对比指标 + 问题清单/引用 + 改进记录）

> 重要：`download_data_for_prompt_optimization.py` **只负责下载与生成复盘骨架**，不会调用 OpenAI 重跑分析。  
> 需要用你最新的 `prompt_optimized.py` / `job_portrait_optimized.json` 生成“新口径 analysis + 新 message”时，请使用 `scripts/prompt_optmization/generate_optimized.py`（会把结果写入本批次目录，便于验证迭代是否生效）。

### 1.3.0 推荐顺序（减少浪费）

1) 先跑下载脚本（拿候选人样本与旧 analysis）
2) 先抽样回放 2-5 个“有问题”的候选人（用 `generate_optimized.py`）
3) 修 prompt/肖像后再回放验证，确认解决“典型问题”
4) 最后再考虑全量回放（本批次 10 个）与发布

例如（先跑下载脚本拿到 `run_...` 目录后）：

```bash
cd scripts/prompt_optmization
python generate_optimized.py --run-dir 架构师/run_YYYYMMDD_HHMMSS --limit 10
```

### 1.3.1 先抽样验证（推荐）

先挑 2-5 个“有问题/边界”的候选人（例如：问法太长、疑似越权、分数边界 6/7、或你想复盘的样本），用 `--start-index/--limit` 快速回放验证：

```bash
# 只回放第 2-3 个（按 candidates/*.json 的排序）
cd scripts/prompt_optmization
python generate_optimized.py \
  --run-dir 架构师/run_YYYYMMDD_HHMMSS \
  --start-index 2 \
  --limit 2
```

默认建议用 `--prompt-source md`（读取 `scripts/prompt_optmization/assistant_actions_prompts.md`，更接近线上口径）。  
只有当你明确要测试本批次目录里的 `prompt_optimized.py` 时，才使用 `--prompt-source optimized_py`。

确认回放后的 `generated/*.generated.json` 和 `优化报告.md` 的问题示例/统计更符合预期后，再决定是否全量回放本批次（limit=0 或 limit=10）。

### 1.3.2 怎么挑“有问题”的候选人（统一标准）

挑选标准（只挑你能说清楚“哪里不对”的样本，2-5 个足够）：

1) **analysis 结果不符合预期**（以 `generated/*.generated.json` 的 `analysis` 为准，忽略旧 analysis）
- 分数/阶段不合理：例如明显不匹配却给到高分或 CONTACT；或明显强匹配却给低分/PASS
- 评分表不自洽：`summary` 的门槛/场景/基础/契合/潜力/总分 与 `overall` 映射不一致
- 画像判断不合理：把“堆名词”当成“机制与取舍”；忽略故障复盘/取舍/量化指标

2) **generate 的 action 或 message 不符合预期**（看 `generated/*.generated.json` 的 `message_obj` + `message`）
- action 不对：该 PASS 却 CHAT；该 CONTACT 却 CHAT；或应该 WAIT 但仍在追问
- message 不合规：字数>160、多问（问号>1）、聊薪资、约时间/面试方式/地点、索要材料、问管理/绩效类问题
- 节奏不对：同一条 message 同时“推进HR安排”又继续追问（应二选一）

选出样本后，用 `generate_optimized.py --start-index/--limit` 针对这些候选人回放，验证你修改的 prompt/画像是否真的解决了问题。

---

## 1.4 提交/下载岗位肖像（推荐走 Vercel API，不依赖本地服务）

你在每个批次目录里会编辑 `job_portrait_optimized.json`，但最终需要把它发布到系统的 Jobs Store（会自动生成一个新版本 `_vN` 并切为 current），这样后续分析/对话都能直接用最新肖像。

> 说明：**岗位肖像**可以通过 API 发布后立即线上生效；岗位特定追问请更新到 `job_portrait_optimized.json` 的 `drill_down_questions` 并发布。  
> **prompt 本身**仍来自已部署的后端代码（`src/prompts/assistant_actions_prompts.py`）：它只负责“线上甄别的通用规则”，不需要引入岗位无关的复杂结构。

### 方式 A：Vercel（`vercel/api/jobs.py`，推荐）

下载 current 岗位肖像：

```bash
python scripts/prompt_optmization/publish_job_portrait.py \
  --api-type vercel \
  --api-base https://<YOUR_VERCEL_DOMAIN> \
  --download-job-id architecture \
  --download-out job_portrait.json
```

（可选）优化肖像（把“线上甄别追问清单”写进 `drill_down_questions`，且不新增 schema 字段）：

```bash
python scripts/prompt_optmization/optimize_job_portrait_json.py \
  --input job_portrait.json \
  --output job_portrait_optimized.json
```

> 该脚本还会把 `requirements` 写成“评分标准文本”（一行一个，总分 100），用于让分析口径稳定、可控。

发布（创建新版本）：

```bash
python scripts/prompt_optmization/publish_job_portrait.py \
  --api-type vercel \
  --api-base https://<YOUR_VERCEL_DOMAIN> \
  --job-portrait job_portrait_optimized.json
```

发布后验证（推荐用脚本拉取，便于留档）：

```bash
python scripts/prompt_optmization/publish_job_portrait.py \
  --api-type vercel \
  --api-base https://<YOUR_VERCEL_DOMAIN> \
  --download-job-id architecture \
  --download-out /tmp/architecture_current.json
```

验证（拉取 current 版本）：

```bash
curl https://<YOUR_VERCEL_DOMAIN>/api/jobs/architecture | python -m json.tool
```

### 方式 B：本地 FastAPI（`web/routes/jobs.py`，仅本地开发）

前提：本地服务已启动（例如 `python start_service.py`）。

```bash
python scripts/prompt_optmization/publish_job_portrait.py \
  --api-type local \
  --api-base http://127.0.0.1:8000 \
  --job-portrait scripts/prompt_optmization/架构师/run_YYYYMMDD_HHMMSS/job_portrait_optimized.json
```

验证：

```bash
curl http://127.0.0.1:8000/jobs/api/architecture | python -m json.tool
```

> 注意：发布时只会提交 jobs-store schema 允许的字段（如 `position/background/requirements/drill_down_questions/candidate_filters/keywords/notification`）。不要在肖像 JSON 顶层捏造新字段；需要额外信息请折叠进 `requirements` 或 `drill_down_questions`（文本化），避免与存储 schema 冲突。

---

## 2) 先读哪些文件（按顺序）

1) 系统设计方案（决定关键场景 & 压测题）  
- `scripts/prompt_optmization/架构师/基于EDA架构的PreSeen HighLevel Design.md`

2) 本批次目录（脚本输出）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/优化报告.md`（先看结论与对比指标）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/job_portrait.json`（看现状画像）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/candidates/*.json`（用于按引用抽样复盘）  
- `scripts/prompt_optmization/<岗位>/run_YYYYMMDD_HHMMSS/generated/*.generated.json`（新口径回放结果：analysis + message + 自动检测）  
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
同时 `generate_optimized.py` 会把“风险快照 + 问题示例（带引用）”写回 `优化报告.md`，便于你只抽样看关键问题，不需要逐个写每个候选人的长评。  
建议的迭代节奏：每批只改 1-3 个关键点（例如“评分表格式约束”或“关键场景题”），否则很难归因哪一条改动带来了收益/退化。
