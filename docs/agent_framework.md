# Agent 框架

基于 LangGraph 的多代理招聘框架

## 概述

招聘助理代理框架包含两个主要代理：
1. **Manager Agent（管理智能体）** - 管理多个 Recruiter Agent，协调任务分配，负责整体流程编排
2. **Recruiter Agent（招聘顾问智能体）** - 处理单个候选人的完整流程，包括简历分析、消息生成、决策执行

## 架构

```
Manager Agent
    ↓ 分配任务
Recruiter Agent (处理单个候选人)
    ↓ 调用工具
FastAPI Service (Boss直聘操作)
    ↓
Playwright + OpenAI + Zilliz
```

## 技术实现

- **框架**: LangGraph
- **模型**: OpenAI GPT-5-mini (Responses API)
- **状态管理**: LangGraph Store (支持断点续传)
- **工具系统**: LangChain Tools (调用 FastAPI 端点)

## Manager Agent

**功能**:
- 管理职位信息 (从 jobs.yaml/Zilliz)
- 管理招聘者样式 (从 assistants.yaml)
- 浏览器实例管理
- 任务分配和协调

**State** (ManagerState):
```python
{
    "messages": list[AnyMessage],      # 对话消息历史
    "candidates": list[Candidate],     # 候选人列表
    "processed_candidates": list[Candidate],  # 已处理候选人
    "jobs": list[dict],                # 岗位列表（从 /jobs/api/list 获取）
    "assistants": list[dict],          # 助手列表（从 /assistant/list 获取）
    "assistant_name": str,              # 当前使用的助手名称
    "current_candidate": Candidate     # 当前处理的候选人
}
```

**Context** (ContextSchema):
```python
{
    "web_portal": str,                 # FastAPI 服务 URL (默认: http://127.0.0.1:5001)
    "timeout": float,                  # API 请求超时时间 (默认: 30.0)
    "model": str,                      # LLM 模型名称 (默认: gpt-5-mini)
    "limit": int,                      # 处理数量限制 (默认: 10)
    "dingtalk_webhook": str            # DingTalk Webhook URL
}
```

## Recruiter Agent

**功能**:
- 从 Manager 接收任务和上下文
- 决定下一步操作（think node）
- 调用工具处理候选人
- 返回处理结果

**工具** (分类):
- **简历工具** (`resume_tools`):
  - `view_online_resume_tool` - 查看在线简历
  - `view_full_resume_tool` - 查看完整简历
  - `request_full_resume_tool` - 请求完整简历
  - `check_resume_availability_tool` - 检查完整简历是否可用
  - `accept_full_resume_tool` - 接受完整简历

- **沟通工具** (`chat_tools`):
  - `send_chat_message_tool` - 发送消息
  - `get_chat_messages_tool` - 获取对话历史
  - `greet_candidate_tool` - 发送招呼
  - `request_contact_tool` - 请求联系方式

- **决策工具** (`action_tools`):
  - `analyze_resume_tool` - 分析简历并评分
  - `notify_hr_tool` - 通知 HR（当候选人在 SEEK 阶段时）
  - `finish_tool` - 完成处理并生成报告

**State** (RecruiterState):
```python
{
    "stage": Literal["GREET", "PASS", "CHAT", "SEEK", "CONTACT"],  # 候选人阶段
    "candidate": Candidate,        # 候选人信息（包含 mode, chat_id/index, job_applied 等）
    "analysis": dict,              # 分析结果（skill, startup_fit, background, overall, summary, followup_tips）
    "messages": list[AnyMessage]   # 对话消息历史
}
```

## 工作流

### Manager 工作流
```
START → check_env (检查环境) → manager_plan (规划任务) 
    ↓ (调用工具)
manager_tool_node (执行工具)
    ↓ (dispatch_candidate_tool)
dispatch_recruiter (调用 Recruiter Agent)
    ↓ (返回结果)
manager_plan (继续规划)
    ↓ (finish_tool)
END
```

**关键节点**:
- `check_env`: 检查浏览器状态、获取岗位和助手列表
- `manager_plan`: Manager Agent 思考并决定下一步操作
- `manager_tool_node`: 执行 Manager 工具（获取候选人、分配任务等）
- `dispatch_recruiter`: 调用 Recruiter Graph 处理单个候选人

### Recruiter 工作流
```
START → recruiter_think (分析思考)
    ↓ (决定调用工具)
execute_tools (执行工具)
    ↓ (工具执行完成)
recruiter_think (继续思考)
    ↓ (finish_tool)
END
```

**关键节点**:
- `recruiter_think`: Recruiter Agent 基于岗位要求和候选人信息思考下一步
- `execute_tools`: 执行工具（查看简历、分析、发送消息等）
- 循环执行直到调用 `finish_tool` 完成处理

## 实现

**文件**:
- `agent/graph.py` - LangGraph 图定义
- `agent/tools.py` - 工具函数实现
- `agent/states.py` - 状态定义
- `agent/prompts.py` - 提示词

**关键组件**:
- Manager Graph - 主协调图
- Recruiter Subgraph - 候选人处理子图
- Tool Functions - 调用 FastAPI 端点

## 使用

```python
from agent.graph import manager_graph
from agent.states import ContextSchema, ManagerInputState
from langchain_core.messages import HumanMessage

# 配置上下文
context = ContextSchema(
    web_portal="http://127.0.0.1:5001",
    timeout=30.0,
    model="gpt-5-mini",
    limit=10,
    dingtalk_webhook="https://oapi.dingtalk.com/robot/send?access_token=..."
)

# 初始化输入
input_state = ManagerInputState(
    messages=[HumanMessage(content="我需要处理推荐牛人，岗位是算法工程师，处理10个候选人")]
)

# 执行工作流
result = manager_graph.invoke(
    input_state,
    config={"context": context}
)
```

## API 端点映射

Agent 工具通过调用以下 FastAPI 端点实现功能：

- **候选人管理**: `GET /chat/dialogs`, `GET /recommend/candidates`
- **简历处理**: `GET /chat/resume/online/{chat_id}`, `GET /chat/resume/full/{chat_id}`
- **消息发送**: `POST /chat/{chat_id}/send_message`, `POST /chat/greet`
- **岗位和助手**: `GET /jobs/api/list`, `GET /assistant/list`

---

相关文档: [系统架构](architecture.md) | [工作流](workflows.md) | [LangGraph 文档](langgraph_comprehensive_notes.md)
