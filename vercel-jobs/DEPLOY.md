# Quick Deployment Guide

## Prerequisites

1. Vercel account (free tier works)
2. FastAPI service running and accessible
3. Node.js installed (for Vercel CLI)

## Step 1: Configure FastAPI CORS

On your FastAPI server, set environment variable:

```bash
# Allow your Vercel domain (optional, defaults to allow all)
export CORS_ALLOWED_ORIGINS="https://your-app.vercel.app"
```

Or leave unset to allow all origins (development only).

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

## Step 3: Configure Environment Variable

1. Go to [Vercel Dashboard](https://vercel.com/dashboard)
2. Select your project
3. Go to **Settings** → **Environment Variables**
4. Add:
   - **Name**: `API_BASE_URL`
   - **Value**: Your FastAPI service URL (e.g., `https://your-api.com` or `http://localhost:5001` for local)
   - **Environment**: Production, Preview, Development (select all)

## Step 4: Redeploy

After adding environment variable, redeploy:

```bash
vercel --prod
```

Or trigger a new deployment from Vercel dashboard.

## Step 5: Test

Visit your Vercel URL (shown after deployment) and test:
- ✅ Load jobs list
- ✅ Create new job
- ✅ Edit existing job
- ✅ Switch versions
- ✅ Delete version

## Troubleshooting

### CORS Errors

If you see CORS errors in browser console:

1. Check FastAPI logs for CORS configuration
2. Verify `CORS_ALLOWED_ORIGINS` includes your Vercel URL
3. Check browser Network tab for preflight requests

### API Connection Failed

1. Verify `API_BASE_URL` is set in Vercel
2. Test API directly: `curl $API_BASE_URL/jobs/api/list`
3. Check FastAPI service is running and accessible

### Environment Variable Not Working

1. Make sure variable is set for all environments (Production, Preview, Development)
2. Redeploy after adding environment variable
3. Check variable name is exactly `API_BASE_URL`

## Production Checklist

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

