# Jobs Editor - Vercel Deployment

Full-featured standalone jobs editor page for Boss Zhipin bot, deployed on Vercel.

**This is a completely standalone page** - it connects directly to Zilliz database and doesn't require the FastAPI service to be running.

## Features

- ✅ Create, update, and delete jobs
- ✅ Version management (view, switch, delete versions)
- ✅ Keywords editor (positive/negative tags)
- ✅ Candidate filters (JSON editor with validation)
- ✅ Drill down questions
- ✅ All job description fields
- ✅ Direct Zilliz connection (no FastAPI needed)

## Setup

### 1. Configure Zilliz Environment Variables

The page connects directly to Zilliz. Set these environment variables in Vercel:

1. Go to [Vercel Dashboard](https://vercel.com/dashboard) → Your Project → Settings → Environment Variables
2. Add the following variables (for all environments: Production, Preview, Development):

```
ZILLIZ_ENDPOINT=https://in03-819fce57d41682b.serverless.gcp-us-west1.cloud.zilliz.com
ZILLIZ_USER=db_819fce57d41682b
ZILLIZ_PASSWORD=Bt1!A&bSQdB[~8fl
ZILLIZ_JOB_COLLECTION_NAME=CN_jobs
ZILLIZ_EMBEDDING_DIM=1536
ZILLIZ_TOKEN=  (leave empty or set if using API key authentication)
```

**Note:** These credentials are from your `config/secrets.yaml` file. The page uses the same Zilliz database as your FastAPI service.

### 2. Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy
cd vercel-jobs
vercel

# Deploy to production
vercel --prod
```

### 3. Test the Deployment

Visit your Vercel URL and test:
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
cd vercel-jobs
vercel dev
```

The page will be available at `http://localhost:3000`

## API Endpoints

The page uses Vercel serverless functions that connect directly to Zilliz:

- `GET /api/jobs/list` - List all jobs
- `GET /api/jobs/:job_id` - Get specific job
- `POST /api/jobs/create` - Create new job
- `POST /api/jobs/:job_id/update` - Update job (creates new version)
- `GET /api/jobs/:job_id/versions` - Get all versions
- `POST /api/jobs/:job_id/switch-version` - Switch current version
- `DELETE /api/jobs/:job_id/delete` - Delete a version

All endpoints are implemented in `api/jobs.py` as a Python serverless function.
- `GET /jobs/api/{job_id}` - Get specific job
- `POST /jobs/create` - Create new job
- `POST /jobs/{job_id}/update` - Update job
- `POST /jobs/{job_id}/switch-version` - Switch job version
- `DELETE /jobs/{job_id}/delete` - Delete job version

## Security Notes

⚠️ **No Authentication**: This page has no authentication. Anyone with the URL can access it.

For production use:
1. Add authentication (e.g., Vercel's password protection)
2. Restrict CORS origins on FastAPI
3. Add API key authentication to FastAPI endpoints
4. Use Vercel's access control features

## Troubleshooting

### CORS Errors

If you see CORS errors:
1. Check `CORS_ALLOWED_ORIGINS` on FastAPI server includes your Vercel URL
2. Verify `API_BASE_URL` is set correctly in Vercel
3. Check browser console for exact error message

### API Connection Failed

1. Verify FastAPI service is running and accessible
2. Check `API_BASE_URL` environment variable
3. Test API endpoint directly: `curl https://your-api.com/jobs/api/list`

### Version Switching Not Working

1. Check browser console for errors
2. Verify `/jobs/{job_id}/versions` endpoint returns data
3. Check network tab for failed requests

## File Structure

```
vercel-jobs/
├── index.html          # Main HTML file with all functionality
├── vercel.json         # Vercel configuration
├── package.json        # Node.js package file
└── README.md          # This file
```

## Customization

### Change API Base URL

Edit `index.html` and change:
```javascript
const API_BASE = window.API_BASE_URL || 'https://your-api.com';
```

### Add Custom Styling

Add CSS in the `<style>` section of `index.html` or link external stylesheet.

### Modify Features

All JavaScript is inline in `index.html`. Edit functions as needed:
- `loadJobsData()` - Load jobs list
- `loadJobForm()` - Load job editor
- `saveJob()` - Save job changes
- `createJob()` - Create new job
- `deleteJob()` - Delete job version

## Support

For issues or questions, check:
- FastAPI service logs
- Browser console (F12)
- Vercel deployment logs
- Network tab for API requests

