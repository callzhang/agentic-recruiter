# 岗位描述编辑器 - 独立页面部署指南

## 概述

岗位描述编辑器 (`/jobs/public`) 是一个简化的独立页面，允许非HR管理人员更新岗位描述，无需访问完整的HR管理系统。

## 访问方式

### 本地访问
```
http://localhost:5001/jobs/public?token=YOUR_TOKEN
```

### 通过 Cloudflare Tunnel 访问
```
https://your-tunnel-url.trycloudflare.com/jobs/public?token=YOUR_TOKEN
```

## 配置 Token

### 开发环境
默认情况下，开发环境允许无 token 访问（仅当 `PUBLIC_JOBS_TOKEN` 未设置或为默认值时）。

### 生产环境
设置环境变量：
```bash
export PUBLIC_JOBS_TOKEN="your-secure-token-here"
```

或在 `config/secrets.yaml` 中添加：
```yaml
public_jobs:
  token: "your-secure-token-here"
```

然后修改 `web/routes/jobs_public.py` 中的 `PUBLIC_JOBS_TOKEN` 读取逻辑。

## 功能限制

公共编辑器**仅允许编辑以下字段**：
- 岗位名称 (position)
- 公司背景 (background)
- 主要职责 (responsibilities)
- 任职要求 (requirements)
- 岗位概述 (description)
- 理想人选 (target_profile)

**不允许编辑**：
- 关键词 (keywords)
- 候选人筛选条件 (candidate_filters)
- 追问问题 (drill_down_questions)
- 版本管理

## 部署选项

### 选项 1: 保持在同一 FastAPI 服务中（推荐）

**优点**：
- ✅ 无需额外部署
- ✅ 共享同一 API
- ✅ 简单易维护
- ✅ 自动版本控制

**缺点**：
- ❌ 需要 FastAPI 服务运行
- ❌ 与主服务共享资源

**适用场景**：
- 内部团队使用
- 已有 Cloudflare Tunnel 或 VPN 访问
- 不需要完全独立的部署

**部署步骤**：
1. 确保 FastAPI 服务运行
2. 配置 `PUBLIC_JOBS_TOKEN` 环境变量
3. 通过 Cloudflare Tunnel 或 VPN 暴露服务
4. 分享链接：`https://your-url/jobs/public?token=YOUR_TOKEN`

---

### 选项 2: Cloudflare Pages（静态站点）

**优点**：
- ✅ 免费 CDN 加速
- ✅ 全球边缘节点
- ✅ 独立于主服务
- ✅ 自动 HTTPS

**缺点**：
- ❌ 需要 CORS 配置
- ❌ 需要 API 认证
- ❌ 需要修改代码以支持跨域

**适用场景**：
- 需要全球访问
- 需要高可用性
- 主服务可能不稳定

**部署步骤**：

1. **创建静态 HTML 文件**（修改 `jobs_public.html`）：
   - 移除 Jinja2 模板语法
   - 使用 JavaScript 从 API 加载数据
   - 配置 API 基础 URL

2. **配置 CORS**（在 `boss_service.py` 中）：
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-pages.pages.dev"],  # Cloudflare Pages URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

3. **部署到 Cloudflare Pages**：
```bash
# 安装 Wrangler CLI
npm install -g wrangler

# 登录
wrangler login

# 创建项目
wrangler pages project create jobs-editor

# 部署
wrangler pages deploy web/templates/jobs_public.html --project-name=jobs-editor
```

4. **配置环境变量**：
   - 在 Cloudflare Pages 设置中添加 `API_BASE_URL`
   - 在 FastAPI 服务中配置 CORS

---

### 选项 3: Vercel（全栈应用）

**优点**：
- ✅ 免费服务器less 函数
- ✅ 优秀的开发体验
- ✅ 自动 HTTPS 和 CDN
- ✅ 支持 API 路由

**缺点**：
- ❌ 需要重构代码
- ❌ 需要配置 API 代理

**适用场景**：
- 需要服务器端逻辑
- 需要更好的开发体验
- 计划扩展功能

**部署步骤**：

1. **创建 `vercel.json`**：
```json
{
  "version": 2,
  "builds": [
    {
      "src": "api/proxy.js",
      "use": "@vercel/node"
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "/api/proxy.js"
    },
    {
      "src": "/(.*)",
      "dest": "/web/templates/jobs_public.html"
    }
  ]
}
```

2. **创建 API 代理** (`api/proxy.js`)：
```javascript
module.exports = async (req, res) => {
  const { method, url, headers, body } = req;
  const targetUrl = `http://your-fastapi-service:5001${url}`;
  
  const response = await fetch(targetUrl, {
    method,
    headers: {
      ...headers,
      'host': 'your-fastapi-service:5001'
    },
    body: body ? JSON.stringify(body) : undefined
  });
  
  const data = await response.json();
  res.json(data);
};
```

3. **部署**：
```bash
npm install -g vercel
vercel
```

---

## 推荐方案对比

| 方案 | 复杂度 | 成本 | 维护性 | 性能 | 推荐度 |
|------|--------|------|--------|------|--------|
| **选项 1: 同一服务** | ⭐ 低 | 免费 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **选项 2: Cloudflare Pages** | ⭐⭐ 中 | 免费 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **选项 3: Vercel** | ⭐⭐⭐ 高 | 免费 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

## 最终推荐

**对于大多数场景，推荐使用选项 1（同一 FastAPI 服务）**：

1. **最简单**：无需额外部署或配置
2. **最安全**：Token 认证，无需 CORS
3. **最易维护**：代码集中，更新方便
4. **功能完整**：自动版本控制，数据一致性

**如果主服务不稳定或需要全球访问，考虑选项 2（Cloudflare Pages）**。

## 安全建议

1. **使用强 Token**：
   ```bash
   # 生成随机 token
   openssl rand -hex 32
   ```

2. **定期轮换 Token**：
   - 每 3-6 个月更换一次
   - 通知所有用户更新链接

3. **限制访问**：
   - 使用 Cloudflare Access 或 VPN
   - 限制 IP 白名单（如果可能）

4. **监控访问**：
   - 记录所有访问日志
   - 设置异常访问告警

## 故障排查

### Token 无效
- 检查环境变量 `PUBLIC_JOBS_TOKEN` 是否正确设置
- 确认 URL 中的 token 参数正确

### CORS 错误（如果使用选项 2）
- 检查 FastAPI 服务的 CORS 配置
- 确认允许的源 URL 正确

### API 连接失败
- 检查 FastAPI 服务是否运行
- 确认 API URL 可访问
- 检查防火墙规则

## 更新日志

- **2024-12**: 初始版本，支持基本的岗位描述编辑功能

