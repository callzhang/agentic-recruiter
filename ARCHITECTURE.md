# 系统架构概览

> 为 AI 代理和开发者提供的快速参考指南

## 系统概述

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

## 技术栈

- **后端**: FastAPI + Playwright (异步)
- **前端**: FastAPI Web UI (Jinja2 templates + Alpine.js/HTMX)
- **AI**: OpenAI GPT-4 (Assistant API + Threads)
- **数据库**: Zilliz (Milvus 向量数据库)
- **监控**: Sentry (错误追踪)
- **配置**: YAML (config.yaml + secrets.yaml)

## 核心模块

### 1. boss_service.py
FastAPI 服务主入口
- 初始化 Playwright + CDP 连接
- 提供 REST API 端点
- Sentry 集成和全局异常处理

### 2. src/chat_actions.py
聊天页面操作
- `get_chat_list_action()` - 获取对话列表
- `send_message_action()` - 发送消息
- `view_online_resume_action()` - 查看在线简历
- `view_full_resume_action()` - 查看完整简历
- `request_resume_action()` - 请求简历

### 3. src/recommendation_actions.py
推荐牛人操作
- `list_recommended_candidates_action()` - 获取推荐列表
- `greet_recommend_candidate_action()` - 打招呼
- `view_recommend_candidate_resume_action()` - 查看简历

### 4. src/assistant_actions.py
AI 助手功能
- `analyze_candidate()` - 分析候选人匹配度
- `generate_message()` - 生成定制化消息
- `init_chat()` - 创建 OpenAI Thread
- `upsert_candidate()` - 存储到 Zilliz

### 5. src/candidate_store.py
Zilliz 数据存储
- 候选人信息管理
- 向量搜索
- CRUD 操作

### 6. src/config.py
配置管理
- 从 config.yaml + secrets.yaml 加载
- 统一的 settings 对象

## 数据流

### 推荐牛人流程
```
1. UI 触发
   ↓
2. GET /recommend/candidates (获取列表)
   ↓
3. GET /recommend/candidate/{idx}/resume (提取简历)
   ↓
4. POST /assistant/analyze-candidate (AI 分析)
   ↓
5. POST /assistant/generate-chat-message (生成消息)
   ↓
6. POST /recommend/candidate/{idx}/greet (发送打招呼)
   ↓
7. POST /assistant/upsert-candidate (存储到 Zilliz)
```

### 聊天处理流程
```
1. GET /chat/dialogs (获取对话列表)
   ↓
2. 查询 Zilliz (by chat_id)
   ↓
3. GET /chat/resume/online/{chat_id} (提取简历，如需要)
   ↓
4. POST /chat/generate-message (生成回复)
   ↓
5. POST /chat/{chat_id}/send_message (发送消息)
   ↓
6. 更新 Zilliz
```

## API 设计 (v2.2.0)

### 响应格式
- **成功**: 直接返回数据 (`bool`, `dict`, `list`)
- **失败**: HTTP 错误 + `{"error": "描述"}`

### 错误码
- `400` - 参数错误 (ValueError)
- `408` - 操作超时 (PlaywrightTimeoutError)
- `500` - 系统错误 (RuntimeError, Exception)

## 配置结构

```
config/
├── config.yaml       # 非敏感配置 (URLs, 端口)
├── secrets.yaml      # 敏感配置 (API keys, 密码)
└── jobs.yaml         # 岗位配置
```

## 关键设计决策

### 1. CDP 模式
使用外部 Chrome + CDP 连接，避免频繁启动浏览器，支持热重载。

### 2. 统一服务架构
- FastAPI 提供 Web UI 和 REST API
- Web UI 通过模板渲染，业务逻辑在服务端
- REST API 提供程序化访问接口

### 3. OpenAI Thread API
每个候选人一个 Thread，持久化对话历史，保持上下文连续性。

### 4. Zilliz 向量存储
- 存储简历文本 + Embedding
- 快速相似度搜索
- 缓存策略（避免重复 Playwright 操作）

### 5. 异常驱动的错误处理
- 不使用 `{"success": bool}` 包装
- 抛出异常，全局处理器统一返回
- Sentry 自动捕获

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

## 快速查找

- **API 文档**: [docs/api.md](docs/api.md)
- **技术细节**: [docs/architecture.md](docs/architecture.md)
- **自动化工作流**: [docs/workflows.md](docs/workflows.md)
- **变更日志**: [CHANGELOG.md](CHANGELOG.md)

## 版本

**当前版本**: v2.2.0  
**最后更新**: 2024-10-11

---

更多详细信息请参考 [docs/](docs/) 目录。


