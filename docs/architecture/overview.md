# 架构概览

系统架构设计和组件说明

## 整体架构

参见 [system.mermaid](system.mermaid) 获取完整的架构图。

## 三层架构

### 1. 展示层 (Streamlit)
- **文件**: `pages/*.py`, `boss_app.py`, `streamlit_shared.py`
- **职责**: 用户界面、业务编排、工作流执行
- **特点**: 多页面应用、缓存优化、实时反馈

### 2. 服务层 (FastAPI)
- **文件**: `boss_service.py`
- **职责**: REST API、Playwright 操作、统一异常处理
- **特点**: 异步处理、CDP 模式、Sentry 集成

### 3. 数据层
- **Playwright**: 浏览器自动化
- **OpenAI**: AI 分析和生成
- **Zilliz**: 向量存储和检索

## 核心设计

### 客户端-服务器分离

```
Streamlit (业务编排)
    ↓ HTTP REST
FastAPI (原子操作)
    ↓ Playwright/OpenAI/Zilliz
外部服务
```

**优势**:
- 业务逻辑在 Streamlit，易于修改
- FastAPI 提供稳定的 API 接口
- 服务可独立扩展

### CDP 模式

使用外部 Chrome + CDP 连接，而非每次 launch：

**优势**:
- 避免频繁启动浏览器
- 支持 uvicorn --reload
- 减少资源消耗
- 保持登录状态

### 异常驱动

API 不返回 `{"success": bool}`，直接抛出异常：

**优势**:
- 简化响应格式
- HTTP 状态码语义化
- Sentry 自动捕获
- 更符合 RESTful 规范

### OpenAI Thread

每个候选人一个 Thread：

**优势**:
- 持久化对话历史
- 上下文连续性
- 避免重复发送历史

### Zilliz 缓存

存储简历和分析结果：

**优势**:
- 避免重复 Playwright 操作
- 快速检索候选人
- 向量相似度搜索

## 数据流向

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

## 并发控制

### Playwright 锁

```python
async with self._page_lock:
    await page.goto(url)
```

**原因**: Playwright page 对象非线程安全

### Zilliz 连接池

多个请求共享 Zilliz 连接：

**优势**:
- 减少连接开销
- 提升并发性能

## 配置管理

### 两层配置

```
config.yaml (非敏感)
  ├── URLs
  ├── 端口
  └── 模型参数

secrets.yaml (敏感)
  ├── API keys
  ├── 密码
  └── Tokens
```

### 统一加载

```python
from src.config import settings

settings.BASE_URL
settings.OPENAI_API_KEY
```

## 错误处理

### 异常层次

```
ValueError        → 400 (参数错误)
PlaywrightTimeoutError → 408 (超时)
RuntimeError      → 500 (系统错误)
Exception         → 500 (未知错误)
```

### Sentry 集成

所有异常自动发送到 Sentry：
- 完整堆栈跟踪
- 请求上下文
- 异常类型标签

## 性能优化

### Streamlit 缓存

```python
@st.cache_data(ttl=600)
def fetch_dialogs(limit: int):
    ...
```

### API 批量操作

```python
with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(process, items))
```

### Zilliz 索引

向量索引加速检索：
- HNSW 索引
- 1536 维 Embedding
- 余弦相似度

## 扩展性

### 水平扩展

- FastAPI 服务可多实例部署
- 共享 Zilliz 数据库
- 负载均衡

### 垂直扩展

- 增加 Playwright 并发数
- 提升 OpenAI API quota
- 扩展 Zilliz 集群

## 相关文档

- [系统架构图](system.mermaid)
- [技术规范](../technical.md)
- [API 文档](../api/reference.md)

---

**快速链接**: [README](../../README.md) | [ARCHITECTURE](../../ARCHITECTURE.md)

