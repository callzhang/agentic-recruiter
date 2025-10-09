# Scripts Directory

This directory contains utility scripts for managing and debugging the Boss直聘 automation system.

## Zilliz/Milvus Management

### `zilliz_manager.py` - Comprehensive Zilliz Management
Main utility for managing Zilliz collections and schema.

```bash
# Check Milvus version and capabilities
python scripts/zilliz_manager.py version

# List all collections
python scripts/zilliz_manager.py list

# Alter field max_length in existing collection
python scripts/zilliz_manager.py alter --collection CN_candidates

# Create new collection with all fields
python scripts/zilliz_manager.py create --new-collection CN_candidates_final

# Migrate data between collections
python scripts/zilliz_manager.py migrate --new-collection CN_candidates_v2
```

### `migrate_candidates_data.py` - Data Migration
Migrate candidate data from one collection to another.

```bash
python scripts/migrate_candidates_data.py
```

### `setup_zilliz_collection.py` - Collection Setup
Ensure Zilliz collections are properly configured.

```bash
python scripts/setup_zilliz_collection.py
```

## Chrome Management

### `manage_chrome.py` - Chrome Process Management
Independent Chrome instance management for the automation system.

```bash
# Check Chrome status
python scripts/manage_chrome.py status

# Start Chrome
python scripts/manage_chrome.py start

# Stop Chrome
python scripts/manage_chrome.py stop

# Restart Chrome
python scripts/manage_chrome.py restart

# Custom configuration
python scripts/manage_chrome.py start --port 9223 --user-data /tmp/my_profile
```

See `README_chrome_management.md` for detailed Chrome management documentation.

## Debugging Tools

### `debug_recommend_resume.py` - Recommendation Debug
Debug recommended candidate resume extraction.

```bash
# Debug first candidate (index 0)
python scripts/debug_recommend_resume.py

# Debug specific candidate
python scripts/debug_recommend_resume.py --index 2

# Inspect only (no full extraction)
python scripts/debug_recommend_resume.py --inspect-only

# Save output to file
python scripts/debug_recommend_resume.py --output debug_output.json
```

### `debug_wasm_export.py` - WASM Resume Debug
Deep debugging for WASM-based resume extraction with structured logging.

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

## Jupyter Notebooks

### `zilliz.ipynb` - Interactive Zilliz Operations
Interactive notebook for exploring and testing Zilliz operations.

## Output Files

- `debug_wasm_export_output.json` - Sample debug output from WASM export debugging

## Environment Requirements

All scripts require:
- Python 3.8+
- Proper configuration in `config/secrets.yaml`
- Chrome running with CDP enabled (for browser-related scripts)
- Zilliz/Milvus connection (for database scripts)

## Usage Examples

### Complete Collection Migration Workflow

```bash
# 1. Check current setup
python scripts/zilliz_manager.py version
python scripts/zilliz_manager.py list

# 2. Create new collection with all fields
python scripts/zilliz_manager.py create --new-collection CN_candidates_final

# 3. Migrate data
python scripts/zilliz_manager.py migrate --new-collection CN_candidates_final

# 4. Update config/secrets.yaml to use new collection
# 5. Test the new collection
```

### Chrome Management Workflow

```bash
# 1. Check Chrome status
python scripts/manage_chrome.py status

# 2. Start Chrome if needed
python scripts/manage_chrome.py start

# 3. Start the main service
python start_service.py

# 4. Stop Chrome when done
python scripts/manage_chrome.py stop
```

### Debugging Workflow

```bash
# 1. Start Chrome and service
python scripts/manage_chrome.py start
python start_service.py

# 2. Debug resume extraction
python scripts/debug_wasm_export.py --chat-id your_chat_id

# 3. Debug recommendation system
python scripts/debug_recommend_resume.py --index 0

# 4. Clean up
python scripts/manage_chrome.py stop
```

## Troubleshooting

### Common Issues

1. **Chrome connection failed**: Ensure Chrome is running with CDP enabled
2. **Zilliz connection failed**: Check credentials in `config/secrets.yaml`
3. **Collection not found**: Use `zilliz_manager.py list` to see available collections
4. **Migration failed**: Check that both source and target collections exist

### Getting Help

- Check script help: `python scripts/script_name.py --help`
- Review debug output files for detailed error information
- Ensure all dependencies are installed and configured correctly
