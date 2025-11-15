# 测试文档 (Test Documentation)

This directory contains the test suite for the Boss Zhipin automation bot.

## 测试文件概览 (Test Files Overview)

### ✅ 当前维护的测试 (Current Tests)

#### 1. `test_boss_service_api.py`
**描述**: Core API endpoint tests  
**类型**: Unit tests with mocking  
**覆盖范围**:
- Status and login endpoints
- Chat dialogs and messages
- Resume operations (request, view, accept)
- Candidate management (recommend, discard)
- Assistant/Thread operations (v2.4.0 updated to use `conversation_id`)
- Web UI routes
- Debug and Sentry integration

**运行**: 
```bash
pytest test/test_boss_service_api.py -v
```

**最近更新 (v2.4.0)**:
- ✅ Updated `test_thread_init_chat_endpoint` to use `conversation_id` instead of deprecated `thread_id`
- ✅ All tests aligned with current OpenAI Conversations API

---

#### 2. `test_candidate_workflow.py`
**描述**: Integration tests for candidate workflows  
**类型**: Integration tests (requires running service)  
**覆盖范围**:
- Service health checks
- Recommended candidates fetching
- Resume retrieval for candidates
- Chat dialog listing
- Assistant operations
- HTMX promise wrapper integration

**运行**:
```bash
# Start service first
python start_service.py

# In another terminal
pytest test/test_candidate_workflow.py -v
```

**注意**: These tests make real HTTP requests to `http://127.0.0.1:5001` and require the service to be running.

---

#### 3. `test_end_to_end.py`
**描述**: End-to-end candidate management flow  
**类型**: Integration test with mocking  
**覆盖范围**:
- Complete candidate workflow from recommendation to chat
- Resume fetching and analysis
- Message generation
- Multi-step flows

**运行**:
```bash
pytest test/test_end_to_end.py -v
```

---

#### 4. `test_jobs_comprehensive.py`
**描述**: Comprehensive tests for job management and versioning  
**类型**: Unit tests with mocking  
**覆盖范围**:
- Job store helper functions (get_base_job_id, etc.)
- Job CRUD operations (insert, update, get, delete)
- Job versioning (create versions, switch versions, delete versions)
- FastAPI job endpoints (create, update, delete, versions, switch-version)
- Edge cases and error handling
- Last version deletion logic (N-1 becomes current)

**运行**:
```bash
pytest test/test_jobs_comprehensive.py -v
```

---

#### 5. `test_resume_capture.py`
**描述**: Resume text capture and grouping logic  
**类型**: Unit tests  
**覆盖范围**:
- Text grouping by y-coordinate buckets
- WASM export parsing
- Edge cases (empty resumes, malformed data)

**运行**:
```bash
pytest test/test_resume_capture.py -v
```

---

## 运行所有测试 (Run All Tests)

### 完整测试套件 (Full Test Suite)
```bash
# Run all tests
pytest test/ -v

# Run with coverage
pytest test/ -v --cov=src --cov=web --cov-report=html

# Run specific test patterns
pytest test/ -v -k "candidate"
pytest test/ -v -k "resume"
```

### 快速验证 (Quick Validation)
```bash
# Run only unit tests (no service required)
pytest test/test_boss_service_api.py test/test_resume_capture.py -v

# Run only integration tests (service required)
pytest test/test_candidate_workflow.py test/test_end_to_end.py -v
```

---

## 测试环境准备 (Test Environment Setup)

### 依赖安装 (Install Dependencies)
```bash
pip install pytest pytest-cov pytest-asyncio httpx
```

### Mock 配置 (Mock Configuration)
大部分测试使用 `pytest.MonkeyPatch` 来模拟外部依赖:
- Playwright page objects
- OpenAI API calls
- Zilliz/Milvus database operations
- DingTalk webhooks
- Sentry error tracking

---

## 已移除的测试 (Removed Tests)

以下测试文件已被移除，因为它们测试的功能不再存在或已过时，或者已被合并到其他测试文件中:

### ❌ `test_job_versioning.py`
- **原因**: 所有测试已合并到 `test_jobs_comprehensive.py`
- **功能**: 岗位版本管理测试（已完全覆盖）
- **移除日期**: v2.4.2 (2025-11-15)
- **替代**: 使用 `test_jobs_comprehensive.py`，包含更全面的测试覆盖

### ❌ `test_decide_pipeline.py`
- **原因**: 依赖已移除的 `boss_client` 模块
- **功能**: 测试不存在的 decide pipeline 功能
- **移除日期**: v2.4.0 (2025-11-13)

### ❌ `test_watcher.py`
- **原因**: 依赖已移除的 `boss_client` 模块
- **功能**: 测试不存在的 watcher 功能
- **移除日期**: v2.4.0 (2025-11-13)

### ❌ `test_subgraph_runtime.py`
- **原因**: LangGraph 示例/演示文件，不是真正的测试
- **功能**: LangGraph 子图运行时示例
- **移除日期**: v2.4.0 (2025-11-13)

### ❌ `langgraph.json`
- **原因**: 上述 LangGraph 演示的配置文件
- **移除日期**: v2.4.0 (2025-11-13)

---

## 测试策略 (Testing Strategy)

### 单元测试 (Unit Tests)
- Mock 外部依赖 (Playwright, OpenAI, Zilliz)
- 快速执行，无需真实浏览器或网络
- 关注单个函数或端点的行为

### 集成测试 (Integration Tests)
- 需要运行的服务实例
- 测试多个组件的交互
- 验证真实的 HTTP 请求/响应

### 测试覆盖率目标 (Coverage Goals)
- **Core logic (src/)**: > 70%
- **API endpoints (boss_service.py)**: > 60%
- **Web routes (web/routes/)**: > 50%

---

## 常见问题 (FAQ)

### Q: 测试失败，提示 "connection refused"
**A**: 确保 `start_service.py` 正在运行（针对集成测试）

### Q: 测试挂起或超时
**A**: 检查 CDP Chrome 是否正在运行：`ps aux | grep chrome`

### Q: Mock 不生效
**A**: 确保 `monkeypatch` 在正确的模块上应用。使用 `import` 路径与测试文件中的一致。

### Q: 如何添加新测试？
**A**: 
1. 为新端点/功能添加测试到相应的测试文件
2. 使用现有的 fixture 和 mock 模式
3. 确保测试是确定性的（不依赖时间或随机性）
4. 运行 `pytest` 验证所有测试通过

---

## 持续集成 (CI/CD)

测试套件设计为可在 CI/CD 管道中运行:

```yaml
# Example GitHub Actions
- name: Run Tests
  run: |
    pip install -r requirements.txt
    pytest test/ -v --cov=src --cov-report=xml
```

**注意**: 集成测试需要模拟服务或跳过（使用 `@pytest.mark.integration` 标记）

---

## 版本历史 (Version History)

### v2.4.2 (2025-11-15)
- ✅ 合并 `test_job_versioning.py` 到 `test_jobs_comprehensive.py`
- ✅ 统一岗位版本管理测试，提高测试覆盖率
- 📝 更新 README 文档

### v2.4.0 (2025-11-13)
- ✅ 更新 `test_boss_service_api.py` 使用 `conversation_id` 替代 `thread_id`
- ❌ 移除 `test_decide_pipeline.py`（已过时）
- ❌ 移除 `test_watcher.py`（已过时）
- ❌ 移除 `test_subgraph_runtime.py`（演示文件）
- ❌ 移除 `langgraph.json`（演示配置）
- 📝 新增此 README 文档

### v2.3.0
- OpenAI Conversations API 集成
- 候选人管理系统重构

### v2.2.0
- 初始测试套件
- API 端点覆盖
- Resume capture 测试

---

**维护者**: Boss Zhipin Bot Team  
**最后更新**: 2025-11-15  
**当前版本**: v2.4.2

