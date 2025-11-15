# Quick Deployment Guide

## Prerequisites

1. Vercel account (free tier works)
2. FastAPI service running and accessible
3. Node.js installed (for Vercel CLI)

## Step 1: Configure Zilliz Environment Variables

This page connects directly to Zilliz - no FastAPI service needed!

In Vercel Dashboard → Settings → Environment Variables, add:

```
ZILLIZ_ENDPOINT=https://in03-819fce57d41682b.serverless.gcp-us-west1.cloud.zilliz.com
ZILLIZ_USER=db_819fce57d41682b
ZILLIZ_PASSWORD=Bt1!A&bSQdB[~8fl
ZILLIZ_JOB_COLLECTION_NAME=CN_jobs
ZILLIZ_EMBEDDING_DIM=1536
```

(Get these values from your `config/secrets.yaml` file)

## Step 2: Deploy to Vercel

```bash
# Navigate to vercel-jobs directory
cd vercel-jobs

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
3. Verify the collection name is correct (`CN_jobs` by default)
4. Check Vercel function logs for detailed error messages

### Environment Variable Not Working

1. Make sure variables are set for all environments (Production, Preview, Development)
2. Redeploy after adding environment variables
3. Check variable names match exactly (case-sensitive)

- [ ] Set `CORS_ALLOWED_ORIGINS` on FastAPI to specific Vercel domain
- [ ] Set `API_BASE_URL` in Vercel environment variables
- [ ] Test all CRUD operations
- [ ] Verify version management works
- [ ] Check mobile responsiveness
- [ ] Consider adding authentication (Vercel password protection)

## Custom Domain

To use a custom domain:

1. Go to Vercel Dashboard → Your Project → Settings → Domains
2. Add your domain
3. Follow DNS configuration instructions
4. Update `CORS_ALLOWED_ORIGINS` on FastAPI to include custom domain

