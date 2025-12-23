# 自动化工作流

Boss直聘自动化机器人的工作流系统

## 概述

系统提供两种工作流模式：

1. **半自动化工作流**（候选人管理页面）：HR 手动触发，AI 自动执行分析、评分、消息生成
2. **全自动化工作流**（Agent 智能体系统）：基于 LangGraph 的完全自主 Agent 系统

每个工作流可独立执行，处理不同来源的候选人，支持阶段双向转换。

---

## 岗位肖像滚动优化闭环（强烈建议纳入日常）

目标：把“评分不准/问法不对/误判原因”等**人类反馈**沉淀成可复用的岗位肖像，提升线上初筛稳定性。

### 线上（Vercel）闭环：评分不准 → 生成 → Diff → 发布

1) 在候选人详情页（只读页面也可）：点击 **“评分不准”**，填写：
   - 至少一个目标分数（overall/skill/background/startup_fit 任一）
   - 原因与建议（>= 5 个字）
2) 打开岗位页：`/jobs`，在岗位标签旁的绿色 **“优化肖像”** 入口进入清单：`/jobs/optimize?job_id=<base_job_id>`
3) 勾选若干条反馈 → 进入生成页 `/jobs/optimize/generate`（进度条 + 字段级 diff + 可编辑）
4) 确认提交（发布）后：
   - 岗位生成新版本（仍为同一个 base_job_id）
   - 本次选中的反馈标记为 `closed`，下次默认不再出现

> 注意：`candidate_filters`（Boss 侧筛选项）与 `notification`（钉钉）会继承上一版，不让 AI 修改；keywords 也会兜底保留，避免被清空。

### 离线回放（脚本）闭环：下载样本 → 回放验证 → 再发布

当你希望在发布前“可复盘验证”（尤其是边界样本/典型误判），建议使用脚本回放：

1) 下载候选人样本：`scripts/prompt_optmization/download_data_for_prompt_optimization.py`
2) 选择 2-5 个“有问题”的候选人，回放生成：`scripts/prompt_optmization/generate_optimized.py`
3) 根据回放结果迭代本批次的 `prompt_optimized.py` / `job_portrait_optimized.json`
4) 满意后用发布脚本或 Vercel API 发布

详见：`scripts/prompt_optmization/README.md`

## 工作流入口(Mode)

### 1. 推荐牛人(recommend)
**数据源**: Boss直聘推荐页面

**流程**: 获取推荐列表 → 提取简历 → AI 分析 → 决策阶段 → 打招呼 → 存储

**关键API**:
- `GET /recommend/candidates` 获取候选人列表
- `POST /assistant/generate-message` (purpose="ANALYZE_ACTION")
- `POST /recommend/candidate/{idx}/greet`

### 2. 新招呼(Greet)
**数据源**: 聊天列表"新招呼"标签页

**流程**: 获取新招呼 → 查询存储 → 提取简历 → AI 分析 → 生成回复 → 发送

**关键API**:
- `GET /chat/dialogs?tab=新招呼&status=未读`
- `POST /assistant/generate-message` (purpose="ANALYZE_ACTION")
- `POST /chat/{chat_id}/send_message`

### 3. 沟通中(Chat)
**数据源**: 聊天列表"沟通中"标签页

**流程**: 获取对话 → 查询缓存 → 请求完整简历 → 重新分析 → 生成回复

**关键API**:
- `GET /chat/dialogs?tab=沟通中&status=未读`
- `POST /chat/resume/request_full`
- `GET /chat/resume/full/{chat_id}`

### 4. 牛人已读未回(Followup)
**数据源**: Zilliz 存储的超时候选人

**流程**: 查询超时候选人 → 筛选阶段 → 生成跟进消息 → 发送

**关键API**:
- Zilliz 直接查询
- `POST /assistant/generate-message` (purpose="FOLLOWUP_ACTION")
- `POST /chat/{chat_id}/send_message`

## 候选人阶段

### 阶段定义

- **PASS**: 不匹配，已拒绝
- **CHAT**: 需要进一步沟通确认（在线甄别）
- **SEEK**: 强匹配（或接近强匹配），强推进（但不约面试）
- **CONTACT**: 联系阶段（待拿联系方式/已拿联系方式）

> 说明：历史数据里可能出现 `GREET`（推荐页“已打招呼”语义），但统一的阶段流以 `PASS/CHAT/SEEK/CONTACT` 为准（见 `src/candidate_stages.py`）。

### 阶段转换

所有工作流都可以在阶段间双向转换：
```
PASS ↔ CHAT ↔ SEEK ↔ CONTACT
```

## AI 消息生成

### Purpose 标志

```python
generate_message(
    conversation_id=...,
    input_message=...,
    purpose="analyze|chat|greet|followup|contact"
)
```

**支持的 Purpose**:
- **analyze** → `ANALYZE_ACTION`: 分析候选人（返回结构化评分）
- **chat** → `ASK_FOR_RESUME_DETAILS_ACTION`: 常规对话回复，挖掘简历细节
- **greet** → `GREET_ACTION`: 首次打招呼
- **followup** → `FOLLOWUP_ACTION`: 跟进催促（默认不追问，以提高回复意愿或直接 WAIT）
- **contact** → `CONTACT_ACTION`: 请求联系方式

**注意**: 使用 `conversation_id` 作为主要标识符（替代 `thread_id`），通过 `init_chat()` 创建。

### 合规与边界（必须在 prompt 中约束）

- **AI 不代替 HR 约面试**：所有面试时间/方式/地点由 HR 决定；AI 不要“确认时间/安排面试/指定地点”。
- **不讨论薪资/预付等商务条款**：涉及薪资/合同/付款等，统一引导 HR 对接。
- **PASS 不发消息**：候选人判定 PASS 时不应发送任何文本（避免无意义打扰）。

## 故障排查

### Chrome 连接失败

**症状**: `Error: connect ECONNREFUSED 127.0.0.1:9222`

**解决方案**:
```bash
# 检查 Chrome 是否启动
curl http://127.0.0.1:9222/json/version

# 重启 Chrome (macOS)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_debug \
  --app=https://www.zhipin.com/web/chat/index
```

### 登录失效

**症状**: `ValueError: 未检测到登录状态`

**解决方案**:
```bash
rm data/state.json
# 手动登录后重启服务
python start_service.py
```

### API 错误

**端口冲突**:
```bash
lsof -i :5001
kill -9 <PID>
```

**请求超时 (408)**:
- 检查网络连接
- 等待 Boss直聘网站恢复
- 重试请求

**参数错误 (400)**:
- 检查 chat_id 是否正确
- 确认候选人仍在列表中

### Playwright 元素未找到

**解决方案**:
1. 检查页面是否加载完成
2. 等待元素出现
3. 检查选择器是否正确

### OpenAI 错误

**Token 超限**: 已自动截断（4096 字符）

**API Key 错误**: 检查 `config/secrets.yaml`

### Zilliz 错误

**Collection 不存在**:
```bash
python scripts/zilliz_manager.py create
```

**连接失败**: 检查 `config/secrets.yaml` 配置

### 性能问题

**内存占用高**: 重启服务
```bash
pkill -f "python start_service.py"
python start_service.py
```

**响应慢**: 
- 使用缓存（Zilliz）
- 批量操作
- 并发处理

### 日志和监控

**查看日志**:
```bash
tail -f logs/boss_service.log
grep ERROR logs/boss_service.log
```

**Sentry Dashboard**: 访问 [Sentry Dashboard](https://sentry.io) 查看错误详情

---

相关文档: [系统架构](architecture.md) | [API 文档](api.md)
