# 贡献指南

感谢你对 Boss直聘自动化机器人的贡献！

## 开发环境设置

### 1. 克隆仓库
```bash
git clone <repository-url>
cd bosszhipin_bot
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置文件
复制并编辑配置文件：
```bash
cp config/config.yaml.example config/config.yaml
cp config/secrets.yaml.example config/secrets.yaml
```

### 4. 启动 Chrome (CDP 模式)
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_debug
```

### 5. 启动服务
```bash
python start_service.py
```

## 代码规范

### Python 风格
- 遵循 PEP 8
- 使用类型注解
- 函数和类添加 docstring

### Playwright 最佳实践
- 使用 `.count()` 而非 try-except
- 使用 `wait_for_selector` 而非 `time.sleep()`
- 使用锁保护共享资源

### API 设计 (v2.2.0+)
- 成功返回数据（dict/list/bool）
- 失败抛出异常（ValueError/RuntimeError）
- 不使用 `{"success": bool}` 包装

## 提交代码

### 1. 创建分支
```bash
git checkout -b feature/your-feature-name
```

### 2. 编写代码
- 添加必要的测试
- 更新相关文档
- 确保代码通过 linter

### 3. 提交更改
```bash
git add .
git commit -m "feat: add your feature description"
```

使用语义化提交信息：
- `feat:` - 新功能
- `fix:` - Bug 修复
- `refactor:` - 代码重构
- `docs:` - 文档更新
- `test:` - 测试相关
- `chore:` - 构建/工具相关

### 4. 推送并创建 Pull Request
```bash
git push origin feature/your-feature-name
```

## 测试

### 运行测试
```bash
pytest test/ -v
```

### 添加测试
- 新功能必须包含测试
- 测试文件放在 `test/` 目录
- 使用 pytest fixtures

## 文档

### 更新文档
修改代码时，同步更新：
- API 文档（如修改端点）
- 技术文档（如修改架构）
- README（如修改安装步骤）

### 文档风格
- 简洁明了
- 包含代码示例
- 中文优先（内部项目）

## 代码审查

- 所有代码需经过审查
- 保持 PR 小而聚焦
- 及时回复审查意见

## 注意事项

### 配置文件
- 不要提交 `config/secrets.yaml`
- 不要提交 `data/state.json`
- 敏感信息使用环境变量

### 浏览器操作
- 使用 CDP 模式，不要 launch 新浏览器
- 避免硬编码等待时间
- 使用 Playwright 的自动等待

### 性能
- API 调用使用缓存
- 批量操作使用并发
- 避免循环中调用 API

## 获取帮助

- 📖 查看 [文档](docs/README.md)
- 🏗️ 阅读 [架构文档](ARCHITECTURE.md)
- 🐛 查看 [Sentry Dashboard](https://sentry.io)

## 问题反馈

发现 Bug 或有功能建议？
1. 检查现有 Issues
2. 创建新 Issue，描述清楚
3. 提供复现步骤（如果是 Bug）

---

**快速链接**: [README](README.md) | [ARCHITECTURE](ARCHITECTURE.md) | [API 文档](docs/api/reference.md)


