# API 文档

Boss直聘自动化机器人 REST API 文档

## 文档导航

- **[API 完整参考](reference.md)** - v2.2.0+ 完整 API 文档
  - 所有端点详细说明
  - 请求/响应示例
  - 错误处理
  - 最佳实践

- **[端点速查](endpoints.md)** - 快速查找 API 端点
  - 端点列表
  - 快速示例
  - curl 命令

## API 版本

**当前版本**: v2.2.0  
**Base URL**: `http://127.0.0.1:5001`

## 核心特性 (v2.2.0)

### 响应格式
- **成功**: 直接返回数据（dict, list, bool）
- **失败**: HTTP 错误 + `{"error": "描述"}`

### HTTP 状态码
- `200` - 成功
- `400` - 请求错误 (ValueError)
- `408` - 请求超时 (Playwright 超时)
- `500` - 服务器错误 (RuntimeError, Exception)

## 端点分类

### 聊天相关
- 获取对话列表
- 发送消息
- 查看简历
- 请求完整简历

### 推荐牛人
- 获取推荐列表
- 查看候选人简历
- 打招呼

### AI 助手
- 分析候选人
- 生成消息
- 存储/查询候选人

### 系统
- 服务状态
- 健康检查

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

### 分析候选人
```bash
curl -X POST http://127.0.0.1:5001/assistant/analyze-candidate \
  -H "Content-Type: application/json" \
  -d '{
    "resume_text": "简历内容...",
    "job_requirements": "岗位要求..."
  }'
```

## 错误处理

所有 API 错误返回 JSON 格式：
```json
{
  "error": "错误描述"
}
```

配合 HTTP 状态码使用：
- `400` - 检查请求参数
- `408` - 操作超时，可重试
- `500` - 服务器错误，查看 Sentry

## 相关文档

- [技术规范](../technical.md) - 架构和实现细节
- [系统架构](../../ARCHITECTURE.md) - 快速概览
- [变更日志](../../CHANGELOG.md) - API 版本历史

---

**完整文档**: [reference.md](reference.md) | **快速查找**: [endpoints.md](endpoints.md)


