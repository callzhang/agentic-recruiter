# API 使用指南 (v2.2.0+)

## 快速开始

### 基本原则

自 v2.2.0 起，所有 API 端点遵循以下原则：

1. **成功响应**: 直接返回数据（dict, list, bool）
2. **失败响应**: 返回 HTTP 错误状态码 + `{"error": "错误描述"}`
3. **无包装对象**: 不再使用 `{"success": bool, "details": str}` 格式

### HTTP 状态码

| 状态码 | 含义 | 典型场景 |
|--------|------|---------|
| 200 | 成功 | 正常响应 |
| 400 | 请求错误 | 参数验证失败、业务逻辑错误 |
| 408 | 请求超时 | Playwright 操作超时 |
| 500 | 服务器错误 | 未预期的系统错误 |

## API 端点详解

### 1. 聊天相关

#### 获取对话列表
```bash
GET /chat/dialogs?limit=10&tab=全部&status=全部&job_title=
```

**成功响应 (200)**:
```json
[
  {
    "chat_id": "abc123",
    "name": "张三",
    "last_message": "你好",
    "time": "2024-10-11 10:00",
    "unread": true
  }
]
```

**失败响应 (400)**:
```json
{
  "error": "未找到对话列表"
}
```

#### 发送消息
```bash
POST /chat/{chat_id}/send
Content-Type: application/json

{
  "message": "你好，感谢投递"
}
```

**成功响应 (200)**:
```json
true
```

**失败响应 (400)**:
```json
{
  "error": "未找到指定对话项"
}
```

#### 获取聊天统计
```bash
GET /chat/stats
```

**成功响应 (200)**:
```json
{
  "new_message_count": 5,
  "new_greet_count": 3
}
```

### 2. 简历相关

#### 请求完整简历
```bash
POST /resume/request
Content-Type: application/json

{
  "chat_id": "abc123"
}
```

**成功响应 (200)**:
```json
true
```

**失败响应 (400)**:
```json
{
  "error": "未找到指定对话项"
}
```

#### 查看在线简历
```bash
POST /resume/online
Content-Type: application/json

{
  "chat_id": "abc123"
}
```

**成功响应 (200)**:
```json
{
  "text": "姓名：张三\n学历：本科\n...",
  "name": "张三",
  "chat_id": "abc123"
}
```

**失败响应 (400)**:
```json
{
  "error": "未找到在线简历"
}
```

#### 查看完整简历
```bash
POST /resume/view_full
Content-Type: application/json

{
  "chat_id": "abc123"
}
```

**成功响应 (200)**:
```json
{
  "text": "详细简历内容...",
  "pages": ["page1.png", "page2.png"]
}
```

**失败响应 (408)**:
```json
{
  "error": "操作超时: Timeout 30000ms exceeded."
}
```

#### 检查完整简历可用性
```bash
POST /resume/check_full_resume_available
Content-Type: application/json

{
  "chat_id": "abc123"
}
```

**成功响应 (200)**:
```json
true
```

### 3. 推荐牛人

#### 选择职位
```bash
POST /recommend/select-job
Content-Type: application/json

{
  "job_name": "Python后端开发"
}
```

**成功响应 (200)**:
```json
{
  "selected_job": "Python后端开发",
  "available_jobs": ["Python后端开发", "Go后端开发"]
}
```

**失败响应 (400)**:
```json
{
  "error": "未找到职位下拉菜单"
}
```

#### 获取推荐候选人列表
```bash
GET /recommend/candidates
```

**成功响应 (200)**:
```json
[
  {
    "index": 0,
    "name": "李四",
    "title": "Python开发工程师",
    "company": "某科技公司"
  }
]
```

**失败响应 (400)**:
```json
{
  "error": "未找到候选人列表"
}
```

#### 查看候选人简历
```bash
GET /recommend/candidate/{index}/resume
```

**成功响应 (200)**:
```json
{
  "text": "姓名：李四\n工作经历：..."
}
```

#### 打招呼
```bash
POST /recommend/candidate/{index}/greet
Content-Type: application/json

{
  "message": "你好，我们有个职位..."
}
```

**成功响应 (200)**:
```json
true
```

### 4. AI助手

#### 生成消息
```bash
POST /assistant/generate-chat-message
Content-Type: application/json

{
  "chat_id": "abc123",
  "purpose": "reply",
  "chat_history": []
}
```

**成功响应 (200)**:
```json
{
  "message": "感谢您的投递，您的简历...",
  "analysis": {
    "匹配度": "高",
    "理由": "..."
  }
}
```

**失败响应 (500)**:
```json
{
  "error": "消息生成失败，请稍后重试"
}
```

#### 分析候选人
```bash
POST /assistant/analyze-candidate
Content-Type: application/json

{
  "resume_text": "简历内容...",
  "job_requirements": "岗位要求..."
}
```

**成功响应 (200)**:
```json
{
  "recommendation": "recommend",
  "scores": {
    "技能匹配": 85,
    "经验匹配": 90
  },
  "reasoning": "候选人具有..."
}
```

## 错误处理最佳实践

### Python (requests)

```python
import requests

def call_api(method: str, endpoint: str, **kwargs):
    """统一的 API 调用函数"""
    url = f"http://localhost:5001{endpoint}"
    response = requests.request(method, url, **kwargs)
    
    # 检查 HTTP 状态码
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 400:
        error = response.json().get("error", "请求错误")
        raise ValueError(error)
    elif response.status_code == 408:
        error = response.json().get("error", "请求超时")
        raise TimeoutError(error)
    elif response.status_code == 500:
        error = response.json().get("error", "服务器错误")
        raise RuntimeError(error)
    else:
        raise Exception(f"未知错误: {response.status_code}")

# 使用示例
try:
    result = call_api("POST", "/chat/abc123/send", json={"message": "Hello"})
    if result is True:
        print("消息发送成功")
except ValueError as e:
    print(f"请求参数错误: {e}")
except TimeoutError as e:
    print(f"操作超时: {e}")
except RuntimeError as e:
    print(f"服务器错误: {e}")
```

### JavaScript (fetch)

```javascript
async function callApi(method, endpoint, body = null) {
    const url = `http://localhost:5001${endpoint}`;
    const options = {
        method,
        headers: {'Content-Type': 'application/json'}
    };
    
    if (body) {
        options.body = JSON.stringify(body);
    }
    
    const response = await fetch(url, options);
    
    if (response.ok) {
        return await response.json();
    }
    
    const error = await response.json();
    const errorMessage = error.error || '未知错误';
    
    switch (response.status) {
        case 400:
            throw new Error(`请求错误: ${errorMessage}`);
        case 408:
            throw new Error(`请求超时: ${errorMessage}`);
        case 500:
            throw new Error(`服务器错误: ${errorMessage}`);
        default:
            throw new Error(`未知错误 (${response.status}): ${errorMessage}`);
    }
}

// 使用示例
try {
    const result = await callApi('POST', '/chat/abc123/send', {
        message: 'Hello'
    });
    
    if (result === true) {
        console.log('消息发送成功');
    }
} catch (error) {
    console.error('操作失败:', error.message);
}
```

### Streamlit (已集成)

在 Streamlit 页面中使用 `streamlit_shared.py` 的 `call_api` 函数：

```python
from streamlit_shared import call_api
import streamlit as st

try:
    ok, result = call_api("POST", "/chat/abc123/send", json={"message": "Hello"})
    if ok and result is True:
        st.success("消息发送成功")
    else:
        st.error(f"发送失败: {result}")
except Exception as e:
    st.error(f"操作失败: {str(e)}")
```

## 常见错误处理

### 1. ValueError (400)
**原因**: 参数验证失败、业务逻辑错误
**示例**: 
- "未找到指定对话项"
- "消息内容不能为空"
- "无效的职位名称"

**解决方法**:
- 检查请求参数是否正确
- 确认资源（chat_id, job_name 等）是否存在
- 验证输入数据格式

### 2. TimeoutError (408)
**原因**: Playwright 操作超时（默认30秒）
**示例**:
- "操作超时: Timeout 30000ms exceeded."
- 页面加载缓慢
- 网络连接不稳定

**解决方法**:
- 重试请求
- 检查网络连接
- 检查 Boss 直聘网站状态
- 考虑增加超时时间（如果是系统配置问题）

### 3. RuntimeError (500)
**原因**: 未预期的系统错误
**示例**:
- "消息生成失败，请稍后重试"
- OpenAI API 调用失败
- 数据库连接错误

**解决方法**:
- 查看 Sentry 错误追踪
- 检查日志文件
- 联系系统管理员
- 确认依赖服务（OpenAI, Zilliz）正常运行

## 测试 API

### 使用 curl

```bash
# 健康检查
curl http://localhost:5001/status

# 获取对话列表
curl "http://localhost:5001/chat/dialogs?limit=5"

# 发送消息
curl -X POST http://localhost:5001/chat/abc123/send \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 测试 Sentry（会触发 ZeroDivisionError）
curl http://localhost:5001/sentry-debug
```

### 使用 Python

```python
import requests

# 健康检查
response = requests.get("http://localhost:5001/status")
print(response.json())

# 获取对话列表
response = requests.get("http://localhost:5001/chat/dialogs", params={"limit": 5})
dialogs = response.json()
print(f"找到 {len(dialogs)} 个对话")

# 发送消息
response = requests.post(
    "http://localhost:5001/chat/abc123/send",
    json={"message": "你好"}
)

if response.status_code == 200 and response.json() is True:
    print("消息发送成功")
else:
    error = response.json().get("error")
    print(f"消息发送失败: {error}")
```

### 使用 Postman

1. **导入集合**: 创建新的 Collection
2. **添加环境变量**: `base_url = http://localhost:5001`
3. **创建请求示例**:
   - 方法: POST
   - URL: `{{base_url}}/chat/abc123/send`
   - Body (JSON):
     ```json
     {
       "message": "你好"
     }
     ```
4. **查看响应**: 
   - 成功: `true` (Status 200)
   - 失败: `{"error": "错误描述"}` (Status 400/408/500)

## 监控和调试

### Sentry Dashboard

1. 访问 Sentry Dashboard: https://sentry.io
2. 查看错误列表
3. 过滤条件：
   - `exception_type`: 按异常类型过滤（ValueError, RuntimeError, etc.）
   - `environment`: 按环境过滤（development, production）
   - `url`: 按端点过滤
4. 查看详细信息：
   - 完整堆栈跟踪
   - 请求上下文（URL, method, path）
   - 用户信息（如果配置）
   - Breadcrumbs（操作历史）

### 日志文件

查看服务日志：

```bash
# 查看实时日志
tail -f logs/boss_service.log

# 搜索错误
grep ERROR logs/boss_service.log

# 搜索特定 API 调用
grep "/chat/.*send" logs/boss_service.log
```

### FastAPI 文档

访问自动生成的 API 文档：

- Swagger UI: http://localhost:5001/docs
- ReDoc: http://localhost:5001/redoc

这些文档会自动反映最新的 API 变更和响应格式。

## 性能优化建议

### 1. 缓存响应

对于不变的数据（如简历），使用客户端缓存：

```python
import functools
import time

@functools.lru_cache(maxsize=100)
def get_resume_cached(chat_id: str):
    response = requests.post(
        "http://localhost:5001/resume/online",
        json={"chat_id": chat_id}
    )
    return response.json()

# 5分钟后清除缓存
time.sleep(300)
get_resume_cached.cache_clear()
```

### 2. 批量请求

如果需要处理多个请求，使用并发：

```python
from concurrent.futures import ThreadPoolExecutor
import requests

def send_message(chat_id: str, message: str):
    return requests.post(
        f"http://localhost:5001/chat/{chat_id}/send",
        json={"message": message}
    )

chat_ids = ["abc123", "def456", "ghi789"]
messages = ["消息1", "消息2", "消息3"]

with ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(send_message, chat_ids, messages))

for i, result in enumerate(results):
    if result.status_code == 200:
        print(f"消息 {i+1} 发送成功")
```

### 3. 超时设置

设置合理的超时时间：

```python
import requests

# 连接超时5秒，读取超时30秒
response = requests.post(
    "http://localhost:5001/resume/view_full",
    json={"chat_id": "abc123"},
    timeout=(5, 30)
)
```

## 版本兼容性

### v2.2.0+ (当前)
- 所有端点返回原始数据类型
- 基于 HTTP 状态码的错误处理
- Sentry 自动错误追踪

### v2.0.0 - v2.1.0 (已弃用)
- 使用 `{"success": bool, "details": str}` 包装对象
- 所有响应都是 200 状态码
- 需要检查 `success` 字段

### 迁移指南

如果你有使用旧版本 API 的代码，请参考 `docs/api_refactoring_2024.md` 进行迁移。

## 支持和反馈

- **问题反馈**: 在 Sentry Dashboard 查看错误
- **功能请求**: 提交 GitHub Issue
- **文档问题**: 更新 `docs/` 目录中的相关文档

## 相关文档

- [技术规范](technical.md)
- [架构设计](architecture.mermaid)
- [项目状态](status.md)
- [变更日志](../changelog.md)

