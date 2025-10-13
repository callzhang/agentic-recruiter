# AI 助手使用指南

OpenAI + Zilliz 集成使用指南

## 概述

AI 助手集成 OpenAI GPT-4 和 Zilliz 向量数据库，提供候选人分析和消息生成功能。

## 核心功能

### 1. 候选人分析

**API**: `POST /assistant/analyze-candidate`

**功能**: 分析候选人简历与岗位匹配度

**请求**:
```json
{
  "resume_text": "简历内容...",
  "job_requirements": "岗位要求..."
}
```

**响应**:
```json
{
  "recommendation": "recommend|pass",
  "scores": {
    "技能匹配": 85,
    "经验匹配": 90,
    "学历匹配": 95
  },
  "reasoning": "候选人具有..."
}
```

### 2. 消息生成

**API**: `POST /assistant/generate-chat-message`

**功能**: 生成定制化对话消息

**请求**:
```json
{
  "chat_id": "abc123",
  "purpose": "greet|chat|followup",
  "chat_history": []
}
```

**响应**:
```json
{
  "message": "你好，我们对您的简历很感兴趣...",
  "analysis": {...}
}
```

### 3. 候选人存储

**API**: `POST /assistant/upsert-candidate`

**功能**: 存储候选人到 Zilliz

**请求**:
```json
{
  "chat_id": "abc123",
  "name": "张三",
  "resume_text": "简历内容...",
  "stage": "GREET"
}
```

### 4. 候选人查询

**API**: `POST /assistant/get-candidate`

**功能**: 从 Zilliz 查询候选人

**请求**:
```json
{
  "chat_id": "abc123"
}
```

## OpenAI Integration

### Assistant API

使用 OpenAI Assistant API 进行分析和生成：

```python
from src.assistant_actions import AssistantActions

assistant = AssistantActions()

# 分析候选人
analysis = assistant.analyze_candidate(
    resume_text="简历内容...",
    job_requirements="岗位要求..."
)

# 生成消息
message = assistant.generate_message(
    chat_id="abc123",
    purpose="greet",
    chat_history=[]
)
```

### Thread API

每个候选人一个 Thread，持久化对话历史：

```python
# 初始化 Thread
result = assistant.init_chat(
    chat_id="abc123",
    resume_text="简历内容...",
    job_description="岗位描述..."
)

thread_id = result["thread_id"]

# 后续对话使用同一个 Thread
# Thread ID 存储在 Zilliz 中，自动关联
```

### Embedding 生成

自动生成简历 Embedding：

```python
from src.assistant_actions import AssistantActions

assistant = AssistantActions()

# 自动生成 Embedding
embedding = assistant.get_embedding("简历文本...")

# 存储时自动生成
assistant.upsert_candidate(
    chat_id="abc123",
    resume_text="简历内容..."
    # Embedding 自动生成并存储
)
```

## Zilliz Integration

### 数据结构

```python
{
    "candidate_id": "uuid-...",
    "chat_id": "abc123",
    "name": "张三",
    "resume_text": "在线简历...",
    "full_resume": "完整简历...",
    "resume_vector": [0.1, 0.2, ...],  # 1536 维
    "thread_id": "thread_...",
    "analysis": '{"scores": {...}}',
    "stage": "GREET",
    "updated_at": 1697000000
}
```

### 向量搜索

```python
from src.candidate_store import candidate_store

# 相似度搜索
results = candidate_store.search_candidates(
    query_text="Python 后端开发",
    top_k=5
)

for result in results:
    print(f"{result['name']}: {result['score']}")
```

### CRUD 操作

```python
from src.candidate_store import candidate_store

# 创建/更新
candidate_store.upsert_candidate(
    chat_id="abc123",
    data={"name": "张三", "resume_text": "..."}
)

# 查询
candidate = candidate_store.get_candidate_by_chat_id("abc123")

# 删除
candidate_store.delete_candidate(chat_id="abc123")
```

## 配置

### OpenAI 配置

`config/secrets.yaml`:
```yaml
openai:
  api_key: sk-...
```

`config/config.yaml`:
```yaml
openai:
  name: CN_recruiting_bot
  model: gpt-4o-mini
  temperature: 0.7
  max_tokens: 2000
```

### Zilliz 配置

`config/secrets.yaml`:
```yaml
zilliz:
  endpoint: https://...
  user: db_...
  password: ...
```

`config/config.yaml`:
```yaml
zilliz:
  collection_name: CN_candidates
  embedding_model: text-embedding-3-small
  embedding_dim: 1536
  similarity_top_k: 5
```

## 使用示例

### 完整流程

```python
from streamlit_shared import call_api

# 1. 获取简历
ok, resume = call_api("POST", "/resume/online", 
                      json={"chat_id": "abc123"})

# 2. 分析候选人
ok, analysis = call_api("POST", "/assistant/analyze-candidate",
                        json={
                            "resume_text": resume["text"],
                            "job_requirements": "Python 3年经验..."
                        })

# 3. 生成消息
if analysis["recommendation"] == "recommend":
    ok, message = call_api("POST", "/assistant/generate-chat-message",
                           json={
                               "chat_id": "abc123",
                               "purpose": "greet",
                               "chat_history": []
                           })
    
    # 4. 发送消息
    ok, result = call_api("POST", "/chat/abc123/send",
                          json={"message": message["message"]})
    
    # 5. 存储候选人
    ok, stored = call_api("POST", "/assistant/upsert-candidate",
                          json={
                              "chat_id": "abc123",
                              "resume_text": resume["text"],
                              "stage": "GREET"
                          })
```

## 最佳实践

### 1. Token 管理
- 简历文本限制在 4096 字符
- 使用 truncation 避免超限
- 监控 token 使用量

### 2. 缓存策略
- 优先从 Zilliz 读取
- 避免重复分析
- 定期更新 Embedding

### 3. 错误处理
- 捕获 OpenAI API 错误
- 处理 rate limit
- 重试机制

### 4. 成本优化
- 使用 gpt-4o-mini（更便宜）
- 批量处理减少调用次数
- 缓存分析结果

## 故障排查

### OpenAI 错误
```
BadRequestError: This model's maximum context length is 8192 tokens
```
**解决**: 截断简历文本到 4096 字符

### Zilliz 错误
```
MilvusException: collection not found
```
**解决**: 运行 `scripts/zilliz_manager.py` 创建 collection

### Embedding 错误
```
resume_vector field is required
```
**解决**: 确保调用 `get_embedding()` 生成 embedding

## 相关文档

- [工作流指南](workflows.md)
- [API 文档](../api/reference.md)
- [技术规范](../technical.md)

---

**快速链接**: [README](../../README.md) | [ARCHITECTURE](../../ARCHITECTURE.md)

