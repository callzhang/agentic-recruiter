#!/usr/bin/env python3
"""Vercel serverless function for candidate detail page.
Displays candidate information in readonly mode.
Updated: 2025-12-24 - Added feedback buttons support
"""

import os
import sys
import json
from urllib.parse import unquote
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler
from datetime import datetime
from typing import Any, Dict, Optional
from pymilvus import MilvusClient

# --- JSON safety utilities (from stats.py) ----------------------------------------

_KEY_TYPES = (str, int, float, bool, type(None))


def _safe_key(key: Any) -> Any:
    """Convert mapping keys to JSON-safe primitives (str/int/float/bool/None)."""
    if isinstance(key, _KEY_TYPES):
        return key
    if isinstance(key, bytes):
        try:
            return key.decode("utf-8")
        except Exception:
            return key.hex()
    return str(key)


def _json_safe(obj: Any) -> Any:
    """Recursively make an object JSON-serializable and safe for Vercel."""
    if isinstance(obj, dict):
        return { _safe_key(k): _json_safe(v) for k, v in obj.items() }
    if isinstance(obj, (list, tuple, set)):
        return [ _json_safe(v) for v in obj ]
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return obj.hex()
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    return obj

# --- End JSON safety utilities ------------------------------------------------------------

def _env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read env var as string, stripping whitespace and optional surrounding quotes."""
    value = os.environ.get(name, default)
    if value is None:
        return None
    s = str(value).strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1]
    return s


# Configuration from environment variables
ZILLIZ_ENDPOINT = _env_str("ZILLIZ_ENDPOINT")
ZILLIZ_TOKEN = _env_str("ZILLIZ_TOKEN", "") or ""
ZILLIZ_USER = _env_str("ZILLIZ_USER")
ZILLIZ_PASSWORD = _env_str("ZILLIZ_PASSWORD")
CANDIDATE_COLLECTION_NAME = _env_str("ZILLIZ_CANDIDATE_COLLECTION_NAME", "CN_candidates") or "CN_candidates"

# Initialize Zilliz client
_candidate_client = None

def _create_candidate_client() -> MilvusClient:
    """Create and return a MilvusClient instance."""
    missing = []
    if not ZILLIZ_ENDPOINT:
        missing.append('ZILLIZ_ENDPOINT')
    if not ZILLIZ_USER:
        missing.append('ZILLIZ_USER')
    if not ZILLIZ_PASSWORD:
        missing.append('ZILLIZ_PASSWORD')
    
    if missing:
        raise RuntimeError(f'Zilliz credentials not configured. Missing: {", ".join(missing)}. Please set these environment variables in Vercel.')
    
    token_value = ZILLIZ_TOKEN if (ZILLIZ_TOKEN and ZILLIZ_TOKEN.strip()) else None
    
    client_kwargs = {
        'uri': ZILLIZ_ENDPOINT,
        'user': ZILLIZ_USER,
        'password': ZILLIZ_PASSWORD,
        'secure': ZILLIZ_ENDPOINT.startswith('https://'),
    }
    if token_value:
        client_kwargs['token'] = token_value
    
    client = MilvusClient(**client_kwargs)
    client.list_collections()  # Verify connection
    return client


def get_candidate_client() -> MilvusClient:
    """Get candidate collection Zilliz client."""
    global _candidate_client
    if _candidate_client is None:
        _candidate_client = _create_candidate_client()
    return _candidate_client

# Jinja2 for template rendering
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Setup Jinja2 environment
# Templates are in vercel/templates directory (copied from web/templates)
template_dir = os.path.join(os.path.dirname(__file__), '../templates')
env = Environment(
    loader=FileSystemLoader([template_dir, os.path.join(template_dir, 'partials')]),
    autoescape=select_autoescape(['html', 'xml'])
)


def _send_html(handler_obj, status_code, html_content):
    """Send HTML response."""
    body = html_content.encode('utf-8')
    handler_obj.send_response(status_code)
    handler_obj.send_header('Content-type', 'text/html; charset=utf-8')
    handler_obj.send_header('Access-Control-Allow-Origin', '*')
    handler_obj.send_header('Content-Length', str(len(body)))
    handler_obj.end_headers()
    handler_obj.wfile.write(body)


def _extract_candidate_id(path: str) -> str:
    """Extract candidate_id from URL path.
    
    Expected format: /api/candidate/{candidate_id} or /candidate/{candidate_id}
    """
    # Remove query string if present
    path = path.split('?')[0]
    
    # Remove leading slash and split
    parts = path.lstrip('/').split('/')
    
    # Find candidate_id - it should be after 'candidate' or 'api/candidate'
    if 'candidate' in parts:
        idx = parts.index('candidate')
        if idx + 1 < len(parts):
            return unquote(parts[idx + 1])
    
    # Fallback: assume last part is candidate_id
    if parts:
        return unquote(parts[-1])
    
    return None


def get_candidate_by_id(candidate_id: str) -> dict:
    """Get candidate by candidate_id from Zilliz."""
    if not candidate_id:
        return None
    
    client = get_candidate_client()
    
    # Query candidate by ID
    # Use all readable fields that exist in the collection schema
    # Note: job_id, created_at, viewed, and score are not in the schema
    fields = [
        "candidate_id", "name", "job_applied", "stage", "analysis", 
        "resume_text", "full_resume", "generated_message", "last_message",
        "chat_id", "conversation_id", "updated_at",
        "metadata", "notified"
    ]
    
    results = client.query(
        collection_name=CANDIDATE_COLLECTION_NAME,
        filter=f"candidate_id == '{candidate_id}'",
        output_fields=fields,
        limit=1,
    )
    
    if not results:
        return None
    
    # Clean and return first result
    candidate = _json_safe(results[0])
    
    # Parse analysis if it's a JSON string
    if "analysis" in candidate and isinstance(candidate["analysis"], str):
        try:
            candidate["analysis"] = json.loads(candidate["analysis"])
        except:
            pass  # Keep as string if parsing fails
    
    # Parse metadata if it's a JSON string
    if "metadata" in candidate and isinstance(candidate.get("metadata"), str):
        try:
            candidate["metadata"] = json.loads(candidate["metadata"])
        except:
            pass  # Keep as string if parsing fails
    
    # Add computed fields that might be expected by template
    # score is derived from analysis, not stored directly
    if "analysis" in candidate and isinstance(candidate["analysis"], dict):
        candidate["score"] = candidate["analysis"].get("overall")
    
    # Set default values for fields that don't exist in schema but might be expected
    if "viewed" not in candidate:
        candidate["viewed"] = None
    if "created_at" not in candidate:
        candidate["created_at"] = None
    
    return candidate


def render_candidate_detail(candidate: dict, *, allow_optimization_feedback: bool) -> str:
    """Render candidate detail template in readonly mode."""
    # Create a copy to avoid modifying original
    candidate_copy = dict(candidate) if candidate else {}
    
    # Prepare template context
    analysis = candidate_copy.pop("analysis", {}) if candidate_copy else {}
    generated_message = candidate_copy.pop("generated_message", '') if candidate_copy else ''
    resume_text = candidate_copy.pop("resume_text", '') if candidate_copy else ''
    full_resume = candidate_copy.pop("full_resume", '') if candidate_copy else ''
    
    # Get score from analysis if available
    if candidate_copy and not candidate_copy.get("score"):
        candidate_copy['score'] = analysis.get("overall") if isinstance(analysis, dict) else None
    
    # Create a mock request object for template compatibility
    class MockRequest:
        url = type('obj', (object,), {'path': '/candidate/' + (candidate_copy.get('candidate_id', '') if candidate_copy else '')})()
    
    # Load candidate detail partial
    detail_template = env.get_template("partials/candidate_detail.html")
    
    # Render candidate detail partial with readonly mode
    detail_html = detail_template.render(
        candidate=candidate_copy or {},
        analysis=analysis,
        generated_message=generated_message,
        resume_text=resume_text,
        full_resume=full_resume,
        view_mode="readonly",
        allow_optimization_feedback=bool(allow_optimization_feedback),
        request=MockRequest(),
    )
    
    # Create standalone HTML document (simpler than extending base.html)
    candidate_name = candidate_copy.get('name', '未知') if candidate_copy else '未知'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>候选人详情 - {candidate_name}</title>
    
    <!-- Favicon -->
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    
    <!-- TailwindCSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- HTMX -->
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    
    <!-- Alpine.js -->
    <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
    
    <!-- Custom CSS -->
    <style>
        body {{ background-color: #f9fafb; }}
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <!-- Navigation bar -->
    <nav class="bg-white shadow-lg sticky top-0 z-50">
        <div class="container mx-auto px-4">
            <div class="flex justify-between items-center py-4">
                <div class="flex items-center space-x-4">
                    <a href="/" class="text-2xl font-bold text-blue-600">🤖 BOSS招聘助手</a>
                </div>
                <div class="text-sm text-gray-600">只读模式</div>
            </div>
        </div>
    </nav>
    
    <!-- Main content -->
    <main class="container mx-auto p-4">
        {detail_html}
    </main>
    
    <!-- Footer -->
    <footer class="bg-white border-t mt-12">
        <div class="container mx-auto px-4 py-6">
            <div class="text-center text-gray-600 text-sm">
                <p>BOSS招聘助手 | 候选人详情（只读模式）</p>
            </div>
        </div>
    </footer>
</body>
</html>"""


class handler(BaseHTTPRequestHandler):
    """Vercel entrypoint for candidate detail page."""
    
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        query_string = self.path.split('?', 1)[1] if '?' in self.path else ''
        query = parse_qs(query_string) if query_string else {}
        
        try:
            # Extract candidate_id from path
            candidate_id = _extract_candidate_id(path)
            
            if not candidate_id:
                _send_html(self, 400, '<html><body><h1>400 Bad Request</h1><p>Missing candidate_id</p></body></html>')
                return
            
            # Get candidate from Zilliz
            candidate = get_candidate_by_id(candidate_id)
            
            if not candidate:
                _send_html(self, 404, f'<html><body><h1>404 Not Found</h1><p>未找到候选人: {candidate_id}</p></body></html>')
                return
            
            # Render template
            context = (query.get('context', [''])[0] or '').strip().lower()
            # Allow feedback in all contexts, especially 'optimize' where it is critical
            allow_feedback = True
            html_content = render_candidate_detail(candidate, allow_optimization_feedback=allow_feedback)
            _send_html(self, 200, html_content)
            
        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}"
            error_trace = traceback.format_exc()
            print(f"ERROR: {error_msg}", file=sys.stderr)
            print(error_trace, file=sys.stderr)
            sys.stderr.flush()
            
            _send_html(self, 500, f'<html><body><h1>500 Internal Server Error</h1><p>{error_msg}</p></body></html>')
