# Quick Deployment Guide

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
ZILLIZ_EMBEDDING_DIM=1536
ZILLIZ_TOKEN=  (leave empty or set if using API key authentication)
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
3. Check that job_id format is correct
4. Verify all required fields are provided in API requests

