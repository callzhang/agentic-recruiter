# Quick Deployment Guide

## 概述

Vercel 部署使用 `BaseHTTPRequestHandler` 模式（而非 FastAPI），提供更好的 JSON 序列化控制和 Vercel Python runtime 兼容性。

**主要 API 端点**:
- `/api/stats` - 统计和报告 API
- `/api/jobs` - 岗位管理 API  
- `/api/candidate` - 候选人详情 API
- `/jobs/optimize` - 岗位肖像优化（清单页）
- `/jobs/optimize/generate` - 岗位肖像优化（生成/对比/发布页）

所有 API 使用 `BaseHTTPRequestHandler` 实现，自动处理 JSON 序列化（包括 Milvus 返回的 bytes 键问题）。

## Prerequisites

1. Vercel account (free tier works)
2. Zilliz database access credentials
3. Node.js installed (for Vercel CLI)

## Step 1: Configure Zilliz Environment Variables

Both pages connect directly to Zilliz - no FastAPI service needed!

In Vercel Dashboard → Settings → Environment Variables, add:

```
ZILLIZ_ENDPOINT=https://in03-xxxxx.serverless.gcp-us-west1.cloud.zilliz.com
ZILLIZ_USER=db_xxxxx
ZILLIZ_PASSWORD=your_password
ZILLIZ_CANDIDATE_COLLECTION_NAME=CN_candidates
ZILLIZ_JOB_COLLECTION_NAME=CN_jobs
ZILLIZ_JOB_OPTIMIZATION_COLLECTION_NAME=CN_job_optimizations
ZILLIZ_EMBEDDING_DIM=1536
ZILLIZ_TOKEN=  (leave empty or set if using API key authentication)

# Required for job portrait optimization (generate/publish)
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1  # optional
```

(Get these values from your `config/secrets.yaml` file)

## Step 2: Deploy to Vercel

```bash
# Navigate to vercel directory
cd vercel

# Install Vercel CLI (if not already installed)
npm install -g vercel

# Login to Vercel
vercel login

# Deploy
vercel

# Follow prompts:
# - Set up and deploy? Yes
# - Which scope? (select your account)
# - Link to existing project? No
# - Project name? (press enter for default)
# - Directory? ./
# - Override settings? No
```

## Step 3: Redeploy

After adding environment variable, redeploy:

```bash
vercel --prod
```

Or trigger a new deployment from Vercel dashboard.

## Step 4: Test

Visit your Vercel URL (shown after deployment) and test:

**Homepage (`/`):**
- ✅ Load homepage
- ✅ Display quick stats
- ✅ Display job statistics
- ✅ Render charts

**Jobs Editor (`/jobs`):**
- ✅ Load jobs list
- ✅ Create new job
- ✅ Edit existing job
- ✅ Switch versions
- ✅ Delete version

**Optimization (`/jobs/optimize`):**
- ✅ Open a candidate detail page: `/candidate/:candidate_id` → 点击“评分不准”保存反馈
- ✅ Open `/jobs/optimize?job_id=<base_job_id>` → 查看/编辑优化清单
- ✅ 勾选若干反馈 → “生成新版岗位肖像” → 字段级 diff/可编辑 → “确认提交（发布新版本）”

## Troubleshooting

### Zilliz Connection Errors

If you see connection errors:

1. Verify all Zilliz environment variables are set in Vercel
2. Check that credentials match your `config/secrets.yaml`
3. Verify the collection names are correct (`CN_candidates` and `CN_jobs` by default)
4. Check Vercel function logs for detailed error messages

### Environment Variable Not Working

1. Make sure variables are set for all environments (Production, Preview, Development)
2. Redeploy after adding environment variables
3. Check variable names match exactly (case-sensitive)

### Statistics Calculation Errors

If statistics are not loading:

1. Check that both candidate and job collections exist in Zilliz
2. Verify collection names match environment variables
3. Check Vercel function logs for calculation errors
4. Ensure numpy is properly installed (check `requirements.txt`)

### JSON Serialization Errors (TypeError: keys must be str...)

If you see `TypeError: keys must be str, int, float, bool or None, not bytes`:

1. This is automatically handled by `_json_safe()` function in `vercel/api/stats.py`
2. The function recursively cleans Milvus results, converting bytes keys to strings
3. If errors persist, check Vercel function logs for detailed error messages
4. Ensure all Milvus query results are passed through `_json_safe()` before serialization

### Jobs API Errors

If jobs operations fail:

1. Check Vercel function logs for detailed error messages
2. Verify Zilliz job collection exists and is accessible
3. Check that job_id format is correct
4. Verify all required fields are provided in API requests
