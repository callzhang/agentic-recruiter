# Agent 框架

基于 LangGraph 的多代理招聘框架

## 概述

招聘助理代理框架包含两个主要代理：
1. **Manager Agent** - 管理多个 Recruiter Agent，协调任务分配
2. **Recruiter Agent** - 处理单个候选人的完整流程

## 架构

```
Manager Agent
    ↓ 分配任务
Recruiter Agent (处理单个候选人)
    ↓ 调用工具
FastAPI Service (Boss直聘操作)
```

## Manager Agent

**功能**:
- 管理职位信息 (从 jobs.yaml/Zilliz)
- 管理招聘者样式 (从 assistants.yaml)
- 浏览器实例管理
- 任务分配和协调

**State**:
```python
{
    "browser_endpoint": str,      # Chrome CDP URL
    "web_portal": str,            # FastAPI 服务 URL
    "job": dict,                  # 职位信息
    "persona": dict,              # 招聘者样式
    "tasks": list[str],           # "recommend" | "greet" | "chat" | "followup"
    "candidates": list[dict],     # 候选人列表
    "processed_candidates": list[dict]
}
```

## Recruiter Agent

**功能**:
- 从 Manager 接收任务和上下文
- 决定下一步操作（think node）
- 调用工具处理候选人
- 返回处理结果

**工具**:
- `read_online_resume` - 读取在线简历
- `read_full_resume` - 读取完整简历
- `analyze_resume` - 分析简历
- `send_message` - 发送消息
- `ask_contact` - 请求联系方式
- `reject_candidate` - 拒绝候选人
- `notify_hr` - 通知 HR
- `upload_record` - 上传记录到 Zilliz

**State**:
```python
{
    "chat_id": str,              # Boss直聘 chat_id
    "recommend_id": int,         # 推荐列表索引
    "job_info": dict,            # 职位信息
    "agent_info": dict,          # 招聘者样式
    "task": str,                 # 任务类型
    "candidate": dict,           # 候选人信息
    "analysis": dict,            # 分析结果
    "messages": list[dict],      # 对话历史
    "error": dict                # 错误信息
}
```

## 工作流

### Manager 工作流
```
START → CHECK_ENV → MANAGER_THINK → POOL_CANDIDATES ↔ INVOKE_RECRUITER → REPORT_RESULTS
```

### Recruiter 工作流
```
THINK (观察和思考) ↔ ACTION (执行工具) → 循环直到完成
```

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
from agent.graph import create_manager_graph

graph = create_manager_graph()
config = {
    "configurable": {
        "thread_id": "thread_123",
        "web_portal": "http://127.0.0.1:5001"
    }
}

result = graph.invoke({
    "job": {...},
    "persona": {...},
    "tasks": ["recommend"]
}, config)
```

---

相关文档: [系统架构](architecture.md) | [工作流](workflows.md) | [LangGraph 文档](langgraph_comprehensive_notes.md)
