# 故障排查

常见问题和解决方案

## Chrome 相关

### Chrome 连接失败

**症状**: `Error: connect ECONNREFUSED 127.0.0.1:9222`

**原因**: Chrome 未启动或 CDP 端口未开放

**解决方案**:
```bash
# 检查 Chrome 是否启动
curl http://127.0.0.1:9222/json/version

# 重启 Chrome
pkill -f "Chrome.*remote-debugging-port"

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_debug

# Linux
google-chrome --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_debug
```

### Chrome 卡死

**症状**: 浏览器无响应，API 调用超时

**解决方案**:
```bash
# 完全清理并重启
pkill -9 Chrome
rm -rf /tmp/chrome_debug
# 重新启动 Chrome 和服务
```

## 登录相关

### 登录失效

**症状**: `ValueError: 未检测到登录状态`

**解决方案**:
```bash
# 删除登录状态文件
rm data/state.json

# 手动登录 Boss直聘
# 然后重启服务
python start_service.py
```

### 滑块验证

**症状**: 登录时出现滑块验证

**解决方案**:
- 手动在 Chrome 中完成滑块验证
- 服务会自动保存登录状态
- 避免高频操作触发验证

## API 相关

### 端口冲突

**症状**: `OSError: [Errno 48] Address already in use`

**解决方案**:
```bash
# 查找占用端口的进程
lsof -i :5001

# 杀死进程
kill -9 <PID>

# 或修改配置
# config/config.yaml
service:
  port: 5002
```

### 请求超时 (408)

**症状**: `PlaywrightTimeoutError: Timeout 30000ms exceeded`

**原因**: 网络慢或页面加载慢

**解决方案**:
- 检查网络连接
- 等待 Boss直聘网站恢复
- 增加超时时间（代码级别）
- 重试请求

### 参数错误 (400)

**症状**: `ValueError: 未找到指定对话项`

**原因**: chat_id 无效或候选人不存在

**解决方案**:
- 检查 chat_id 是否正确
- 确认候选人仍在列表中
- 刷新对话列表

## Playwright 相关

### 元素未找到

**症状**: `ValueError: 未找到元素`

**原因**: 页面结构变化或元素未加载

**解决方案**:
1. 检查页面是否加载完成
2. 等待元素出现
3. 检查选择器是否正确
4. Boss直聘页面可能更新了

### 事件循环错误

**症状**: `ValueError: The future belongs to a different loop`

**原因**: 在不同的 asyncio 事件循环中使用 Playwright 对象

**解决方案**:
- 使用 `await` 直接调用，不要用 `asyncio.run()`
- 重新创建 locator
- 使用 `page.evaluate()` 代替

## OpenAI 相关

### Token 超限

**症状**: `BadRequestError: maximum context length is 8192 tokens`

**原因**: 简历文本过长

**解决方案**:
- 自动截断已实现（4096 字符）
- 如仍超限，手动缩短简历文本

### API Key 错误

**症状**: `AuthenticationError: Incorrect API key`

**解决方案**:
```yaml
# 检查 config/secrets.yaml
openai:
  api_key: sk-proj-...  # 确保正确
```

### Rate Limit

**症状**: `RateLimitError: Rate limit reached`

**解决方案**:
- 等待一分钟后重试
- 减少并发请求
- 升级 OpenAI 账户

## Zilliz 相关

### Collection 不存在

**症状**: `MilvusException: collection not found`

**解决方案**:
```bash
# 创建 collection
python scripts/zilliz_manager.py create
```

### 字段长度超限

**症状**: `MilvusException: length exceeds max length`

**原因**: 简历文本过长

**解决方案**:
- 已增加 `resume_text` max_length 到 25000
- 如仍超限，手动截断

### 连接失败

**症状**: `MilvusException: failed to connect`

**解决方案**:
```yaml
# 检查 config/secrets.yaml
zilliz:
  endpoint: https://...
  user: db_...
  password: ...  # 确保正确
```

## Streamlit 相关

### 页面崩溃

**症状**: Streamlit 页面白屏或报错

**解决方案**:
```bash
# 清除缓存
streamlit cache clear

# 重启应用
pkill -f streamlit
streamlit run boss_app.py
```

### 缓存过期

**症状**: 数据不更新

**解决方案**:
- 点击"刷新"按钮
- 或清除缓存: `streamlit cache clear`

## 性能相关

### 内存占用高

**症状**: 服务占用内存持续增长

**解决方案**:
```bash
# 重启服务
pkill -f "python start_service.py"
python start_service.py
```

### 响应慢

**症状**: API 调用很慢

**原因**: 
- Playwright 操作慢
- 网络慢
- OpenAI API 慢

**解决方案**:
- 使用缓存（Zilliz）
- 批量操作
- 并发处理

## 日志相关

### 查看日志

```bash
# 服务日志
tail -f logs/boss_service.log

# 搜索错误
grep ERROR logs/boss_service.log

# 搜索特定 API
grep "/chat/.*send" logs/boss_service.log
```

### Sentry Dashboard

访问 [Sentry Dashboard](https://sentry.io) 查看：
- 错误列表
- 堆栈跟踪
- 请求上下文
- 错误趋势

## 获取帮助

### 检查文档
- [README](../../README.md)
- [ARCHITECTURE](../../ARCHITECTURE.md)
- [技术文档](../technical.md)
- [API 文档](../api/reference.md)

### 调试模式
```bash
# 启用详细日志
export LOG_LEVEL=DEBUG
python start_service.py
```

### 创建 Issue
如果问题仍未解决：
1. 收集错误信息
2. 记录复现步骤
3. 创建 Issue

---

**快速链接**: [README](../../README.md) | [CONTRIBUTING](../../CONTRIBUTING.md)

