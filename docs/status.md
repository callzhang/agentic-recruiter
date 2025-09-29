# Boss直聘机器人项目状态

## 项目概述
基于Playwright的Boss直聘自动化机器人，提供后台服务和API接口，支持候选人管理、消息处理、搜索等功能。

## 当前状态 ✅ 运行中
- **服务状态**: 正常运行 (端口5001, CDP模式)
- **登录状态**: 已登录
- **浏览器模式**: 外部Chrome + CDP连接
- **最后更新**: 2025-09-23 13:30

## 已完成功能

### 核心服务
- ✅ FastAPI后台服务 (`boss_service.py`)
- ✅ 自动启动脚本 (`start_service.py`)
- ✅ 教程文档 (`tutorial.ipynb`)
- ✅ 热重载支持 (Uvicorn --reload)
- ✅ 端口冲突自动处理

### 登录管理
- ✅ 自动登录检测
- ✅ 登录状态持久化 (storage_state)
- ✅ 滑块验证处理
- ✅ 10分钟登录等待机制
- ✅ 页面自动恢复机制

### 数据提取
- ✅ 候选人列表获取 (2个候选人)
- ✅ 消息列表获取
- ✅ 页面选择器优化 (14个元素匹配)
- ✅ 黑名单过滤系统
- ✅ 数据自动保存 (JSONL格式)

### API接口
- ✅ `/status` - 服务状态
- ✅ `/candidates` - 候选人列表
- ✅ `/messages` - 消息列表
- ✅ `/messages/history` - 消息历史记录
- ✅ `/search` - 搜索参数预览
- ✅ `/notifications` - 操作日志
- ✅ `/login` - 登录操作
- ✅ `/resume/request` - 简历请求
- ✅ `/resume/online` - 在线简历查看
- ✅ `/decide/pipeline` - AI决策流程
- ✅ `/decide/notify` - DingTalk通知

### 配置管理
- ✅ 参数映射系统 (`src/mappings.py`)
- ✅ 简化选择器 (内联单选择器)
- ✅ 黑名单管理 (`src/blacklist.py`)
- ✅ 环境变量配置
- ✅ 简历捕获配置 (`src/resume_capture.py`)
- ✅ OCR服务配置 (`src/ocr_service.py`)
- ✅ 岗位要求配置 (`config/jobs.yaml`)

### 智能简历处理
- ✅ WASM文本提取 - 直接解析网站数据结构
- ✅ Canvas渲染钩子 - 拦截绘图API重建文本
- ✅ 多种图像捕获 - toDataURL、分页截图、元素截图
- ✅ OCR文本识别 - 本地pytesseract + OpenAI视觉API
- ✅ 智能回退机制 - 自动选择最佳方法
- ✅ 多捕获模式 - auto/wasm/image模式选择

### AI决策系统
- ✅ YAML岗位配置 - 结构化要求定义
- ✅ OpenAI集成 - GPT辅助决策分析
- ✅ DingTalk通知 - 实时HR通知
- ✅ 批量处理 - 并发候选人处理
- ✅ 决策日志 - 完整的决策审计

### 客户端优化
- ✅ ResumeResult对象 - 类型安全的结构化响应
- ✅ 便利方法 - get_resume_text, get_resume_image
- ✅ 批量API - batch_get_resumes
- ✅ 错误处理 - 统一的异常管理
- ✅ 上下文管理器 - 资源自动清理

## 技术优化

### 稳定性改进
- ✅ 页面超时处理 (60秒)
- ✅ 线程安全 (Playwright + FastAPI)
- ✅ 错误恢复机制
- ✅ 资源清理 (优雅关闭)
- ✅ CDP外部浏览器 - 进程隔离，热重载友好
- ✅ 事件驱动架构 - 避免sleep，提升响应速度

### 性能优化
- ✅ 选择器缓存
- ✅ 异步处理
- ✅ 批量操作支持
- ✅ 内存管理
- ✅ 响应监听器 - 自动获取JSON数据
- ✅ TTL缓存 - 减少重复请求
- ✅ 并发简历处理 - 多线程批量获取

## 测试结果

### API测试
```bash
# 服务状态
curl "http://127.0.0.1:5001/status"
# 返回: {"status": "running", "logged_in": true}

# 候选人列表
curl "http://127.0.0.1:5001/candidates?limit=5"
# 返回: 2个候选人数据

# 搜索功能
curl "http://127.0.0.1:5001/search?city=北京&job=Python开发"
# 返回: 参数映射 {"city": "101010100", "jobType": "1901"}
```

### 数据输出
- 候选人数据保存到: `data/output/candidates_*.jsonl`
- 简历图像保存到: `output/canvas_images/*.png`
- 通知日志: 完整操作记录
- 选择器命中: 14个元素
- 简历处理: 支持WASM文本和多页截图
- 决策结果: JSON格式，包含评分和推理

## 待完成功能

### P2 优先级
- ⏳ 自动黑名单扩充 (从消息页提取负面信息)
- ✅ 简历自动读取（在线简历抓取 + OCR 转 Markdown）
- ✅ 自动打招呼决策管道（YAML + OpenAI）
- ✅ DingTalk 通知（建议 greet 时发送）
- ⏳ 消息自动回复
- ⏳ 候选人监控 (新消息自动决策)
- ⏳ 多平台支持 (拉勾、智联招聘等)

### P3 优先级
- ⏳ 简历数据库 (候选人信息存储)
- ⏳ 数据分析 (招聘效果统计)
- ⏳ Web界面 (可视化管理)
- ⏳ 移动端支持 (手机端操作)

## 使用说明

### 启动服务
```bash
python start_service.py
```

### 客户端调用
```bash
# 获取候选人
curl "http://127.0.0.1:5001/chat/candidates?limit=10"

# 获取消息
curl "http://127.0.0.1:5001/chat/dialogs?limit=5"

# 搜索预览
curl "http://127.0.0.1:5001/search?city=北京&job_type=全职"
```

### 直接API调用
```bash
curl "http://127.0.0.1:5001/candidates?limit=5"
```

## 架构图
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   tutorial.ipynb│───▶│  boss_service   │───▶│   Playwright    │
│   (教程文档)     │    │  (FastAPI服务)  │    │   (浏览器自动化) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   数据存储      │
                       │ (JSONL/JSON)    │
                       └─────────────────┘
```

## 配置说明

### 环境变量
- `BOSS_SERVICE_HOST`: 服务主机 (默认: 127.0.0.1)
- `BOSS_SERVICE_PORT`: 服务端口 (默认: 5001)
- `BOSS_STORAGE_STATE_FILE`: 登录状态文件
- `BOSS_STORAGE_STATE_JSON`: 登录状态JSON

### 文件结构
```
bosszhipin_bot/
├── boss_service.py          # 主服务
├── tutorial.ipynb           # 教程文档
├── start_service.py         # 启动脚本
├── command.ipynb            # 演示Notebook
├── src/
│   ├── config.py            # 配置管理
│   ├── mappings.py          # 参数映射
│   ├── chat_utils.py         # 聊天工具
│   ├── blacklist.py         # 黑名单管理
│   ├── resume_capture.py    # 简历捕获
│   ├── ocr_service.py       # OCR服务
│   └── service/             # 服务模块
│       ├── browser.py       # 浏览器管理
│       ├── login.py         # 登录服务
│       ├── messages.py      # 消息服务
│       └── resume.py        # 简历服务
├── jobs/
│   └── criteria.yaml        # 岗位要求
├── data/
│   ├── state.json           # 登录状态
│   ├── blacklist.json       # 黑名单
│   └── output/              # 输出数据
├── test/                    # 测试文件
├── docs/
│   ├── status.md            # 本文档
│   ├── technical.md         # 技术文档
│   ├── architecture.mermaid # 架构图
│   ├── canvas_image_guide.md # Canvas指南
│   └── client_api_migration.md # API迁移
└── wasm/                    # WASM分析文件
```

## 风险控制
- ✅ 登录状态检测
- ✅ 黑名单过滤
- ✅ 操作频率控制
- ✅ 错误日志记录
- ✅ 资源自动清理

## 下一步计划
1. 实现候选人监控和自动决策
2. 添加消息自动回复功能
3. 完善事件缓存模块重构
4. 实现自动黑名单扩充
5. 优化简历捕获成功率
6. 添加Web界面管理
7. 支持多招聘平台集成
