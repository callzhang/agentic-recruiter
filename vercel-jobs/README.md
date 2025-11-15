# Jobs Editor - Vercel Deployment

Full-featured standalone jobs editor page for Boss Zhipin bot, deployed on Vercel.

## Features

- ✅ Create, update, and delete jobs
- ✅ Version management (view, switch, delete versions)
- ✅ Keywords editor (positive/negative tags)
- ✅ Candidate filters (JSON editor with validation)
- ✅ Drill down questions
- ✅ All job description fields

## Setup

### 1. Configure API Base URL

The page needs to know where your FastAPI service is running. Set it in one of these ways:

**Option A: Environment Variable (Recommended)**
```bash
# In Vercel dashboard, add environment variable:
API_BASE_URL=https://your-fastapi-service.com
```

**Option B: Edit index.html**
```javascript
// Change this line in index.html:
const API_BASE = 'https://your-fastapi-service.com';
```

### 2. Configure CORS on FastAPI

Add CORS middleware to allow requests from Vercel:

```bash
# Set environment variable on FastAPI server:
export CORS_ALLOWED_ORIGINS="https://your-vercel-app.vercel.app,https://your-custom-domain.com"
```

Or edit `boss_service.py` to allow all origins (development only):
- The CORS middleware is already configured
- By default, it allows all origins (`*`)
- For production, set `CORS_ALLOWED_ORIGINS` environment variable

### 3. Deploy to Vercel

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

### 4. Set Environment Variables in Vercel

1. Go to Vercel Dashboard → Your Project → Settings → Environment Variables
2. Add:
   - `API_BASE_URL`: Your FastAPI service URL (e.g., `https://your-service.com`)

## Local Development

```bash
# Install Vercel CLI
npm install -g vercel

# Run local dev server
cd vercel-jobs
vercel dev
```

The page will be available at `http://localhost:3000`

## API Endpoints Used

The page calls these FastAPI endpoints:

- `GET /jobs/api/list` - List all jobs
- `GET /jobs/{job_id}/versions` - Get job versions
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

