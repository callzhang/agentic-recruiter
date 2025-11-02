# Boss直聘自动化机器人

基于 Playwright 的 Boss直聘自动化系统，支持候选人管理、简历提取、智能对话等功能。

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置文件
编辑 `config/config.yaml` 和 `config/secrets.yaml`

### 3. 启动 Chrome (CDP模式)
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug

# Windows
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\temp\chrome_debug
```

### 4. 启动服务
```bash
python start_service.py
```

服务地址: `http://127.0.0.1:5001`

### 5. 访问 Web UI
打开浏览器访问: `http://127.0.0.1:5001/web`

## 核心功能

### 聊天管理
- 获取对话列表、发送消息、请求简历
- 自动打招呼、筛选候选人

### 简历提取
- 在线简历、完整简历（附件）
- WASM/Canvas/截图多种方式

### AI 助手
- OpenAI 集成，自动分析候选人
- 生成定制化消息
- Zilliz 向量存储

### 推荐牛人
- 浏览推荐候选人
- 批量打招呼

## API 文档

详见 [docs/api.md](docs/api.md)

### 示例

```python
import requests

# 获取对话列表
response = requests.get('http://127.0.0.1:5001/chat/dialogs?limit=10')
dialogs = response.json()

# 发送消息
response = requests.post(
    'http://127.0.0.1:5001/chat/abc123/send',
    json={'message': '你好'}
)

# 查看在线简历
response = requests.get('http://127.0.0.1:5001/chat/resume/online/abc123')
resume = response.json()
```

## 项目结构

```
├── boss_service.py         # FastAPI 后端服务 + Web UI
├── start_service.py        # 服务启动脚本
├── web/                    # Web UI (FastAPI templates)
│   ├── routes/            # 路由处理
│   ├── templates/         # HTML 模板
│   └── static/            # 静态资源
├── config/                 # 配置文件
│   ├── config.yaml        # 非敏感配置
│   └── secrets.yaml       # 敏感配置 (API keys)
├── src/                    # 核心模块
│   ├── chat_actions.py    # 聊天操作
│   ├── recommendation_actions.py  # 推荐牛人操作
│   ├── assistant_actions.py       # AI 助手
│   ├── candidate_store.py         # Zilliz 存储
│   └── config.py          # 配置加载
├── docs/                   # 文档
└── test/                   # 测试

```

## 技术栈

- **后端**: FastAPI + Playwright (CDP 模式)
- **前端**: FastAPI Web UI (Jinja2 templates + Alpine.js/HTMX)
- **AI**: OpenAI GPT-4
- **向量数据库**: Zilliz (Milvus)
- **错误追踪**: Sentry

## 配置说明

### config.yaml (非敏感)
```yaml
boss_zhipin:
  chat_url: https://www.zhipin.com/web/chat/index
  
service:
  host: 127.0.0.1
  port: 5001

browser:
  cdp_url: http://127.0.0.1:9222
```

### secrets.yaml (敏感)
```yaml
openai:
  api_key: sk-...

zilliz:
  endpoint: https://...
  user: ...
  password: ...

sentry:
  dsn: https://...
```

## 文档

- [系统架构](ARCHITECTURE.md) - 架构概览
- [API 文档](docs/api.md) - REST API 完整参考
- [系统架构详情](docs/architecture.md) - 架构和技术细节
- [自动化工作流](docs/workflows.md) - 工作流和故障排查
- [变更日志](CHANGELOG.md) - 版本历史
- [贡献指南](CONTRIBUTING.md) - 如何贡献

## 故障排查

### Chrome 连接失败
```bash
# 检查 Chrome 是否启动
curl http://127.0.0.1:9222/json/version

# 重启 Chrome 并清除缓存
rm -rf /tmp/chrome_debug
```

### 登录失效
删除 `data/state.json` 并重新登录

### 端口冲突
修改 `config/config.yaml` 中的 `service.port`

## 开发

### 运行测试
```bash
pytest test/
```

### 代码风格
```bash
black .
ruff check .
```

## License

MIT License

## 支持

- GitHub Issues
- Sentry Dashboard (错误追踪)

---

更新时间: 2024-10-11
版本: v2.2.0
