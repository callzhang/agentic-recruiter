# 招聘助理代理框架

## 概述

1. recruiter manager - recruiter 多代理框架。
2. Manager agent功能包括：
- jobs.yaml 中的职位描述
    - id
    - 职位
    - 关键词
    - 背景
    - 职责
    - 要求
    - ...
- agent.yaml 中的 recruiter 样式:
    - id
    - name
    - instructions
    - ...

- 浏览器实例管理，可与招聘网站(Boss直聘)进行交互。

3. recruiter agent功能包括：
- 从manager agent接收指令(State Dict)，信息包含：
    - job_info: 职位信息
    - agent_info: 招聘者样式
    - chat_id: 聊天ID(用于聊天界面)
    - recommend_id: 推荐ID(用于推荐界面)
- 决定下一步操作（think node），工具：
    - 获取在线简历（read online resume, read_full_resume）
    - 分析简历(analyze resume)
    - 询问联系方式(ask contact)
    - 发送信息(send message)
    - 通知HR(notify HR)
- 返回结果给manager agent
    - 结果包括：完整的对话信息
- ...

## Agent Nodes and Tools Definition
```mermaid
---
title: Manager - Recruiter Agent Framework
---
graph TD
%% state if_env_good <<choice>>
classDef tool fill:blue
classDef hitl color:black, stroke:yellow, fill:orange
%% Main flow
START --> CHECK_ENV ---> |good|MANAGER_THINK[manager think] ---> POOL_CANDIDATES e1@<====> INVOKE_RECRUITER
%% other conditions
CHECK_ENV --> start_browser([start browser instance]):::tool
CHECK_ENV --> start_web([start web portal]):::tool
CHECK_ENV <---> |missing|LET_FOR_USER_UPDATE[wait for user update]
LET_FOR_USER_UPDATE <--> |waiting for user update|SHOW_WEB_PORTAL([web portal]):::hitl
LET_FOR_USER_UPDATE --> |not found|MANAGER_THINK
MANAGER_THINK --> LET_FOR_USER_UPDATE
POOL_CANDIDATES --> check_info([check job, agent, db]):::tool
POOL_CANDIDATES --> LIST_CHAT_CANDIDATES([list chat candidates]):::tool
POOL_CANDIDATES --> LIST_RECOMMEND_CANDIDATES([list recommend candidates]):::tool
%% end of main flow
POOL_CANDIDATES --> |finished all candidates|REPORT_RESULTS[report results] --> END
%% error handling
POOL_CANDIDATES --> |network error|CHECK_ENV
POOL_CANDIDATES --> |net found error|LET_FOR_USER_UPDATE

subgraph INVOKE_RECRUITER[recruiter agent]
    THINK[observe and think] <--> |continue|ACTION
    THINK ---> |finished|END1
    ACTION --> READ_RESUME([read online resume]):::tool
    ACTION --> CHECK_FULL_RESUME([check full resume]):::tool
    ACTION --> REQUEST_FULL_RESUME([request full resume]):::tool
    ACTION --> READ_FULL_RESUME([read full resume]):::tool
    ACTION --> ANALYZE([analyze resume]):::tool
    ACTION --> READ_MESSAGES([read messages]):::tool
    ACTION --> ASK_CONACT([ask contact]):::tool
    ACTION --> SEND_MESSAGE([send message]):::tool
    ACTION --> NOTIFY_HR([notify HR]):::tool
    ACTION --> REJECT([reject candidate]):::tool
    ACTION --> UPLOAD_RECORD([upload record]):::tool
end
e1@{ animate: true }
```

### State Definition
#### Manager agent state:
```json
{
    "browser_endpoint": str, // "http://127.0.0.1:9222",
    "web_portal": str, // "http://127.0.0.1:5001",
    "job": dict,
    "persona": dict,
    "tasks": list[str], //"recommend" | "greet" | "chat" | "followup",
    "candidates": list[dict], // the candidates from the retruiter agent, e.g. [{"name": "John Doe", "resume": "John Doe is a software engineer with 3 years of experience in Python and Java.", "score": 8, "reasoning": "The candidate is a good fit for the job."}]
    "processed_candidates": list[dict], // the candidates that have been processed
}
```

#### Recruiter agent state:
```json
{
    "chat_id": str, // "abc_123",
    "recommend_id": int, // 4,
    "job_info": dict, 
    "agent_info": dict,
    "task": str, // "recommend" | "greet" | "chat" | "followup",
    "candidate": dict, // the candidate from the retruiter agent, e.g. {"name": "John Doe", "resume": "John Doe is a software engineer with 3 years of experience in Python and Java.", "score": 8, "reasoning": "The candidate is a good fit for the job."}
    "analysis": dict, // the result from the retruiter agent, e.g. {"skill": 8, "startup_fit": 7, "background": 9, "overall": 8, "summary": "The candidate is a good fit for the job.", "followup_tips": "You can ask the candidate to provide more details about their experience."}
    "messages": list[dict], //the messages from the retruiter agent, e.g. [{"role": "user", "content": "Hello, how are you?"}, {"role": "assistant", "content": "I'm good, thank you!"}]
    "error": dict, // the error from the retruiter agent, e.g. {"code": 400, "message": "Bad Request", "details": "the website is not responding."}
}
```