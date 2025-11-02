# 自动化工作流

Boss直聘自动化机器人的 4 个独立工作流入口

## 概述

每个工作流可独立执行，处理不同来源的候选人，支持阶段双向转换。

## 工作流入口

### 1. 推荐牛人
**数据源**: Boss直聘推荐页面

**流程**: 获取推荐列表 → 提取简历 → AI 分析 → 决策阶段 → 打招呼 → 存储

**关键API**:
- `GET /recommend/candidates`
- `POST /chat/generate-message` (purpose="ANALYZE_ACTION")
- `POST /recommend/candidate/{idx}/greet`

### 2. 新招呼
**数据源**: 聊天列表"新招呼"标签页

**流程**: 获取新招呼 → 查询存储 → 提取简历 → AI 分析 → 生成回复 → 发送

**关键API**:
- `GET /chat/dialogs?tab=新招呼&status=未读`
- `POST /chat/generate-message`
- `POST /chat/{chat_id}/send_message`

### 3. 沟通中
**数据源**: 聊天列表"沟通中"标签页

**流程**: 获取对话 → 查询缓存 → 请求完整简历 → 重新分析 → 生成回复

**关键API**:
- `GET /chat/dialogs?tab=沟通中&status=未读`
- `POST /chat/resume/request_full`
- `GET /chat/resume/full/{chat_id}`

### 4. 追结果
**数据源**: Zilliz 存储的超时候选人

**流程**: 查询超时候选人 → 筛选阶段 → 生成跟进消息 → 发送

**关键API**:
- Zilliz 直接查询
- `POST /chat/generate-message` (purpose="FOLLOWUP_ACTION")
- `POST /chat/{chat_id}/send_message`

## 候选人阶段

### 阶段定义

- **PASS**: 不匹配，已拒绝
- **GREET**: 表达兴趣，已索要简历
- **SEEK**: 强匹配，寻求联系方式
- **CONTACT**: 已获得联系方式
- **WAITING_LIST**: 待定

### 阶段转换

所有工作流都可以在阶段间双向转换：
```
PASS ↔ GREET ↔ SEEK ↔ CONTACT
        ↕
  WAITING_LIST
```

## AI 消息生成

### Purpose 标志

```python
generate_message(
    thread_id=...,
    assistant_id=...,
    purpose="GREET_ACTION|CHAT_ACTION|ANALYZE_ACTION|FOLLOWUP_ACTION"
)
```

- **GREET_ACTION**: 首次打招呼
- **CHAT_ACTION**: 常规对话回复
- **ANALYZE_ACTION**: 分析候选人
- **FOLLOWUP_ACTION**: 跟进催促

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

