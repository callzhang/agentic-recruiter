# 系统架构

> 为 AI 代理和开发者提供的快速参考指南

## 概述

Boss直聘自动化机器人 - 基于 Playwright 的智能招聘助手，集成 OpenAI 和 Zilliz 向量数据库。

## 核心架构

```
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Service                        │
│                 (boss_service.py)                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Web UI (Jinja2)  │  REST API  │  Business Logic │  │
│  │  (web/templates)  │  (endpoints)│  (core modules) │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Chat Actions  │  Recommendation  │  Assistant   │  │
│  │  (聊天操作)     │  (推荐牛人)       │  (AI助手)     │  │
│  └──────────────────────────────────────────────────┘  │
└────────┬─────────────────────┬────────────────┬─────────┘
         │                     │                │
         ▼                     ▼                ▼
   ┌──────────┐          ┌─────────┐      ┌─────────┐
   │Playwright│          │ OpenAI  │      │ Zilliz  │
   │(浏览器控制)│          │(AI分析)  │      │(向量库)  │
   └──────────┘          └─────────┘      └─────────┘
         │
         ▼
   ┌──────────┐
   │  Chrome  │
   │  (CDP)   │
   └──────────┘
```

## 架构层次

### 1. 展示层 (FastAPI Web UI)
- **职责**: 用户界面、页面渲染、交互处理
- **技术**: Jinja2 模板、Alpine.js、HTMX
- **特点**: 服务端渲染、动态内容加载

### 2. 服务层 (FastAPI)
- **职责**: REST API、Web UI 路由、Playwright 操作、统一异常处理
- **特点**: 异步处理、CDP 模式、Sentry 集成

### 3. 数据层
- **Playwright**: 浏览器自动化
- **OpenAI**: AI 分析和生成（使用 Conversations API）
- **Zilliz**: 向量存储和检索

## 技术栈

- **后端**: FastAPI + Playwright (异步)
- **前端**: FastAPI Web UI (Jinja2 templates + Alpine.js/HTMX)
- **AI**: OpenAI GPT-5-mini (Responses API)
- **Agent 框架**: LangGraph (双 Agent 架构)
- **数据库**: Zilliz (Milvus 向量数据库) - 内置 OpenAI 嵌入函数
- **通知**: DingTalk Webhook
- **监控**: Sentry (错误追踪)
- **配置**: YAML (config.yaml + secrets.yaml)

## 核心模块

### 1. boss_service.py
FastAPI 服务主入口
- 初始化 Playwright + CDP 连接
- 提供 REST API 端点和 Web UI 路由
- Sentry 集成和全局异常处理

### 2. src/chat_actions.py
聊天页面操作
- `get_chat_list_action()` - 获取对话列表
- `send_message_action()` - 发送消息
- `view_online_resume_action()` - 查看在线简历
- `view_full_resume_action()` - 查看完整简历
- `request_full_resume_action()` - 请求简历

### 3. src/recommendation_actions.py
推荐牛人操作
- `list_recommended_candidates_action()` - 获取推荐列表
- `greet_recommend_candidate_action()` - 打招呼
- `view_recommend_candidate_resume_action()` - 查看简历

### 4. src/assistant_actions.py
AI 助手功能
- `analyze_candidate()` - 分析候选人匹配度
- `generate_message()` - 生成定制化消息
- `init_chat()` - 创建 OpenAI Conversation
- `upsert_candidate()` - 存储到 Zilliz
- `send_dingtalk_notification()` - 发送 DingTalk 通知

### 5. src/candidate_store.py
Zilliz 数据存储
- 候选人信息管理
- 向量搜索
- CRUD 操作
- 字符串查询语法（使用双引号和 AND 运算符）
- 支持 `generated_message` 字段存储 AI 生成的消息
- 按 `updated_at` 排序，返回最新匹配的候选人

### 6. src/jobs_store.py
岗位画像存储（Zilliz）
- 岗位信息版本管理
- 支持岗位版本历史（`job_id_v1`, `job_id_v2`, ...）
- `current` 字段标识当前使用的版本
- 内置 OpenAI 嵌入函数（`text-embedding-3-small`）
- 自动向量生成

### 7. src/config.py
配置管理
- `config.yaml` - 非敏感配置（URLs, 端口等）
- `secrets.yaml` - 敏感配置（API keys, 密码）
- `get_dingtalk_config()` - 获取 DingTalk 配置

## 核心设计

### 统一服务架构

```
FastAPI Web UI (Jinja2 templates)
    ↓ (同一进程)
FastAPI REST API
    ↓ Playwright/OpenAI/Zilliz
外部服务
```

**优势**:
- Web UI 和 API 在同一服务中，简化部署
- 服务端渲染，更好的性能和一致性
- 统一的错误处理和日志

### CDP 模式

使用外部 Chrome + CDP 连接，而非每次 launch：
- 避免频繁启动浏览器
- 支持 uvicorn --reload
- 保持登录状态
- 减少资源消耗

### Chrome 浏览器隔离

Chrome 使用 `--app` 模式启动，创建专用窗口：
- 无地址栏，防止误操作
- 专用窗口，明确标识为自动化用途
- 不影响 Playwright 自动化功能

**启动方式**:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_debug \
  --app=https://www.zhipin.com/web/chat/index
```

### 异常驱动

API 不返回 `{"success": bool}`，直接抛出异常：
- 简化响应格式
- HTTP 状态码语义化
- Sentry 自动捕获

### OpenAI Conversations API

每个候选人一个 Conversation（原 Thread）：
- 持久化对话历史
- 上下文连续性
- 避免重复发送历史
- 使用 `conversation_id` 作为标识符（向后兼容 `thread_id`）

### Zilliz 向量存储

存储简历和分析结果：
- 存储简历文本 + Embedding
- 快速相似度搜索
- 缓存策略（避免重复 Playwright 操作）
- 使用正确的 Milvus 查询语法（双引号字符串，AND 运算符）

## 数据流

### 推荐牛人流程
```
1. UI 触发
   ↓
2. GET /recommend/candidates (获取列表)
   ↓
3. GET /recommend/candidate/{idx}/resume (提取简历)
   ↓
4. POST /assistant/generate-message (AI 分析，purpose="ANALYZE_ACTION")
   ↓
5. POST /assistant/generate-message (生成消息，purpose="CHAT_ACTION")
   ↓
6. POST /recommend/candidate/{idx}/greet (发送打招呼)
   ↓
7. POST /candidates/save-to-cloud (存储到 Zilliz)
```

### 聊天处理流程
```
1. GET /chat/dialogs (获取对话列表)
   ↓
2. 查询 Zilliz (by chat_id 或 name + job_title)
   ↓
3. GET /chat/resume/online/{chat_id} (提取简历，如需要)
   ↓
4. POST /assistant/generate-message (生成回复，purpose="CHAT_ACTION")
   ↓
5. POST /chat/{chat_id}/send_message (发送消息)
   ↓
6. 更新 Zilliz
```

### 读取流向
```
UI 请求 → FastAPI 端点 → 检查 Zilliz 缓存
                              ↓ 未命中
                         Playwright 获取
                              ↓
                         存入 Zilliz
                              ↓
                         返回给 UI
```

### 写入流向
```
UI 操作 → FastAPI 端点 → Playwright 执行
                              ↓
                         OpenAI 处理（如需要）
                              ↓
                         更新 Zilliz
                              ↓
                         返回状态
```

## API 设计 (v2.2.0+)

### 响应格式
- **成功** (200): 直接返回数据（bool/dict/list）
- **失败** (400/408/500): `{"error": "错误描述"}`

### 错误处理

| 异常类型 | HTTP 状态 | 场景 |
|---------|----------|------|
| ValueError | 400 | 参数错误、业务逻辑错误 |
| PlaywrightTimeoutError | 408 | 操作超时 |
| RuntimeError | 500 | 系统错误 |

所有异常自动发送到 Sentry。

### 主要 API 端点

#### AI 助手操作
- `POST /assistant/generate-message` - 生成消息（支持多种 purpose）
- `POST /assistant/init-chat` - 初始化对话（返回 conversation_id）
- `GET /assistant/{thread_id}/messages` - 获取对话消息（thread_id 接受 conversation_id）
- `GET /assistant/{thread_id}/analysis` - 获取分析结果

#### 聊天相关
- `GET /chat/dialogs` - 获取对话列表
- `POST /chat/{chat_id}/send_message` - 发送消息
- `GET /chat/resume/online/{chat_id}` - 查看在线简历
- `POST /chat/resume/request_full` - 请求完整简历

#### 推荐牛人
- `GET /recommend/candidates` - 获取推荐列表
- `GET /recommend/candidate/{index}/resume` - 查看简历
- `POST /recommend/candidate/{index}/greet` - 打招呼

#### 候选人管理
- `GET /store/candidate/{chat_id}` - 获取候选人信息
- `POST /store/candidate/get-by-resume` - 通过简历检查候选人

## 简历提取技术

### 方法优先级
1. **WASM 文本提取** - 直接解析网站数据（最快）
2. **Canvas Hook** - 拦截绘图 API（准确）
3. **截图 + OCR** - 最后手段（最慢）

## Playwright 最佳实践

### 元素检查
```python
# ✅ 使用 .count()
if await element.count() == 0:
    raise ValueError("元素不存在")
```

### 等待策略
```python
# 等待元素
await page.wait_for_selector(selector, timeout=30000)

# 避免固定延迟
# ❌ time.sleep(2)
```

### 页面导航
页面导航会智能检测当前页面，如果已在目标页面（如推荐页面），则跳过导航。

## 性能优化

### 缓存策略
- Zilliz: 向量相似度搜索加速，避免重复 Playwright 操作
- 浏览器: 客户端缓存 API 响应

### 批量操作
```python
# ✅ 并发处理
with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(process_candidate, candidates))
```

## 监控和调试

### Sentry 集成
自动捕获所有未处理异常、请求上下文、堆栈跟踪

### 日志
```python
from src.global_logger import logger
logger.info("操作成功")
logger.error("操作失败", exc_info=True)
```

## 配置管理

### 配置结构
```
config/
├── config.yaml       # 非敏感配置 (URLs, 端口)
├── secrets.yaml      # 敏感配置 (API keys, 密码)
└── jobs.yaml         # 岗位配置
```

### 两层配置
- `config.yaml` - 非敏感配置（URLs, 端口等）
- `secrets.yaml` - 敏感配置（API keys, 密码）

### 统一加载
```python
from src.config import settings
settings.BASE_URL
settings.OPENAI_API_KEY
settings.get_zilliz_config()
```

## 目录结构

```
├── boss_service.py          # FastAPI 服务 + Web UI
├── start_service.py         # 服务启动脚本
├── web/                     # Web UI
│   ├── routes/             # 路由处理
│   ├── templates/          # HTML 模板 (Jinja2)
│   └── static/             # 静态资源 (CSS, JS)
├── src/                     # 核心模块
│   ├── chat_actions.py
│   ├── recommendation_actions.py
│   ├── assistant_actions.py
│   ├── candidate_store.py
│   └── config.py
├── config/                  # 配置文件
├── docs/                    # 文档
└── test/                    # 测试
```

## 关键设计决策

### 1. CDP 模式
使用外部 Chrome + CDP 连接，避免频繁启动浏览器，支持热重载。

### 2. 统一服务架构
- FastAPI 提供 Web UI 和 REST API
- Web UI 通过模板渲染，业务逻辑在服务端
- REST API 提供程序化访问接口

### 3. OpenAI Responses API
每个候选人一个 Conversation，持久化对话历史，保持上下文连续性。使用 `conversation_id` 作为主要标识符，同时保持对 `thread_id` 的向后兼容。支持结构化输出（JSON Schema）用于分析任务。

### 4. Zilliz 向量存储
- 存储简历文本 + Embedding
- 快速相似度搜索
- 缓存策略（避免重复 Playwright 操作）
- 使用正确的 Milvus 查询语法（双引号字符串，AND 运算符）
- **岗位集合**：内置 OpenAI `text-embedding-3-small` 嵌入函数，自动生成向量
- **候选人集合**：支持 `generated_message` 字段，按 `updated_at` 排序

### 5. 异常驱动的错误处理
- 不使用 `{"success": bool}` 包装
- 抛出异常，全局处理器统一返回
- Sentry 自动捕获

## 当前状态

### 核心组件

| 组件 | 状态 | 说明 |
|------|------|------|
| FastAPI 服务 | ✅ | 端口 5001, CDP 模式 |
| Web UI | ✅ | FastAPI Web UI (Jinja2) |
| 浏览器连接 | ✅ | 外部 Chrome CDP |
| AI 助手 | ✅ | OpenAI Responses API + Zilliz |
| Agent 系统 | ✅ | LangGraph 双 Agent 架构 |
| 岗位版本管理 | ✅ | 支持版本历史和切换 |
| DingTalk 通知 | ✅ | 自动通知优质候选人 |
| Sentry 追踪 | ✅ | 错误监控 |

## 快速查找

- **API 文档**: [docs/api.md](api.md)
- **技术细节**: [docs/architecture.md](architecture.md)（本文档）
- **自动化工作流**: [docs/workflows.md](workflows.md)
- **变更日志**: [CHANGELOG.md](../CHANGELOG.md)

## 版本

**当前版本**: v2.2.0+  
**最后更新**: 2024-12

---

更多详细信息请参考 [docs/](.) 目录。
