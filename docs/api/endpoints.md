# API 端点速查

> 完整 API 文档请参考 [API_USAGE_GUIDE.md](API_USAGE_GUIDE.md)

## 基础信息

**Base URL**: `http://127.0.0.1:5001`

**响应格式** (v2.2.0+):
- 成功: 直接返回数据（dict/list/bool）
- 失败: `{"error": "错误描述"}` + HTTP 状态码（400/408/500）

## 端点列表

### 聊天相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/dialogs` | GET | 获取对话列表 |
| `/chat/{chat_id}/send` | POST | 发送消息 |
| `/chat/stats` | GET | 获取聊天统计 |
| `/chat/select-job` | POST | 选择职位 |

### 简历相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/resume/online` | POST | 查看在线简历 |
| `/resume/view_full` | POST | 查看完整简历 |
| `/resume/request` | POST | 请求完整简历 |
| `/resume/check_full_resume_available` | POST | 检查完整简历可用性 |
| `/resume/accept` | POST | 接受简历 |

### 推荐牛人

| 端点 | 方法 | 说明 |
|------|------|------|
| `/recommend/select-job` | POST | 选择职位 |
| `/recommend/candidates` | GET | 获取推荐列表 |
| `/recommend/candidate/{index}/resume` | GET | 查看候选人简历 |
| `/recommend/candidate/{index}/greet` | POST | 打招呼 |

### AI 助手

| 端点 | 方法 | 说明 |
|------|------|------|
| `/assistant/analyze-candidate` | POST | 分析候选人 |
| `/assistant/generate-chat-message` | POST | 生成消息 |
| `/assistant/upsert-candidate` | POST | 存储候选人 |
| `/assistant/get-candidate` | POST | 查询候选人 |

### 系统

| 端点 | 方法 | 说明 |
|------|------|------|
| `/status` | GET | 服务状态 |
| `/sentry-debug` | GET | Sentry 测试 |

## 快速示例

### 获取对话列表
```bash
curl "http://127.0.0.1:5001/chat/dialogs?limit=10"
```

### 发送消息
```bash
curl -X POST http://127.0.0.1:5001/chat/abc123/send \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

### 查看在线简历
```bash
curl -X POST http://127.0.0.1:5001/resume/online \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "abc123"}'
```

### 分析候选人
```bash
curl -X POST http://127.0.0.1:5001/assistant/analyze-candidate \
  -H "Content-Type: application/json" \
  -d '{
    "resume_text": "简历内容...",
    "job_requirements": "岗位要求..."
  }'
```

---

完整的请求/响应示例、错误处理、最佳实践请参考 [reference.md](reference.md)
