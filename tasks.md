# Boss直聘机器人开发任务

## 当前状态
项目已完成主要功能开发，处于功能完善和优化阶段。已完成架构重构和API优化。

## 已完成任务 ✅

### 核心架构 (v1.0.0)
- [x] FastAPI后台服务架构
- [x] Playwright浏览器自动化
- [x] 自动登录和状态持久化
- [x] 候选人数据提取
- [x] 消息列表获取
- [x] 搜索参数映射
- [x] 黑名单过滤系统
- [x] 热重载开发支持

### 智能简历处理 (v2.0.0)
- [x] WASM文本提取技术
- [x] Canvas渲染钩子技术
- [x] 多策略图像捕获
- [x] OCR服务集成（本地+云端）
- [x] 简历请求发送功能
- [x] 消息历史记录获取
- [x] 捕获方法参数化（auto/wasm/image）

### AI决策系统 (v2.0.0)
- [x] YAML岗位配置系统
- [x] OpenAI GPT集成
- [x] 智能简历匹配分析
- [x] DingTalk通知集成
- [x] 决策流程自动化
- [x] 批量候选人处理

### 技术优化 (v2.0.0)
- [x] 事件驱动架构重构
- [x] CDP外部浏览器支持
- [x] 客户端API优化
- [x] ResumeResult结构化对象
- [x] 便利方法和批量处理
- [x] 错误处理统一化
- [x] 内存和性能优化

### 文档和测试 (v2.0.0)
- [x] 交互式Notebook演示
- [x] Canvas图像处理指南
- [x] 客户端API迁移指南
- [x] 完整测试覆盖
- [x] 技术文档更新
- [x] 项目状态文档

### 架构重构和API优化 (v2.1.0) - 2025-10-08
- [x] **Streamlit客户端-服务端架构分离**
  - [x] 移除Streamlit页面中的直接服务函数调用
  - [x] 统一使用HTTP API调用后端服务
  - [x] 实现客户端-服务端完全分离
- [x] **API响应简化**
  - [x] 移除所有JSONResponse包装器
  - [x] 直接返回数据对象（字典、列表、布尔值）
  - [x] 统一API响应格式
- [x] **聊天消息生成统一化**
  - [x] 移除`/chat/generate-greeting-message`端点
  - [x] 统一所有消息生成到`generate_chat_message`
  - [x] 更新端点URL：`/assistant/generate-followup` → `/assistant/generate-chat-message`
- [x] **冗余函数清理**
  - [x] 移除调度器中的包装函数：`_check_full_resume`, `_view_full_resume`
  - [x] 简化代码结构，提高可维护性
- [x] **配置系统重构**
  - [x] 移除所有`os.getenv()`调用
  - [x] 基于YAML的配置系统（`jobs.yaml`, `secrets.yaml`）
  - [x] 敏感数据与通用配置分离
- [x] **性能优化**
  - [x] 实现助手缓存（`st.cache_data`）
  - [x] 缓存失效机制（创建/更新/删除后清理）
  - [x] 转换`run_in_threadpool`端点为直接同步调用
- [x] **错误修复**
  - [x] 修复`deprecated`装饰器导入问题
  - [x] 修复`candidate_id`未定义错误
  - [x] 修复Playwright事件循环不匹配问题
  - [x] 修复OpenAI token限制错误（文本截断到4096字符）

### 数据存储优化 (v2.1.0) - 2025-10-08
- [x] **Zilliz集合管理**
  - [x] 创建新集合`CN_candidates_v2`和`CN_candidates_final`
  - [x] 添加新字段：`stage`, `full_resume`, `thread_id`
  - [x] 所有字段设置为nullable，支持灵活数据插入
  - [x] 数据迁移：从`CN_candidates`迁移7条记录到新集合
- [x] **集合管理工具**
  - [x] 创建`zilliz_manager.py`综合管理工具
  - [x] 支持版本检查、集合列表、字段修改、数据迁移
  - [x] 清理临时脚本，组织可重用工具到`scripts/`目录
- [x] **向量数据库优化**
  - [x] 修复`resume_vector`字段缺失问题
  - [x] 实现嵌入生成和存储
  - [x] 支持部分更新（`partial=True`）

### 开发工具和调试 (v2.1.0) - 2025-10-08
- [x] **脚本管理**
  - [x] 清理所有临时脚本
  - [x] 组织可重用工具到`scripts/`目录
  - [x] 创建完整的脚本文档（`scripts/README.md`）
- [x] **调试工具**
  - [x] 保留WASM调试工具（`debug_wasm_export.py`）
  - [x] 保留推荐简历调试工具（`debug_recommend_resume.py`）
  - [x] 保留Chrome管理工具（`manage_chrome.py`）
- [x] **版本兼容性**
  - [x] 确认Zilliz Cloud运行Milvus 2.5（不支持动态字段添加）
  - [x] 实现兼容性解决方案（预创建完整字段集合）

## 当前技术栈

### 后端服务
- **FastAPI**: RESTful API服务
- **Playwright**: 浏览器自动化
- **OpenAI GPT**: AI决策和消息生成
- **Zilliz/Milvus**: 向量数据库存储

### 前端界面
- **Streamlit**: 交互式Web界面
- **客户端-服务端分离**: 通过HTTP API通信

### 数据存储
- **Zilliz Cloud**: 向量数据库（Milvus 2.5兼容）
- **YAML配置**: 岗位配置和敏感数据管理
- **JSON状态**: 浏览器会话持久化

### 开发工具
- **Chrome CDP**: 外部浏览器调试
- **热重载**: 开发环境自动重启
- **调试脚本**: WASM、简历、推荐系统调试

## 下一步计划

### 四个独立自动化工作流入口 (v2.2.0) - 规划中

#### 业务逻辑概述
实现四个独立的招聘自动化工作流入口，每个入口可独立执行，用于处理不同来源的候选人数据。这些工作流会更新候选人的阶段状态（stage），支持双向转换。

**重要**: 这四个工作流是**独立的入口点**，不是顺序执行的流程。每个工作流都可以将候选人的stage在 PASS、GREET、SEEK、CONTACT、WAITING_LIST 之间自由转换。

#### 工作流入口定义 vs 候选人阶段状态

**工作流入口** (4个独立入口，可独立执行):
1. **推荐牛人**: 处理推荐页面的候选人
2. **新招呼**: 处理聊天中的新招呼对话
3. **沟通中**: 处理聊天中的活跃对话
4. **追结果**: 对超时未回复的候选人进行跟进

**候选人阶段状态** (可双向转换):
- `PASS`: 不匹配，已拒绝（未达到阈值）
- `GREET`: 表达兴趣，已索要完整简历
- `SEEK`: 强匹配，正在寻求联系方式
- `CONTACT`: 已获得联系方式
- `WAITING_LIST`: 不确定，需要进一步沟通确认

#### 工作流1: 推荐牛人 (Recommend Page Entry)
- [ ] 获取推荐列表: `GET /recommend/candidates`
- [ ] 遍历候选人: 对每个 `index` 调用 `/recommend/candidate/{idx}/resume`
- [ ] **初始化对话**: `init_chat(candidate_info, job_info)` → 创建thread，返回`thread_id`, `candidate_id`
- [ ] **AI分析**: `generate_message(thread_id, purpose="analyze")` → 分析并更新Zilliz的`stage`和`analysis`
- [ ] 决策逻辑: 根据stage → `GREET` / `SEEK` / `WAITING_LIST` 继续，`PASS` 停止
- [ ] **生成打招呼**: `generate_message(thread_id, purpose="greet")` + `/recommend/candidate/{idx}/greet`
- [ ] Zilliz记录包含: `thread_id`, `stage`, `analysis`, `resume_text`, `chat_id=NULL`

#### 工作流2: 新招呼 (New Greetings Entry)
- [ ] 获取新招呼列表: `get_chat_list_action(tab="新招呼", status="未读")`
- [ ] 查询记录: 通过 `chat_id` 从Zilliz直接获取 → 获得`thread_id`（如存在）
- [ ] 如无记录: 获取简历 + `init_chat(candidate_info, job_info)` + `generate_message(thread_id, purpose="analyze")`
- [ ] **生成回复**: `generate_message(thread_id, purpose="chat", user_message=latest_message)`
- [ ] 更新记录: 添加/更新 `chat_id`，更新 `stage`, `updated_at`

#### 工作流3: 沟通中 (Active Chats Entry)
- [ ] 获取沟通中列表: `get_chat_list_action(tab="沟通中", status="未读")`
- [ ] 查询记录: 通过 `chat_id` 从Zilliz直接获取 → 获得`thread_id`
- [ ] 缓存优先: 优先使用Zilliz已有的 `resume_text` / `full_resume`（避免10s浏览器操作）
- [ ] 简历请求: 如无 `full_resume`，调用 `request_resume_action`
- [ ] 离线简历: 收到后调用 `view_full_resume_action`
- [ ] **重新分析**: `generate_message(thread_id, purpose="analyze", additional_context={full_resume})` → 可能stage倒退（如 `SEEK` → `GREET`）
- [ ] **生成回复**: `generate_message(thread_id, purpose="chat", user_message=latest_message)`
- [ ] 联系方式: 获得微信/电话 → `notify_hr_action` (#TODO) → 更新stage为`CONTACT`
- [ ] 更新Zilliz: `stage`, `full_resume` (缓存), `updated_at`

#### 工作流4: 追结果 (Follow-up Entry)
- [ ] 筛选条件: Zilliz查询 `updated_at > 1天 AND stage IN ['GREET', 'SEEK', 'WAITING_LIST']` → 获得候选人列表及其`thread_id`
- [ ] **生成催促消息**: `generate_message(thread_id, purpose="followup")`
- [ ] 发送消息: `send_message_action`
- [ ] 更新Zilliz: `updated_at`，可能根据回复更新 `stage`

#### 待实现功能 (TODOs)
- [ ] `mark_candidate_stage_action(chat_id, stage)` - 支持所有stage包括 `WAITING_LIST`
- [ ] `notify_hr_action(candidate_info)` - HR通知功能 (部分已存在)
- [ ] `skip_recommend_candidate_action(index)` - 推荐候选人跳过标记
- [ ] 实现 `purpose="followup"` 提示词变体
- [ ] 增强 `pages/1_自动化.py` 客户端编排UI - 四个独立按钮/面板
- [ ] Zilliz schema添加 `WAITING_LIST` 作为有效stage值

#### Thread API架构 (v2.2.0核心设计)

**Thread作为对话记忆**:
- Thread存储完整上下文: 岗位描述、简历、分析结果、所有聊天消息
- 所有消息生成只需 `thread_id` + `purpose`，无需重建上下文
- OpenAI Thread API自动维护完整对话历史

**Zilliz角色** (阶段追踪 + 路由 + 缓存):
1. **阶段追踪**: 记录候选人当前stage (PASS/GREET/SEEK/CONTACT/WAITING_LIST)
2. **路由**: 链接 `chat_id` ↔ `thread_id` 用于消息生成
3. **简历缓存**: 保存 `resume_text`/`full_resume` 避免10s浏览器操作
4. **语义搜索**: 通过 `resume_vector` 查找候选人（当chat_id未知时）
5. **审计追踪**: 保存 `analysis` JSON用于历史审查

**函数拆分**:
- `init_chat(candidate_info, job_info)` → 创建thread + Zilliz记录，返回thread_id
- `generate_message(thread_id, purpose, user_message, additional_context)` → 使用已有thread生成消息

#### 数据存储要求
- Zilliz集合字段: `candidate_id`, `chat_id` (nullable), `thread_id`, `stage`, `resume_vector`, `resume_text`, `full_resume`, `analysis`, `updated_at`, `name`, `job_applied`, `last_message`, `metadata`
- `chat_id` 字段保持nullable (推荐工作流创建记录时为NULL，聊天工作流直接通过chat_id查询并更新)
- Stage字段支持值: `PASS`, `GREET`, `SEEK`, `CONTACT`, `WAITING_LIST`
- 使用 `chat_id` 作为主要查询键（当可用时），无需语义搜索
- Stage转换支持双向：任何stage都可以转换为任何其他stage
- `resume_text`/`full_resume` 保留用于快速检索（避免浏览器重新抓取）
- `analysis` JSON保留用于历史审计

### 短期优化 (v2.2.1)
- [ ] 实现更智能的候选人评分算法
- [ ] 添加批量操作支持
- [ ] 优化简历提取成功率
- [ ] 增强错误处理和重试机制

### 中期扩展 (v3.0.0)
- [ ] 多平台支持（其他招聘网站）
- [ ] 高级分析仪表板
- [ ] 机器学习模型集成
- [ ] 自动化工作流编排

### 长期规划 (v4.0.0)
- [ ] 微服务架构重构
- [ ] 容器化部署
- [ ] 分布式处理
- [ ] 企业级功能

*最后更新: 2025-01-27*
*项目状态: v2.1.0架构重构完成，v2.2.0四个独立自动化工作流入口规划中*