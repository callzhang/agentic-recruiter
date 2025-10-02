# Async Job Queue Documentation (ARCHIVED)

> **Note**: This feature was removed as it was unnecessary for single-user local automation.
> This document is kept for reference in case async functionality is needed in the future.

## Why It Was Removed

The async job queue added unnecessary complexity for a local, single-user automation tool:
- ❌ Extra code to maintain (~249 lines in `src/job_queue.py`)
- ❌ Polling overhead (client must repeatedly check job status)
- ❌ More complex error handling
- ❌ Unnecessary for synchronous, single-user workflows

## When You Might Need It Again

Consider re-implementing async queue if:
- ✅ Supporting multiple concurrent users
- ✅ Building a web service (not just local automation)
- ✅ Need to process 100+ candidates in parallel
- ✅ Want to decouple UI from long-running operations

## Simpler Alternatives

### For Local Automation (Current Approach)
```python
# Direct synchronous call - simple and clean
response = requests.post(f"{BASE_URL}/resume/online", json={"chat_id": chat_id})
result = response.json()
print(result['text'])
```

### For Batch Processing (If Needed)
```python
# Sequential processing - still simple
for chat_id in chat_ids:
    result = requests.post(f"{BASE_URL}/resume/online", json={"chat_id": chat_id})
    process_result(result.json())
```

### For True Async (If Needed)
```python
# Use Python's native asyncio - simpler than job queue
import asyncio
import httpx

async def process_resume(chat_id):
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}/resume/online", json={"chat_id": chat_id})
        return response.json()

async def batch_process(chat_ids):
    tasks = [process_resume(chat_id) for chat_id in chat_ids]
    results = await asyncio.gather(*tasks)
    return results

# Run it
results = asyncio.run(batch_process(chat_ids))
```

---

## Original Documentation (For Reference)

For the original async queue implementation details, see the git history:
```bash
git log --all --full-history -- "src/job_queue.py"
git show <commit_hash>:src/job_queue.py
```

### Key Components That Were Removed

1. **`src/job_queue.py`** (249 lines)
   - `JobQueue` class
   - `Job` dataclass  
   - `JobStatus` enum
   - Worker thread management
   - Auto-cleanup logic

2. **API Endpoints** (in `boss_service.py`)
   - `GET /jobs/{job_id}` - Check job status
   - `GET /jobs` - List jobs
   - `GET /jobs/stats` - Queue statistics
   - `POST /resume/online/async` - Queue resume view
   - `POST /resume/view_full/async` - Queue full resume

3. **Tutorial Examples**
   - Helper functions for async operations
   - Single async resume view example
   - Batch processing example
   - Queue monitoring example
   - Job status checking example

4. **Example Scripts**
   - `examples/async_queue_example.py`

### Code Complexity Reduction

- **Before**: ~1557 lines in `boss_service.py` + 249 lines in `src/job_queue.py` = **1806 lines**
- **After**: ~1350 lines in `boss_service.py` = **1350 lines**
- **Reduction**: **456 lines removed** (~25% less code)

---

**Last Updated**: 2025-10-02
**Archived By**: Simplification refactor for single-user local automation
