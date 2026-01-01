# Boss Zhipin Bot - Vercel Deployment

Unified Vercel deployment for Boss Zhipin bot, including homepage statistics dashboard and jobs editor.

**Both pages connect directly to Zilliz database** and use Vercel serverless functions. No FastAPI backend required.

## Features

### Homepage (`/`)
- ✅ Real-time statistics dashboard
- ✅ Job performance metrics
- ✅ Progress scores and conversion rates
- ✅ Interactive charts (Chart.js)
- ✅ Responsive design
- ✅ 自动跳过 `status=inactive` 的岗位统计（避免噪音）

### Jobs Editor (`/jobs`)
- ✅ Create, update, and delete jobs
- ✅ Version management (view, switch, delete versions)
- ✅ Keywords editor (positive/negative tags)
- ✅ Candidate filters (JSON editor with validation)
- ✅ Drill down questions
- ✅ All job description fields

### Job Portrait Optimization (`/jobs/optimize`)
- ✅ “评分不准”人类反馈：在候选人详情页点击“评分不准”写入 `CN_job_optimizations`
- ✅ 优化清单：按岗位查看反馈、编辑目标分与建议
- ✅ 生成新版岗位肖像：调用 OpenAI（严格 JSON schema 输出）并提供字段级 diff 可编辑
- ✅ 一键发布：发布新版本岗位肖像并把本次选中的反馈标记为 `closed`

## Setup

### 1. Configure Zilliz Environment Variables

Both pages connect directly to Zilliz. Set these environment variables in Vercel:

1. Go to [Vercel Dashboard](https://vercel.com/dashboard) → Your Project → Settings → Environment Variables
2. Add the following variables (for all environments: Production, Preview, Development):

```
ZILLIZ_ENDPOINT=https://in03-xxxxx.serverless.gcp-us-west1.cloud.zilliz.com
ZILLIZ_USER=db_xxxxx
ZILLIZ_PASSWORD=your_password
ZILLIZ_CANDIDATE_COLLECTION_NAME=CN_candidates
ZILLIZ_JOB_COLLECTION_NAME=CN_jobs
ZILLIZ_JOB_OPTIMIZATION_COLLECTION_NAME=CN_job_optimizations
ZILLIZ_EMBEDDING_DIM=1536
ZILLIZ_TOKEN=  (leave empty or set if using API key authentication)
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=...
DINGTALK_SECRET=SEC...
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.2
OPENAI_MODEL_OPTIMIZATION=gpt-5.2
OPENAI_BASE_URL=https://api.openai.com/v1
```

**Note:** 
- Zilliz credentials are from your `config/secrets.yaml` file. The pages use the same Zilliz database as your FastAPI service.
- DingTalk credentials are for daily report notifications (see "Daily Reports" section below).
- OpenAI credentials are required for `/jobs/optimize/generate`（生成新版岗位肖像）与相关 AI 能力。

### 2. Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy
cd vercel
vercel

# Deploy to production
vercel --prod
```

### 3. Test the Deployment

Visit your Vercel URL and test:

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
- ✅ Open `/jobs/optimize?job_id=architecture` → 查看/编辑优化清单
- ✅ 勾选若干反馈 → “生成新版岗位肖像” → 字段级 diff/可编辑 → “确认提交（发布新版本）”

## Local Development

```bash
# Install Vercel CLI
npm install -g vercel

# Run local dev server
cd vercel

# (Recommended) Use the safety wrapper to avoid "hangs" caused by iCloud
# `dataless` lockfiles in parent directories on macOS:
chmod +x ./vercel_safe.sh
./vercel_safe.sh dev
# If you run it in a non-interactive environment and see a confirmation error,
# add `--yes`:
# ./vercel_safe.sh dev --yes
```

The pages will be available at:
- Homepage: `http://localhost:3000`

## MCP: University Lookup (QS/211/985)

This repo exposes an MCP endpoint for university background lookup (QS 2026 rank + 211/985):

- Prod: `https://boss-hunter.vercel.app/api/mcp_university`
- Local: `http://localhost:3000/api/mcp_university`

Quick test:

```bash
curl -s "http://localhost:3000/api/mcp_university"
curl -s -X POST "http://localhost:3000/api/mcp_university" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"lookup_university_background","arguments":{"school_name":"清华大学"}}}'
```

### Python Test Script

A python script is provided to test the OpenAI Responses API + MCP tool integration:

```bash
# Basic usage with config/secrets.yaml
python scripts/test_mcp_university_tool.py --school "清华大学"

# With custom MCP URL and detailed output
python scripts/test_mcp_university_tool.py --school "清华大学" \
  --mcp-url "http://localhost:3000/api/mcp_university" \
  --verbose
```

Dataset file:
- `vercel/api/2026_qs_world_university_rankings.xlsx`
- Jobs Editor: `http://localhost:3000/jobs`

### Troubleshooting: `vercel dev` / `vercel --prod` hangs

On macOS, if your repo is under an iCloud-managed folder (commonly `~/Documents`),
some files may become iCloud "dataless" placeholders. If Vercel/Node tooling tries
to read such a lockfile (e.g. a parent `package-lock.json`), the read can block
waiting for iCloud to download it, making Vercel commands appear to freeze.

Check (from `vercel/`):

```bash
./vercel_safe.sh doctor
```

Fix options:
- Download the reported lockfile (or mark its folder as “Always Keep on This Device”)
- Move the repo to a non‑iCloud folder (e.g. `~/Dev/...`)
- Remove/rename the unneeded lockfile so it won’t be detected

## API Endpoints

The pages use Vercel serverless functions that connect directly to Zilliz:

### Statistics API (`api/stats.py`)
- `GET /api/stats` - Calculate and return statistics from Zilliz database (JSON format)
- `GET /api/stats?format=report` - Return formatted Markdown report for DingTalk

### Daily Reports API (`api/send-daily-report.py`)
- `GET /api/send-daily-report` - Send daily reports to DingTalk (called by Vercel Cron Jobs)
  - Sends 1 overall report (all jobs summary) to default DingTalk webhook
  - Sends N individual job reports (one per job) to job-specific or default DingTalk webhook

### Jobs API (`api/jobs.py`)
- `GET /api/jobs/list` - List all jobs
- `GET /api/jobs/:job_id` - Get specific job
- `POST /api/jobs/create` - Create new job
- `POST /api/jobs/:job_id/update` - Update job (creates new version)
- `GET /api/jobs/:job_id/versions` - Get all versions
- `POST /api/jobs/:job_id/switch-version` - Switch current version
- `DELETE /api/jobs/:job_id/delete` - Delete a version

### Job Optimization API (`api/jobs.py`)
- `GET /api/jobs/optimizations/count?job_id=...` - Feedback count (open only)
- `GET /api/jobs/optimizations/list?job_id=...` - Feedback list (open only)
- `POST /api/jobs/optimizations/add` - Add feedback item (评分不准)
- `POST /api/jobs/optimizations/update` - Update feedback item
- `POST /api/jobs/optimizations/generate` - Generate optimized job portrait (OpenAI)
- `POST /api/jobs/optimizations/publish` - Publish new version + close feedback items

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

### Jobs API Errors

If jobs operations fail:

1. Check Vercel function logs for detailed error messages
2. Verify Zilliz job collection exists and is accessible
3. Check that job_id format is correct (base_job_id or versioned_job_id)
4. Verify all required fields are provided in API requests

## Daily Reports (Vercel Cron Jobs)

The deployment includes a daily report feature that automatically sends statistics to DingTalk every day at 7:00 AM (Beijing time).

### How It Works

1. **Vercel Cron Jobs** automatically calls `/api/send-daily-report` daily at UTC 23:00 (7:00 AM Beijing time)
2. The function generates and sends:
   - **1 overall report**: Summary of all jobs, sent to default DingTalk webhook (from `DINGTALK_WEBHOOK` environment variable)
   - **N job reports**: Individual report for each **active** job, sent to:
     - Job-specific DingTalk webhook (if configured in job's `notification` field)
     - Default DingTalk webhook (fallback if job doesn't have notification config)
   - **Note**: Jobs with `status` set to `"inactive"` are automatically skipped and will not receive daily reports

### Configuration

1. **Environment Variables** (required):
   - `DINGTALK_WEBHOOK`: Default DingTalk webhook URL (from `config/secrets.yaml`)
   - `DINGTALK_SECRET`: Default DingTalk secret (from `config/secrets.yaml`)

2. **Job-specific Configuration** (optional):
   - Each job can have its own `notification` field in the job collection:
     ```json
     {
       "notification": {
         "url": "https://oapi.dingtalk.com/robot/send?access_token=...",
         "secret": "SEC..."
       }
     }
     ```
   - If a job has `notification` configured, its report will be sent to that webhook
   - Otherwise, it falls back to the default webhook
   
3. **Job Status** (optional):
   - Each job can have a `status` field in the job collection:
     - `"active"` (default): Job will receive daily reports
     - `"inactive"`: Job will **not** receive daily reports (skipped automatically)
   - To set a job as inactive, update the job's `status` field to `"inactive"` in the jobs editor

4. **Cron Schedule**:
   - Configured in `vercel.json`:
     ```json
     {
       "crons": [
         {
           "path": "/api/send-daily-report",
           "schedule": "0 23 * * *"
         }
       ]
     }
     ```
   - `0 23 * * *` = UTC 23:00 = 7:00 AM Beijing time

### Requirements

- **Vercel Pro or Enterprise plan** (Cron Jobs are not available on the free plan)
- See [Vercel Cron Jobs documentation](https://vercel.com/docs/cron-jobs/usage-and-pricing) for details

### Report Format

**Overall Report** includes:
- Total candidate count
- Today's new candidates
- Last 7 days / 30 days totals
- Growth rates (vs yesterday, vs last week)
- Job statistics table (all jobs with today's metrics)

**Individual Job Report** includes:
- Job name
- Today's new candidates and SEEK count
- Total count, quality score, progress score
- Last 7 days trend

## File Structure

```
vercel/
├── api/
│   ├── jobs.py              # Jobs API serverless function
│   ├── stats.py             # Statistics API serverless function
│   └── send-daily-report.py # Daily report sender (Cron Jobs)
├── public/
│   ├── index.html           # Homepage (statistics dashboard)
│   ├── jobs.html            # Jobs editor page
│   └── stats.js             # Statistics JavaScript
├── vercel.json              # Vercel configuration (includes crons)
├── package.json             # Node.js package file
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Security Notes

⚠️ **No Authentication**: These pages have no authentication. Anyone with the URL can access them.

For production use:
1. Add authentication (e.g., Vercel's password protection)
2. Use Vercel's access control features
3. Restrict API endpoints if needed
