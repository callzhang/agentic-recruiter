# Boss Zhipin API Endpoints Documentation

This document describes all available API endpoints in the Boss Zhipin automation service.

## Base URL
```
http://127.0.0.1:5001
```

## Authentication
Most endpoints require the user to be logged in to Boss Zhipin. The service will automatically handle login verification and redirect to login page if needed.

---

## System Endpoints

### GET `/status`
Get the current service status and login state.

**Response:**
```json
{
  "status": "running",
  "logged_in": true,
  "timestamp": "2025-09-27T13:30:00.000Z",
  "notifications_count": 5
}
```

### GET `/notifications`
Get recent service notifications.

**Query Parameters:**
- `limit` (int, optional): Number of notifications to return (1-200, default: 20)

**Response:**
```json
{
  "notifications": [
    {
      "timestamp": "2025-09-27T13:30:00.000Z",
      "level": "info",
      "message": "Service started successfully"
    }
  ],
  "total": 5
}
```

### POST `/login`
Trigger login verification.

**Response:**
```json
{
  "success": true,
  "message": "登录成功",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### POST `/restart`
Soft restart the API service while keeping browser session.

**Response:**
```json
{
  "success": true,
  "message": "API服务已重启，浏览器会话保持",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

---

## Chat Management

### GET `/chat/candidates`
Get list of chat candidates.

**Query Parameters:**
- `limit` (int, optional): Number of candidates to return (1-100, default: 10)

**Response:**
```json
{
  "success": true,
  "candidates": [
    {
      "name": "张三",
      "position": "Python开发工程师",
      "company": "某科技公司",
      "chat_id": "12345"
    }
  ],
  "count": 1,
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### GET `/chat/dialogs`
Get list of chat dialogs/messages.

**Query Parameters:**
- `limit` (int, optional): Number of dialogs to return (1-100, default: 10)

**Response:**
```json
{
  "success": true,
  "messages": [
    {
      "chat_id": "12345",
      "last_message": "您好，我对这个职位很感兴趣",
      "timestamp": "2025-09-27T13:30:00.000Z"
    }
  ],
  "count": 1,
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### GET `/chat/{chat_id}/messages`
Get chat history for a specific conversation.

**Path Parameters:**
- `chat_id` (string): The chat/conversation ID

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "messages": [
    {
      "sender": "candidate",
      "content": "您好，我对这个职位很感兴趣",
      "timestamp": "2025-09-27T13:30:00.000Z"
    }
  ],
  "count": 1,
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### POST `/chat/{chat_id}/send`
Send a text message to a specific conversation.

**Path Parameters:**
- `chat_id` (string): The chat/conversation ID

**Request Body:**
```json
{
  "message": "您好，我对您的简历很感兴趣"
}
```

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "message": "您好，我对您的简历很感兴趣",
  "details": "消息发送成功",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### POST `/chat/{chat_id}/greet`
Send a greeting message to a candidate.

**Path Parameters:**
- `chat_id` (string): The chat/conversation ID

**Request Body:**
```json
{
  "message": "您好，我对您的简历很感兴趣，希望能进一步沟通。"
}
```

**Response:**
```json
{
  "success": true,
  "message": "打招呼成功",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

---

## Resume Management

### POST `/resume/request`
Request a resume from a candidate.

**Request Body:**
```json
{
  "chat_id": "12345"
}
```

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "already_sent": false,
  "details": "简历请求已发送",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### POST `/resume/check_full`
Check whether an attached resume is available.

**Request Body:**
```json
{
  "chat_id": "12345"
}
```

**Response:**
```json
{
  "success": true,
  "available": true,
  "details": "附件简历已可用"
}
```

### POST `/resume/view_full`
Retrieve the attached resume content.

**Request Body:**
```json
{
  "chat_id": "12345"
}
```

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "content": "简历内容...",
  "details": "简历查看成功",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### POST `/resume/online`
View online resume and capture content using various methods (WASM, canvas, screenshot).

**Request Body:**
```json
{
  "chat_id": "12345"
}
```

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "text": "Extracted text content",
  "html": "<html>...</html>",
  "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "images_base64": ["data:image/png;base64,..."],
  "data_url": "data:image/png;base64,...",
  "width": 1920,
  "height": 1080,
  "details": "简历内容提取成功",
  "error": null,
  "timestamp": "2025-09-27T13:30:00.000Z",
  "capture_method": "wasm"
}
```

---

## Candidate Management

### POST `/candidate/discard`
Discard a candidate by clicking the "not suitable" button.

**Request Body:**
```json
{
  "chat_id": "12345"
}
```

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "details": "候选人已标记为不合适",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### POST `/resume/accept`
Accept a candidate by clicking the "accept" button.

**Request Body:**
```json
{
  "chat_id": "12345"
}
```

**Response:**
```json
{
  "success": true,
  "chat_id": "12345",
  "details": "候选人已接受",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

---

## Recommendation System

### GET `/recommend/candidates`
Get list of recommended candidates.

**Query Parameters:**
- `limit` (int, optional): Number of candidates to return (1-100, default: 20)

**Response:**
```json
{
  "success": true,
  "candidates": [
    {
      "name": "李四",
      "position": "Java开发工程师",
      "experience": "3年",
      "education": "本科",
      "index": 0
    }
  ],
  "count": 1,
  "details": "成功获取 1 个推荐候选人",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### GET `/recommend/candidate/{index}`
View a specific recommended candidate's resume.

**Path Parameters:**
- `index` (int): The candidate index in the recommendation list

**Response:**
```json
{
  "success": true,
  "candidate": {
    "name": "李四",
    "position": "Java开发工程师",
    "resume_content": "简历内容...",
    "details": "候选人简历查看成功"
  },
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

---

## Search Configuration

### GET `/search`
Get search parameter preview for job search configuration.

**Query Parameters:**
- `city` (string, optional): City name (default: "北京")
- `job_type` (string, optional): Job type (default: "全职")
- `salary` (string, optional): Salary range (default: "不限")
- `experience` (string, optional): Experience level (default: "不限")
- `degree` (string, optional): Education degree (default: "不限")
- `industry` (string, optional): Industry (default: "不限")

**Response:**
```json
{
  "success": true,
  "preview": {
    "base": "https://www.zhipin.com/web/geek/job?",
    "params": {
      "city": "101010100",
      "jobType": "1",
      "salary": "0",
      "experience": "0",
      "degree": "0",
      "industry": "0"
    }
  },
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

---

## Debug Endpoints

### GET `/debug/page`
Get current page content for debugging.

**Response:**
```json
{
  "success": true,
  "page_info": {
    "url": "https://www.zhipin.com/web/chat/index",
    "title": "Boss直聘",
    "content": "<html>...</html>",
    "content_length": 50000,
    "screenshot": null,
    "cookies": [],
    "local_storage": {},
    "session_storage": {}
  },
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

### GET `/debug/cache`
Get event cache statistics.

**Response:**
```json
{
  "success": true,
  "cache_stats": {
    "total_entries": 10,
    "cache_hits": 5,
    "cache_misses": 3,
    "ttl_expired": 2
  },
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

---

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "success": false,
  "error": "Error message",
  "details": "Detailed error information",
  "timestamp": "2025-09-27T13:30:00.000Z"
}
```

Common error scenarios:
- **401 Unauthorized**: User not logged in
- **404 Not Found**: Chat ID or resource not found
- **500 Internal Server Error**: Service or browser session issues

---

## Usage Examples

### Python Client Example
```python
import requests

# Get candidates
response = requests.get('http://127.0.0.1:5001/chat/candidates?limit=5')
candidates = response.json()

# Send a message
response = requests.post('http://127.0.0.1:5001/chat/12345/send', 
                        json={'message': 'Hello!'})

# View online resume
response = requests.post('http://127.0.0.1:5001/resume/online',
                        json={'chat_id': '12345'})
resume_data = response.json()
```

### cURL Examples
```bash
# Get service status
curl http://127.0.0.1:5001/status

# Get candidates
curl "http://127.0.0.1:5001/chat/candidates?limit=10"

# Send message
curl -X POST http://127.0.0.1:5001/chat/12345/send \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'

# View online resume
curl -X POST http://127.0.0.1:5001/resume/online \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "12345"}'
```

---

## Notes

1. **Authentication**: Most endpoints require the user to be logged in to Boss Zhipin. The service handles login verification automatically.

2. **Rate Limiting**: Be mindful of API usage to avoid overwhelming the Boss Zhipin website.

3. **Browser Session**: The service maintains a persistent browser session. Use the `/restart` endpoint if you encounter issues.

4. **Resume Capture**: The `/resume/online` endpoint uses advanced capture methods including WASM hooks, canvas extraction, and screenshot fallbacks.

5. **Error Handling**: All endpoints return structured JSON responses with success indicators and detailed error information.



