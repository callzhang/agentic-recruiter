# API 文档

Boss直聘自动化机器人 REST API 文档

## 目录

- [基础信息](#基础信息)
- [端点列表](#端点列表)
- [端点详解](#端点详解)
- [错误处理](#错误处理)
- [测试 API](#测试-api)
- [监控和调试](#监控和调试)
- [性能优化](#性能优化)
- [版本兼容性](#版本兼容性)

## 基础信息

**当前版本**: v2.6.3  
**Base URL**: `http://127.0.0.1:5001`

### 响应格式 (v2.2.0+)

- **成功**: 直接返回数据（dict, list, bool）
- **失败**: HTTP 错误状态码 + `{"error": "错误描述"}`
- **无包装对象**: 不再使用 `{"success": bool, "details": str}` 格式

### HTTP 状态码

| 状态码 | 含义 | 典型场景 |
|--------|------|---------|
| 200 | 成功 | 正常响应 |
| 400 | 请求错误 | 参数验证失败、业务逻辑错误 |
| 408 | 请求超时 | Playwright 操作超时（默认30秒） |
| 500 | 服务器错误 | 未预期的系统错误 |

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
| `/chat/{chat_id}/send_message` | POST | 发送消息 |
| `/chat/greet` | POST | 发送打招呼 |
| `/chat/stats` | GET | 获取聊天统计 |
| `/chat/candidate/discard` | POST | 丢弃候选人 |
| `/chat/contact/request` | POST | 请求联系方式 |

### 简历相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/resume/request_full` | POST | 请求完整简历 |
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

### 候选人管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/candidates/pass` | POST | PASS 候选人（支持推荐模式和聊天模式，v2.6.1+） |
| `/candidates/notify` | POST | 发送 DingTalk 通知 |

### AI 助手管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/assistant/list` | GET | 获取助手列表 |
| `/assistant/create` | POST | 创建助手 |
| `/assistant/update/{assistant_id}` | POST | 更新助手 |
| `/assistant/delete/{assistant_id}` | DELETE | 删除助手 |

### AI 助手操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/assistant/generate-message` | POST | 生成消息 |
| `/assistant/init-chat` | POST | 初始化对话线程 |
| `/assistant/{thread_id}/messages` | GET | 获取线程消息 |
| `/assistant/{thread_id}/analysis` | GET | 获取线程分析 |

### 岗位管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/jobs/api/list` | GET | 获取所有岗位列表（仅当前版本） |
| `/jobs/api/{job_id}` | GET | 获取岗位详情（当前版本） |
| `/jobs/{job_id}/versions` | GET | 获取岗位所有版本 |
| `/jobs/{job_id}/switch-version` | POST | 切换当前使用的版本 |
| `/jobs/{job_id}/delete` | DELETE | 删除指定版本（需保留至少一个版本） |

### 岗位肖像优化（人类反馈 → 生成 → 发布）

> 说明：这些接口用于“评分不准”反馈与岗位肖像滚动优化（本地 FastAPI 版本）。  
> Vercel 的线上版本请参考 `vercel/README.md`（路径以 `/api/jobs/...` 为主）。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/jobs/api/optimizations/count` | GET | 查询某岗位（base_job_id）的反馈数量 |
| `/jobs/api/optimizations/list` | GET | 列表（按 updated_at 倒序） |
| `/jobs/api/optimizations/add` | POST | 添加反馈（评分不准） |
| `/jobs/api/optimizations/update` | POST | 更新反馈（用户二次修改） |
| `/jobs/api/optimizations/generate` | POST | 调用 OpenAI 生成新版岗位肖像（严格 JSON schema） |
| `/jobs/api/optimizations/publish` | POST | 发布新版岗位肖像并关闭所选反馈（status=closed） |

### 候选人管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/candidates/notify` | POST | 发送 DingTalk 通知 |

### Web UI

| 端点 | 方法 | 说明 |
|------|------|------|
| `/web` | GET | Web UI 首页 |
| `/web/stats` | GET | Web UI 统计 |
| `/web/candidates/*` | GET/POST | 候选人管理界面 |
| `/web/automation/*` | GET/POST | 自动化工作流界面 |
| `/web/assistants/*` | GET | 助手管理界面 |
| `/web/jobs/*` | GET | 岗位管理界面 |

## 端点详解

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
POST /chat/{chat_id}/send_message
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
POST /chat/resume/request_full
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
GET /chat/resume/online/{chat_id}
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
GET /chat/resume/full/{chat_id}
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
POST /chat/resume/check_full_resume_available
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
POST /assistant/generate-message
Content-Type: application/json

{
  "thread_id": "thread_123",
  "assistant_id": "asst_123",
  "purpose": "GREET_ACTION",
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

## 错误处理

### 错误响应格式

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

### 常见错误类型

#### 1. ValueError (400)
**原因**: 参数验证失败、业务逻辑错误
**示例**: 
- "未找到指定对话项"
- "消息内容不能为空"
- "无效的职位名称"

**解决方法**:
- 检查请求参数是否正确
- 确认资源（chat_id, job_name 等）是否存在
- 验证输入数据格式

#### 2. TimeoutError (408)
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

#### 3. RuntimeError (500)
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

### 错误处理最佳实践

#### Python (requests)

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
    result = call_api("POST", "/chat/abc123/send_message", json={"message": "Hello"})
    if result is True:
        print("消息发送成功")
except ValueError as e:
    print(f"请求参数错误: {e}")
except TimeoutError as e:
    print(f"操作超时: {e}")
except RuntimeError as e:
    print(f"服务器错误: {e}")
```

#### JavaScript (fetch)

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
    const result = await callApi('POST', '/chat/abc123/send_message', {
        message: 'Hello'
    });
    
    if (result === true) {
        console.log('消息发送成功');
    }
} catch (error) {
    console.error('操作失败:', error.message);
}
```

#### JavaScript (浏览器端)

在 Web UI 中使用 fetch API：

```javascript
async function sendMessage(chatId, message) {
    try {
        const response = await fetch(`/chat/${chatId}/send_message`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: message})
        });
        
        if (response.ok) {
            const result = await response.json();
            if (result === true) {
                alert('消息发送成功');
            }
        } else {
            const error = await response.json();
            alert(`发送失败: ${error.error}`);
        }
    } catch (error) {
        alert(`操作失败: ${error.message}`);
    }
}
```

## 测试 API

### 使用 curl

```bash
# 健康检查
curl http://localhost:5001/status

# 获取对话列表
curl "http://localhost:5001/chat/dialogs?limit=5"

# 发送消息
curl -X POST http://localhost:5001/chat/abc123/send_message \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 查看在线简历
curl "http://127.0.0.1:5001/chat/resume/online/abc123"

# 查看完整简历
curl "http://127.0.0.1:5001/chat/resume/full/abc123"

# 请求完整简历
curl -X POST http://127.0.0.1:5001/chat/resume/request_full \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "abc123"}'

# 获取推荐列表
curl "http://127.0.0.1:5001/recommend/candidates"

# 查看候选人简历
curl "http://127.0.0.1:5001/recommend/candidate/0/resume"

# 发送打招呼
curl -X POST http://127.0.0.1:5001/recommend/candidate/0/greet \
  -H "Content-Type: application/json" \
  -d '{"message": "你好，我对您的简历很感兴趣"}'

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
    "http://localhost:5001/chat/abc123/send_message",
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
   - URL: `{{base_url}}/chat/abc123/send_message`
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

## 性能优化

### 1. 缓存响应

对于不变的数据（如简历），使用客户端缓存：

```python
import functools
import time

@functools.lru_cache(maxsize=100)
def get_resume_cached(chat_id: str):
    response = requests.get(
        f"http://localhost:5001/chat/resume/online/{chat_id}"
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
        f"http://localhost:5001/chat/{chat_id}/send_message",
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
response = requests.get(
    "http://localhost:5001/chat/resume/full/abc123",
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

如果你有使用旧版本 API 的代码，请参考项目变更日志进行迁移。

## 相关文档

- [系统架构](architecture.md) - 架构和实现细节
- [自动化工作流](workflows.md) - 工作流和故障排查
- [变更日志](../CHANGELOG.md) - API 版本历史

## 支持和反馈

- **问题反馈**: 在 Sentry Dashboard 查看错误
- **功能请求**: 提交 GitHub Issue
- **文档问题**: 更新 `docs/` 目录中的相关文档
