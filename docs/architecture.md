# 系统架构

## 概述

Boss直聘自动化机器人 - 基于 Playwright 的智能招聘助手，集成 OpenAI 和 Zilliz 向量数据库。

## 架构层次

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

### 1. 展示层 (FastAPI Web UI)
- **职责**: 用户界面、页面渲染、交互处理
- **技术**: Jinja2 模板、Alpine.js、HTMX
- **特点**: 服务端渲染、动态内容加载

### 2. 服务层 (FastAPI)
- **职责**: REST API、Web UI 路由、Playwright 操作、统一异常处理
- **特点**: 异步处理、CDP 模式、Sentry 集成

### 3. 数据层
- **Playwright**: 浏览器自动化
- **OpenAI**: AI 分析和生成
- **Zilliz**: 向量存储和检索

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
- `init_chat()` - 创建 OpenAI Thread
- `upsert_candidate()` - 存储到 Zilliz

### 5. src/candidate_store.py
Zilliz 数据存储
- 候选人信息管理
- 向量搜索
- CRUD 操作

### 6. src/config.py
配置管理
- `config.yaml` - 非敏感配置（URLs, 端口等）
- `secrets.yaml` - 敏感配置（API keys, 密码）

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

### OpenAI Thread

每个候选人一个 Thread：
- 持久化对话历史
- 上下文连续性
- 避免重复发送历史

### Zilliz 缓存

存储简历和分析结果：
- 避免重复 Playwright 操作
- 快速检索候选人
- 向量相似度搜索

## 数据流

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

## API 设计 (v2.2.0)

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

## 当前状态

### 核心组件

| 组件 | 状态 | 说明 |
|------|------|------|
| FastAPI 服务 | ✅ | 端口 5001, CDP 模式 |
| Web UI | ✅ | FastAPI Web UI (Jinja2) |
| 浏览器连接 | ✅ | 外部 Chrome CDP |
| AI 助手 | ✅ | OpenAI + Zilliz |
| Sentry 追踪 | ✅ | 错误监控 |

---

相关文档: [API 文档](api.md) | [工作流](workflows.md) | [Agent 框架](agent_framework.md)

