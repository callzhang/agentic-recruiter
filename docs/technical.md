# 技术规格

## 架构概览

## 业务逻辑

### 四个独立自动化工作流入口 (v2.2.0)

从 v2.1 起，业务编排完全转移到 Streamlit 客户端，FastAPI 仅提供 Playwright 操作和 AI 服务。页面 `1_自动化.py` 提供**四个独立的工作流入口**，每个入口可独立执行，用于处理不同来源的候选人。这些工作流会更新候选人的阶段状态（stage），支持双向转换。

**重要**: 这四个工作流是**独立的入口点**，不是顺序执行的流程。每个工作流都可以将候选人的stage在 PASS、GREET、SEEK、CONTACT、WAITING_LIST 之间自由转换。

#### 工作流入口 vs 候选人阶段状态

**工作流入口** (4个独立入口):
- **推荐牛人**: 处理推荐页面的候选人
- **新招呼**: 处理聊天中的新招呼对话
- **沟通中**: 处理聊天中的活跃对话
- **追结果**: 对超时未回复的候选人进行跟进

**候选人阶段状态** (可双向转换):
- **`PASS`**: 不匹配，已拒绝（未达到阈值）, overall_socre <= borderline
- **`GREET`**: 表达兴趣，已索要完整简历, overall_socre >= borderline
- **`SEEK`**: 强匹配，正在寻求联系方式, overall_socre >= threshold_seek
- **`CONTACT`**: 已获得联系方式

**AI决策和分析的Action**
```python
ACTIONS = {
    # generate message actions
    "GREET_ACTION": "请生成首次打招呼消息", # 打招呼
    "ANALYZE_ACTION": "请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。", # 分析候选人
    "ASK_FOR_RESUME_DETAILS_ACTION": "请根据上述沟通历史，生成下一条跟进消息。重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方。不要超过100字，且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。", # 询问简历细节
    "ANSWER_QUESTIONS_ACTION": "请回答候选人提出的问题。", # 回答问题
    "FOLLOWUP_ACTION": "请生成下一条跟进消息，用于吸引候选人回复。", # 跟进消息
    "REQUEST_CONTACT_MESSAGE_ACTION": "请生成下一条跟进消息，用于吸引候选人回复。", # 联系方式
    # browser actions
    "SEND_MESSAGE_BROWSER_ACTION": "请发送消息给候选人。", # 发送消息
    "REQUEST_FULL_RESUME_BROWSER_ACTION": "请请求完整简历。", # 请求完整简历
    "REQUEST_WECHAT_PHONE_BROWSER_ACTION": "请请求候选人微信和电话。", # 请求微信和电话
    # notification actions
    "NOTIFY_HR_ACTION": "请通知HR。", # 通知HR
    # chat actions
    "WAIT_ACTION": "已经完成所有动作，等待候选人回复。"
}
```

#### 工作流1: 推荐牛人 (Recommend Page Entry)
- **数据获取**: `GET /recommend/candidates` 拉取推荐列表 → 对每个 `index` 调用 `/recommend/candidate/{idx}/resume` 获取在线简历
- **创建record**: `POST /assistant/init-chat` 创建数据库对象，`chat_id=NULL`
- **AI分析**: 通过 `POST /assistant/generate-message (..., purpose="analyze")` 分析匹配度
- **Stage决策**: 根据overall_score得分转换stage → `GREET`(>=borderline) / `PASS`(<borderline)
- **PASS**: 如果PASS，则`discard_candidate_action`丢弃候选人
- **打招呼**: 如果GREET, 则使用 `generate_message(..., purpose="greet")` 生成首轮打招呼内容 + `/recommend/candidate/{idx}/greet`，并更新 `stage`为`GREET`
- **关键特点**: 此工作流创建的记录无 `chat_id`，通过 `candidate_id` 标识

#### 工作流2: 新招呼 (New Greetings Entry)
- **列表获取**: `get_chat_list_action(tab="新招呼", status="未读")` 过滤新招呼栏目
- **记录查询**: 通过 `chat_id` 从Zilliz直接获取（如存在则更新，不存在则创建:`init-chat`）
- **简历查看**: 优先使用record的 `online_resume`
    - 如果`online_resume`为空, 则调用 `view_online_resume_action(chat_id)` 抓取在线简历,
    - 同时如果`check_full_resume_available`为True, 则调用 `view_full_resume_action` 获取完整简历
    - 最后调用 `update_candidate_resume` 跟新resume
- **AI分析**: `generate_message(..., purpose="analyze")` 对候选人进行分析
- **Stage决策**: 根据overall_score得分决定stage → `GREET`(>=borderline) / `PASS`(<borderline)
- **PASS**: 如果PASS，则`discard_candidate_action`丢弃候选人
- **打招呼**: 如果GREET, 则`generate_message(..., purpose="chat")` + `send_message_action` + `request_full_resume_action` 完成跟进
- **记录更新**: 更新 `stage`

#### 工作流3: 沟通中 (Active Chats Entry)
- **列表获取**: `get_chat_list_action(tab="沟通中", status="未读")` 拉取沟通中聊天
- **记录查询**: 通过 `chat_id` 从Zilliz直接获取 record, 如果没有找到，则说明对话来自于推荐牛人，则通过`get_candidate_by_resume` 获取候选人record
- **AI决策**: `generate_message(..., purpose="plan")` 决定下一步操作，以下为AI决策分支，直到收到`WAIT_ACTION`停止循环:
    - REQUEST_FULL_RESUME_ACTION: 请求完整简历  
    - ANALYZE_ACTION: 如果有简历或者对话更新，对候选人进行分析
        - **联系方式**: 若获取到微信/电话，调用 `notify_hr_action`（#TODO）并标记 `CONTACT`
    - REQUEST_CONTACT_MESSAGE_ACTION: 请求联系方式`send_message_action`
    - SEND_MESSAGE_BROWSER_ACTION: 发送消息`send_message_action`
    - WAIT_ACTION: 等待候选人回复, 如果收到`WAIT_ACTION`则停止循环


#### 工作流4: 追结果 (Follow-up Entry)
- **筛选条件**: Zilliz查询 `updated_at > 1天 AND stage IN ['GREET', 'SEEK']`
- **消息生成**: 利用 `generate_message(..., purpose="followup")` 生成催促消息
- **消息发送**: 通过 `send_message_action` 发送催促消息
- **状态更新**: 更新 `updated_at`，可能根据回复更新 `stage`


### 数据流设计

**独立工作流架构**:
```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Streamlit   │─────▶│   FastAPI    │─────▶│  Playwright  │
│  (客户端UI)   │ HTTP │  (业务服务)   │ CDP   │ (浏览器控制)  │
└──────────────┘      └──────────────┘      └──────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
            ┌──────────────┐  ┌──────────────┐
            │   OpenAI     │  │   Zilliz     │
            │ (AI分析生成)  │  │ (向量存储)    │
            └──────────────┘  └──────────────┘
```

## 核心模块

### 1. boss_service.py
FastAPI 后端服务，提供 REST API

**主要功能**:
- Playwright 浏览器控制
- 聊天、简历、推荐操作
- 统一异常处理（Sentry 集成）

**关键特性**:
- CDP 模式连接外部 Chrome
- 异步操作，锁保护并发
- HTTP 状态码语义化（400/408/500）

### 2. src/chat_actions.py
聊天相关操作

**函数**:
- `get_chat_list_action()` - 获取对话列表
- `send_message_action()` - 发送消息
- `request_resume_action()` - 请求完整简历
- `view_online_resume_action()` - 查看在线简历
- `view_full_resume_action()` - 查看完整简历
- `accept_resume_action()` - 接受简历
- `discard_candidate_action()` - 丢弃候选人

### 3. src/recommendation_actions.py
推荐牛人操作

**函数**:
- `select_recommend_job_action()` - 选择职位
- `list_recommended_candidates_action()` - 获取推荐列表
- `view_recommend_candidate_resume_action()` - 查看简历
- `greet_recommend_candidate_action()` - 打招呼

### 4. src/assistant_actions.py
AI 助手功能

**函数**:
- `analyze_candidate()` - 分析候选人匹配度
- `generate_message()` - 生成定制化消息
- `upsert_candidate()` - 存储候选人到 Zilliz
- `get_candidate_by_id()` - 查询候选人

**集成**:
- OpenAI Assistant API + Thread
- Zilliz 向量存储
- 自动 embedding 生成

### 5. src/candidate_store.py
Zilliz 数据存储

**Schema**:
```python
{
    "candidate_id": str,      # UUID 主键
    "chat_id": str,           # Boss直聘 chat_id
    "name": str,
    "resume_text": str,       # 在线简历
    "full_resume": str,       # 完整简历
    "resume_vector": [float], # Embedding
    "thread_id": str,         # OpenAI Thread
    "analysis": str,          # 分析结果 JSON
    "stage": str,             # 候选人阶段
    "updated_at": int,        # 时间戳
}
```

### 6. src/config.py
配置管理

**文件**:
- `config.yaml` - 非敏感配置（URLs, 端口等）
- `secrets.yaml` - 敏感配置（API keys, 密码）

**加载**:
```python
from src.config import settings

settings.BASE_URL
settings.OPENAI_API_KEY
settings.get_zilliz_config()
```

## 数据流

### 推荐牛人流程
```
1. 获取推荐列表 → 2. 提取简历 → 3. AI 分析
                                      ↓
                            4. 决策 (PASS/GREET/SEEK)
                                      ↓
5. 存储到 Zilliz ← 6. 打招呼 ← 7. 生成消息
```

### 聊天处理流程
```
1. 获取对话列表 → 2. 查询 Zilliz (by chat_id)
                                      ↓
                            3. 提取简历（如需要）
                                      ↓
                            4. AI 生成回复
                                      ↓
                            5. 发送消息 + 更新存储
```

## API 设计 (v2.2.0)

### 响应格式

**成功** (200):
```json
true                          // Bool 操作
{"text": "...", "name": "..."} // 数据对象
[{...}, {...}]                // 数组
```

**失败** (400/408/500):
```json
{"error": "错误描述"}
```

### 错误处理

| 异常类型 | HTTP 状态 | 场景 |
|---------|----------|------|
| ValueError | 400 | 参数错误、业务逻辑错误 |
| PlaywrightTimeoutError | 408 | 操作超时 |
| RuntimeError | 500 | 系统错误 |
| Exception | 500 | 未预期错误 |

所有异常自动发送到 Sentry。

## 简历提取技术

### 方法优先级
1. **WASM 文本** - 直接解析网站数据（最快）
2. **Canvas Hook** - 拦截绘图 API（准确）
3. **截图 + OCR** - 最后手段（最慢）

### 在线简历
```python
view_online_resume_action(chat_id)
→ 返回 {"text": "...", "name": "...", "chat_id": "..."}
```

### 完整简历（附件）
```python
view_full_resume_action(chat_id)
→ 返回 {"text": "...", "pages": ["page1.png", ...]}
```

## Playwright 最佳实践

### 元素检查
```python
# ✅ 使用 .count()
if await element.count() == 0:
    raise ValueError("元素不存在")

# ❌ 避免 try-except
try:
    await element.click()
except:
    pass
```

### 等待策略
```python
# 等待元素
await page.wait_for_selector(selector, timeout=30000)

# 等待函数
await page.wait_for_function("() => document.readyState === 'complete'")

# 避免固定延迟
# ❌ time.sleep(2)
```

### 并发控制
```python
# 使用锁保护共享资源
async with self._page_lock:
    await page.goto(url)
```

## 性能优化

### 缓存策略
- Streamlit: `@st.cache_data(ttl=600)`
- API: LRU cache for expensive operations
- Zilliz: 向量相似度搜索加速

### 批量操作
```python
# ✅ 并发处理
with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(process_candidate, candidates))

# ❌ 顺序处理
for candidate in candidates:
    process_candidate(candidate)
```

## Streamlit 优化

### 核心原则
1. 使用 `@st.cache_data` 替代会话状态
2. 最小化 API 调用
3. 避免不必要的重新渲染

### 缓存函数
```python
# ✅ 缓存 API 结果
@st.cache_data(ttl=300, show_spinner="加载中...")
def fetch_dialogs(limit: int):
    ok, dialogs = call_api("GET", f"/chat/dialogs?limit={limit}")
    return dialogs
```

### 表单提交
```python
# ✅ 使用表单避免每次输入都重新渲染
with st.form("message_form"):
    message = st.text_area("消息")
    submitted = st.form_submit_button("发送")
    if submitted:
        send_message(message)
```

### 条件渲染
```python
# ✅ 延迟加载
if st.button("查看简历"):
    st.session_state["show_resume"] = True

if st.session_state.get("show_resume"):
    resume = fetch_resume()
    st.text_area("简历", resume)
```

### 常见陷阱
```python
# ❌ 循环中调用 API
for chat_id in chat_ids:
    resume = call_api("POST", "/resume/online", json={"chat_id": chat_id})

# ✅ 批量获取或使用并发
with ThreadPoolExecutor(max_workers=5) as executor:
    resumes = list(executor.map(fetch_resume, chat_ids))
```

## 监控和调试

### Sentry 集成
```yaml
# secrets.yaml
sentry:
  dsn: https://...@sentry.io/...
  environment: development
  release: 2.2.0
```

自动捕获:
- 所有未处理异常
- 请求上下文
- 堆栈跟踪

### 日志
```python
from src.global_logger import logger

logger.info("操作成功")
logger.warning("潜在问题")
logger.error("操作失败", exc_info=True)
```

## 安全考虑

### 敏感数据
- 所有 API keys 存储在 `secrets.yaml`
- Git 忽略 `secrets.yaml`
- 环境变量备用方案

### 会话管理
- 登录状态持久化到 `data/state.json`
- CDP 连接外部 Chrome（无需重复登录）
- 自动恢复登录失效

## 测试

### 运行测试
```bash
pytest test/ -v
```

### 主要测试
- `test_decide_pipeline.py` - AI 决策流程
- `test_resume_capture.py` - 简历提取
- `test_watcher.py` - 文件监控

## 部署

### 生产环境
1. 修改 `config.yaml` 和 `secrets.yaml`
2. 设置 `sentry.environment: production`
3. 启动外部 Chrome (CDP)
4. 启动服务: `python start_service.py`

### Docker (TODO)
```dockerfile
# 待实现
```

## 版本历史

- **v2.2.0** (2024-10-11) - API 简化 + Sentry + 配置重构
- **v2.1.0** (2024-10) - 架构重构 + Thread API
- **v2.0.2** (2024-10) - Streamlit 优化
- **v2.0.0** (2024-09) - 初始版本

---

详细 API 文档: [api/reference.md](api/reference.md)  
架构图: [architecture/system.mermaid](architecture/system.mermaid)  
系统架构: [ARCHITECTURE.md](../ARCHITECTURE.md)
