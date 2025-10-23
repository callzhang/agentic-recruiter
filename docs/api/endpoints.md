# API 端点速查

> 完整 API 文档请参考 [reference.md](reference.md)

## 基础信息

**Base URL**: `http://127.0.0.1:5001`

**响应格式** (v2.2.0+):
- 成功: 直接返回数据（dict/list/bool）
- 失败: `{"error": "错误描述"}` + HTTP 状态码（400/408/500）

## 端点列表

### 系统状态

| 端点 | 方法 | 说明 |
|------|------|------|
| `/status` | GET | 服务状态 |
| `/sentry-debug` | GET | Sentry 测试 |
| `/restart` | POST | 软重启服务 |
| `/debug/page` | GET | 调试页面信息 |
| `/debug/cache` | GET | 调试缓存信息 |

### 认证登录

| 端点 | 方法 | 说明 |
|------|------|------|
| `/login` | POST | 登录 Boss直聘 |

### 聊天相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/dialogs` | GET | 获取对话列表 |
| `/chat/{chat_id}/messages` | GET | 获取对话消息 |
| `/chat/{chat_id}/message` | POST | 发送消息 |
| `/chat/greet` | POST | 发送打招呼 |
| `/chat/stats` | GET | 获取聊天统计 |
| `/chat/candidate/discard` | POST | 丢弃候选人 |
| `/chat/contact/request` | POST | 请求联系方式 |

### 简历相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/resume/request` | POST | 请求完整简历 |
| `/chat/resume/full/{chat_id}` | GET | 查看完整简历 |
| `/chat/resume/check_full_resume_available` | POST | 检查完整简历可用性 |
| `/chat/resume/online/{chat_id}` | GET | 查看在线简历 |
| `/chat/resume/accept` | POST | 接受简历 |

### 候选人管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/store/candidate/{chat_id}` | GET | 获取候选人信息 |
| `/store/candidate/get-by-resume` | POST | 通过简历检查候选人 |

### 推荐牛人

| 端点 | 方法 | 说明 |
|------|------|------|
| `/recommend/candidates` | GET | 获取推荐列表 |
| `/recommend/candidate/{index}/resume` | GET | 查看候选人简历 |
| `/recommend/candidate/{index}/greet` | POST | 打招呼 |

### AI 助手

| 端点 | 方法 | 说明 |
|------|------|------|
| `/assistant/list` | GET | 获取助手列表 |
| `/assistant/create` | POST | 创建助手 |
| `/assistant/update/{assistant_id}` | POST | 更新助手 |
| `/assistant/delete/{assistant_id}` | DELETE | 删除助手 |

### 对话线程

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/generate-message` | POST | 生成消息 |
| `/chat/init-chat` | POST | 初始化对话线程 |
| `/chat/{thread_id}/messages` | GET | 获取线程消息 |
| `/chat/{thread_id}/analysis` | GET | 获取线程分析 |

### Web UI (新增)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/web` | GET | Web UI 首页 |
| `/web/stats` | GET | Web UI 统计 |
| `/web/candidates/*` | GET/POST | 候选人管理界面 |
| `/web/automation/*` | GET/POST | 自动化工作流界面 |
| `/web/assistants/*` | GET | 助手管理界面 |
| `/web/jobs/*` | GET | 岗位管理界面 |

## 快速示例

### 系统状态
```bash
# 检查服务状态
curl "http://127.0.0.1:5001/status"

# 软重启服务
curl -X POST "http://127.0.0.1:5001/restart"
```

### 聊天相关
```bash
# 获取对话列表
curl "http://127.0.0.1:5001/chat/dialogs?limit=10"

# 发送消息
curl -X POST http://127.0.0.1:5001/chat/abc123/message \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 获取聊天统计
curl "http://127.0.0.1:5001/chat/stats"
```

### 简历相关
```bash
# 查看在线简历
curl "http://127.0.0.1:5001/chat/resume/online/abc123"

# 查看完整简历
curl "http://127.0.0.1:5001/chat/resume/full/abc123"

# 请求完整简历
curl -X POST http://127.0.0.1:5001/chat/resume/request \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "abc123"}'
```

### 推荐牛人
```bash
# 获取推荐列表
curl "http://127.0.0.1:5001/recommend/candidates"

# 查看候选人简历
curl "http://127.0.0.1:5001/recommend/candidate/0/resume"

# 发送打招呼
curl -X POST http://127.0.0.1:5001/recommend/candidate/0/greet \
  -H "Content-Type: application/json" \
  -d '{"message": "你好，我对您的简历很感兴趣"}'
```

### AI 助手
```bash
# 生成消息
curl -X POST http://127.0.0.1:5001/chat/generate-message \
  -H "Content-Type: application/json" \
  -d '{
    "resume_text": "简历内容...",
    "job_requirements": "岗位要求...",
    "thread_id": "thread_123"
  }'

# 获取助手列表
curl "http://127.0.0.1:5001/assistant/list"
```

### 对话线程
```bash
# 初始化对话线程
curl -X POST http://127.0.0.1:5001/chat/init-chat \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_id": "candidate_123",
    "assistant_id": "asst_123",
    "job_id": "job_123"
  }'

# 获取线程消息
curl "http://127.0.0.1:5001/chat/thread_123/messages"

# 获取线程分析
curl "http://127.0.0.1:5001/chat/thread_123/analysis"
```

### Web UI
```bash
# 访问 Web UI
curl "http://127.0.0.1:5001/web"

# 获取 Web UI 统计
curl "http://127.0.0.1:5001/web/stats"
```

---

完整的请求/响应示例、错误处理、最佳实践请参考 [reference.md](reference.md)
