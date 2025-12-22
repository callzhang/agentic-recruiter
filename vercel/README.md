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

### Jobs Editor (`/jobs`)
- ✅ Create, update, and delete jobs
- ✅ Version management (view, switch, delete versions)
- ✅ Keywords editor (positive/negative tags)
- ✅ Candidate filters (JSON editor with validation)
- ✅ Drill down questions
- ✅ All job description fields

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
ZILLIZ_EMBEDDING_DIM=1536
ZILLIZ_TOKEN=  (leave empty or set if using API key authentication)
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=...
DINGTALK_SECRET=SEC...
```

**Note:** 
- Zilliz credentials are from your `config/secrets.yaml` file. The pages use the same Zilliz database as your FastAPI service.
- DingTalk credentials are for daily report notifications (see "Daily Reports" section below).

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

## Local Development

```bash
# Install Vercel CLI
npm install -g vercel

# Run local dev server
cd vercel
vercel dev
```

The pages will be available at:
- Homepage: `http://localhost:3000`
- Jobs Editor: `http://localhost:3000/jobs`

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

