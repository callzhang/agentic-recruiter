# 自动化工作流

Boss直聘自动化机器人的 4 个独立工作流入口

## 概述

每个工作流可独立执行，处理不同来源的候选人，支持阶段双向转换。

## 工作流入口

### 1. 推荐牛人

**数据源**: Boss直聘推荐页面

**流程**:
```
获取推荐列表 → 提取简历 → AI 分析 → 决策阶段 → 打招呼 → 存储
```

**适用场景**:
- 主动寻找候选人
- 批量处理推荐牛人
- 首次接触候选人

**关键API**:
- `GET /recommend/candidates`
- `POST /assistant/analyze-candidate`
- `POST /recommend/candidate/{idx}/greet`

### 2. 新招呼

**数据源**: 聊天列表"新招呼"标签页

**流程**:
```
获取新招呼 → 查询存储 → 提取简历 → AI 分析 → 生成回复 → 发送
```

**适用场景**:
- 候选人主动打招呼
- 首次回复
- 快速筛选

**关键API**:
- `GET /chat/dialogs?tab=新招呼&status=未读`
- `POST /assistant/generate-chat-message`
- `POST /chat/{chat_id}/send`

### 3. 沟通中

**数据源**: 聊天列表"沟通中"标签页

**流程**:
```
获取对话 → 查询缓存 → 请求完整简历 → 重新分析 → 生成回复
```

**适用场景**:
- 持续对话
- 深入沟通
- 获取完整简历后重新评估

**关键API**:
- `GET /chat/dialogs?tab=沟通中&status=未读`
- `POST /resume/request`
- `POST /resume/view_full`

### 4. 追结果

**数据源**: Zilliz 存储的超时候选人

**流程**:
```
查询超时候选人 → 筛选阶段 → 生成跟进消息 → 发送
```

**适用场景**:
- 候选人长时间未回复
- 催促简历
- 跟进联系方式

**关键API**:
- Zilliz 直接查询
- `POST /assistant/generate-chat-message?purpose=followup`
- `POST /chat/{chat_id}/send`

## 候选人阶段

### 阶段定义

- **PASS**: 不匹配，已拒绝
- **GREET**: 表达兴趣，已索要简历
- **SEEK**: 强匹配，寻求联系方式
- **CONTACT**: 已获得联系方式
- **WAITING_LIST**: 待定，需进一步沟通

### 阶段转换

所有工作流都可以在阶段间双向转换：

```
PASS ↔ GREET ↔ SEEK ↔ CONTACT
        ↕
  WAITING_LIST
```

**示例**:
- 工作流 1 (推荐牛人): NULL → GREET/SEEK/PASS
- 工作流 2 (新招呼): NULL → GREET/PASS
- 工作流 3 (沟通中): GREET → SEEK 或 SEEK → GREET (倒退)
- 工作流 4 (追结果): GREET/SEEK → GREET (重新跟进)

## 数据存储

### Zilliz Schema

```python
{
    "candidate_id": str,      # UUID 主键
    "chat_id": str,           # Boss直聘 chat_id
    "name": str,              # 候选人姓名
    "resume_text": str,       # 在线简历
    "full_resume": str,       # 完整简历
    "resume_vector": [float], # Embedding
    "thread_id": str,         # OpenAI Thread
    "analysis": str,          # 分析结果 JSON
    "stage": str,             # 当前阶段
    "updated_at": int,        # 时间戳
}
```

### 缓存策略

- 优先从 Zilliz 读取简历
- 避免重复 Playwright 操作
- 减少浏览器操作耗时

## AI 消息生成

### Purpose 标志

```python
generate_message(
    chat_id=...,
    purpose="greet|chat|followup",
    chat_history=[...]
)
```

- **greet**: 首次打招呼
- **chat**: 常规对话回复
- **followup**: 跟进催促

### OpenAI Thread

- 每个候选人一个 Thread
- 持久化对话历史
- 上下文连续性

## 实现示例

### Streamlit UI 调用

```python
import streamlit as st
from streamlit_shared import call_api

# 工作流 1: 推荐牛人
def process_recommendations():
    ok, candidates = call_api("GET", "/recommend/candidates")
    
    for idx, candidate in enumerate(candidates):
        # 获取简历
        ok, resume = call_api("GET", f"/recommend/candidate/{idx}/resume")
        
        # AI 分析
        ok, analysis = call_api("POST", "/assistant/analyze-candidate", 
                                json={"resume_text": resume["text"]})
        
        if analysis["recommendation"] == "recommend":
            # 生成消息
            ok, message = call_api("POST", "/assistant/generate-chat-message",
                                   json={"purpose": "greet"})
            
            # 打招呼
            ok, result = call_api("POST", f"/recommend/candidate/{idx}/greet",
                                  json={"message": message["message"]})
```

## 最佳实践

1. **批量处理**: 使用并发处理多个候选人
2. **缓存优先**: 先查询 Zilliz，避免重复操作
3. **错误处理**: 捕获异常，记录失败候选人
4. **进度显示**: 使用 Streamlit spinner 提示用户
5. **阶段管理**: 根据分析结果动态更新阶段

## 相关文档

- [AI 助手使用](ai-assistant.md)
- [技术规范](../technical.md)
- [API 文档](../api/reference.md)

---

**快速链接**: [README](../../README.md) | [ARCHITECTURE](../../ARCHITECTURE.md)

