# Scripts Directory

This directory contains utility scripts for managing and debugging the Boss直聘 automation system.

## 🗂️ Active Scripts (v2.4.0)

> 注：除数据迁移/调试脚本外，岗位肖像与 prompt 的日常迭代建议优先走：
> - 线上（Vercel）：`/jobs/optimize`（评分不准→生成→diff→发布）
> - 离线回放：`scripts/prompt_optmization/README.md`

### Data Management

#### `migrate_candidates_data.py` - Data Migration (15KB)
Migrate candidate data from one Zilliz collection to another with schema updates.

**Features**:
- Increases `resume_text` and `full_resume` max_length to 65535
- Deduplicates candidates by name
- Converts `thread_id` to `conversation_id`

**Usage**:
```bash
python scripts/migrate_candidates_data.py
```

**Latest Run (v2.4.0)**:
- Migrated 152 records to `CN_candidates_v3`
- Removed 10 duplicates
- Updated field max_length from 25000/30000 to 65535

---

#### `cleanup_thread_conversation_ids.py` - Conversation ID Cleanup (4.1KB)
Clean up old `conversation_id` entries that start with "thread_" (legacy format).

**Usage**:
```bash
python scripts/cleanup_thread_conversation_ids.py
```

**Latest Run (v2.4.0)**:
- Updated 61 candidates
- Set old `thread_*` conversation_ids to null

---

#### `zilliz_manager.py` - Zilliz Collection Manager (8.2KB)
Comprehensive utility for managing Zilliz collections and schema.

**Usage**:
```bash
# Check Milvus version and capabilities
python scripts/zilliz_manager.py version

# List all collections
python scripts/zilliz_manager.py list

# Create new collection
python scripts/zilliz_manager.py create --new-collection CN_candidates_v4

# Migrate data between collections
python scripts/zilliz_manager.py migrate --new-collection CN_candidates_v4
```

---

#### `create_new_candidate_schema.py` - Schema Definition (4.8KB)
Create new candidate collection with updated schema.

**Usage**:
```bash
python scripts/create_new_candidate_schema.py
```

---

### Jobs Management

#### `migrate_jobs_to_cn_jobs_2.py` - Jobs Migration (8.4KB)
Migrate job definitions to new schema.

**Usage**:
```bash
python scripts/migrate_jobs_to_cn_jobs_2.py
```

---

## 🧩 Prompt / 岗位肖像迭代（离线可复盘）

目录：`scripts/prompt_optmization/`

核心脚本：
- `scripts/prompt_optmization/download_data_for_prompt_optimization.py`
  - 拉取指定岗位的最新候选人样本（默认 10 份，倒序按对话更新时间），并生成本批次复盘骨架
  - 不会调用 OpenAI 重跑分析（只下载数据 + 统计 + 报告骨架）
- `scripts/prompt_optmization/generate_optimized.py`
  - 基于候选人 history + 当前 `assistant_actions_prompts.md` 与 `job_portrait_optimized.json` 生成“新口径 analysis + 新 message”
  - 输出到 `generated/*.generated.json`，并把问题示例（带引用）写回 `优化报告.md`

详见：`scripts/prompt_optmization/README.md`

### UI Assets

#### `generate_favicon.py` - Favicon Generator (1.2KB)
Validate SVG favicon (v2.4.0: simplified, removed PNG/ICO generation).

**Usage**:
```bash
python scripts/generate_favicon.py
```

**Changes in v2.4.0**:
- Removed `cairosvg` and `Pillow` dependencies
- Now only validates SVG file existence and format
- Modern browsers support SVG favicons directly

---

### Debugging Tools

#### `debug_wasm_export.py` - WASM Resume Debug (6.8KB)
Deep debugging for WASM-based resume extraction with structured logging.

**Usage**:
```bash
# Debug with first available chat
python scripts/debug_wasm_export.py

# Debug specific chat ID
python scripts/debug_wasm_export.py --chat-id abc123

# Use local WASM bundle
python scripts/debug_wasm_export.py --use-local-wasm

# Custom output path
python scripts/debug_wasm_export.py --output custom_debug.json
```

---

### Agent Framework (Experimental)

#### `orchestrator-worker-graph.py` - LangGraph Demo (5.7KB)
Experimental LangGraph orchestrator-worker pattern demonstration.

**Note**: This is a demo/research script, not part of the production system.

---

## 📚 Additional Resources

### Jupyter Notebooks

#### `zilliz.ipynb`
Interactive notebook for exploring and testing Zilliz operations.

### Output Files

- `debug_wasm_export_output.json` - Sample debug output from WASM export debugging

### Documentation

- `README_chrome_management.md` - Chrome CDP management guide

---

## 🚀 Usage Examples

### Complete Collection Migration Workflow

```bash
# 1. Check current setup
python scripts/zilliz_manager.py version
python scripts/zilliz_manager.py list

# 2. Run migration script (creates CN_candidates_v3)
python scripts/migrate_candidates_data.py

# 3. Clean up old conversation IDs
python scripts/cleanup_thread_conversation_ids.py

# 4. Update config/config.yaml to use new collection
# Set: zilliz.collection_name = CN_candidates_v3

# 5. Restart service to use new collection
python start_service.py
```

### Debugging Workflow

```bash
# 1. Start Chrome and service
python start_service.py  # Automatically starts Chrome via CDP

# 2. Debug resume extraction
python scripts/debug_wasm_export.py --chat-id your_chat_id

# 3. Check WASM output
cat scripts/debug_wasm_export_output.json
```

---

## 🗑️ Removed Scripts (v2.4.0)

The following scripts have been removed as they are outdated or no longer needed:

### ❌ `alter_zilliz_fields.py`
- **Reason**: Functionality merged into `zilliz_manager.py`
- **Alternative**: Use `zilliz_manager.py alter`

### ❌ `check_milvus_version.py`
- **Reason**: Functionality merged into `zilliz_manager.py`
- **Alternative**: Use `zilliz_manager.py version`

### ❌ `debug_chrome.py`
- **Reason**: Empty file, no functionality
- **Alternative**: Use browser DevTools or `start_service.py` logs

### ❌ `debug_recommend_resume.py`
- **Reason**: Outdated, doesn't match current API
- **Alternative**: Use Web UI `/candidates` page for debugging

---

## ⚙️ Environment Requirements

All scripts require:
- **Python 3.11+** (recommended)
- Proper configuration in `config/config.yaml` and `config/secrets.yaml`
- Chrome running with CDP enabled (for browser-related scripts)
  - Automatically started by `start_service.py`
  - Default CDP URL: `http://127.0.0.1:9222`
- Zilliz/Milvus connection (for database scripts)

### Installation

```bash
pip install -r requirements.txt
```

---

## 🐛 Troubleshooting

### Common Issues

1. **Chrome connection failed**
   - Ensure Chrome is running with CDP enabled
   - Check `start_service.py` logs for CDP connection status
   - Default CDP endpoint: `http://127.0.0.1:9222`

2. **Zilliz connection failed**
   - Check credentials in `config/secrets.yaml`
   - Verify network connectivity to Zilliz Cloud
   - Use `zilliz_manager.py version` to test connection

3. **Collection not found**
   - Use `zilliz_manager.py list` to see available collections
   - Check `config/config.yaml` for correct collection name
   - Current collection (v2.4.0): `CN_candidates_v3`

4. **Migration failed**
   - Check that both source and target collections exist
   - Ensure sufficient Zilliz storage quota
   - Review migration script logs for specific errors

### Getting Help

- Check script help: `python scripts/script_name.py --help`
- Review debug output files for detailed error information
- Check `docs/` directory for additional documentation
- See `CHANGELOG.md` for recent changes and known issues

---

## 📊 Version History

### v2.4.0 (2025-11-13)
- ✅ Added `cleanup_thread_conversation_ids.py` for conversation ID cleanup
- ✅ Updated `migrate_candidates_data.py` to support max_length 65535
- ✅ Simplified `generate_favicon.py` (removed image conversion)
- ❌ Removed `alter_zilliz_fields.py` (merged into zilliz_manager)
- ❌ Removed `check_milvus_version.py` (merged into zilliz_manager)
- ❌ Removed `debug_chrome.py` (empty file)
- ❌ Removed `debug_recommend_resume.py` (outdated)
- 📝 Completely rewrote README with current scripts only

### v2.3.0
- Initial scripts collection
- Zilliz management utilities
- Chrome management utilities
- WASM debugging tools

---

**Last Updated**: 2025-11-13  
**Current Version**: v2.4.0  
**Maintained Scripts**: 8 active + 3 notebooks/configs
