"""
Vercel serverless function for jobs API
Connects directly to Zilliz using environment variables
"""

import os
import sys
import json
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import Milvus client with error handling
try:
    from pymilvus import MilvusClient
except ImportError as e:
    print(f"ERROR: Failed to import MilvusClient: {e}", file=sys.stderr)
    raise

# Configuration from environment variables
ZILLIZ_ENDPOINT = os.environ.get('ZILLIZ_ENDPOINT')
ZILLIZ_TOKEN = os.environ.get('ZILLIZ_TOKEN', '')
ZILLIZ_USER = os.environ.get('ZILLIZ_USER')
ZILLIZ_PASSWORD = os.environ.get('ZILLIZ_PASSWORD')
COLLECTION_NAME = os.environ.get('ZILLIZ_JOB_COLLECTION_NAME', 'CN_jobs')
EMBEDDING_DIM = int(os.environ.get('ZILLIZ_EMBEDDING_DIM', '1536'))

# Initialize Zilliz client
_client = None

def get_client():
    """Get or create Zilliz client"""
    global _client
    if _client is None:
        missing = []
        if not ZILLIZ_ENDPOINT:
            missing.append('ZILLIZ_ENDPOINT')
        if not ZILLIZ_USER:
            missing.append('ZILLIZ_USER')
        if not ZILLIZ_PASSWORD:
            missing.append('ZILLIZ_PASSWORD')
        
        if missing:
            raise ValueError(f'Zilliz credentials not configured. Missing: {", ".join(missing)}. Please set these environment variables in Vercel.')
        
        try:
            _client = MilvusClient(
                uri=ZILLIZ_ENDPOINT,
                token=ZILLIZ_TOKEN,
                user=ZILLIZ_USER,
                password=ZILLIZ_PASSWORD,
                secure=ZILLIZ_ENDPOINT.startswith('https://'),
            )
        except Exception as e:
            raise ValueError(f'Failed to connect to Zilliz: {str(e)}')
    return _client

def get_base_job_id(job_id: str) -> str:
    """Extract base job_id by removing version suffix"""
    return re.sub(r'_v\d+$', '', job_id)

def get_all_jobs() -> List[Dict[str, Any]]:
    """Get all jobs (current versions only)"""
    client = get_client()
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter='current == true',
        output_fields=[
            'job_id', 'position', 'background', 'description', 'responsibilities',
            'requirements', 'target_profile', 'keywords', 'drill_down_questions',
            'candidate_filters', 'version', 'current', 'created_at', 'updated_at'
        ],
        limit=1000
    )
    
    jobs = []
    for job in results:
        job_dict = {k: v for k, v in job.items() if v is not None and v != ''}
        if 'job_id' in job_dict:
            job_dict['base_job_id'] = get_base_job_id(job_dict['job_id'])
        jobs.append(job_dict)
    
    jobs.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
    return jobs

def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Get specific job by job_id (can be base_job_id or versioned_job_id)
    If versioned_job_id is provided, returns that specific version.
    If base_job_id is provided, returns the current version.
    """
    client = get_client()
    
    # Check if job_id is already versioned (contains _v followed by digits)
    if re.match(r'.+_v\d+$', job_id):
        # It's a versioned job_id, fetch that specific version
        versioned_job_id = job_id
        base_job_id = get_base_job_id(job_id)
    else:
        # It's a base_job_id, fetch current version
        base_job_id = job_id
        versioned_job_id = None
    
    # Build filter
    if versioned_job_id:
        # Fetch specific version
        filter_expr = f'job_id == "{versioned_job_id}"'
    else:
        # Fetch current version
        filter_expr = f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w" && current == true'
    
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=filter_expr,
        output_fields=[
            'job_id', 'position', 'background', 'description', 'responsibilities',
            'requirements', 'target_profile', 'keywords', 'drill_down_questions',
            'candidate_filters', 'version', 'current', 'created_at', 'updated_at'
        ],
        limit=100
    )
    
    for job in results:
        job_id_value = job.get('job_id', '')
        if versioned_job_id:
            # Exact match for versioned job_id
            if job_id_value == versioned_job_id:
                job_dict = {k: v for k, v in job.items() if v is not None and v != ''}
                job_dict['base_job_id'] = base_job_id
                return job_dict
        else:
            # Match any version of base_job_id (but filter already ensures current==true)
            if job_id_value.startswith(f'{base_job_id}_v') and re.match(rf'^{re.escape(base_job_id)}_v\d+$', job_id_value):
                job_dict = {k: v for k, v in job.items() if v is not None and v != ''}
                job_dict['base_job_id'] = base_job_id
                return job_dict
    
    return None

def insert_job(**job_data) -> bool:
    """Insert a new job"""
    client = get_client()
    job_id = job_data.get('job_id') or job_data.get('id', '')
    if not job_id:
        raise ValueError('job_id is required')
    base_job_id = get_base_job_id(job_id)
    versioned_job_id = f'{base_job_id}_v1'
    
    now = datetime.now().isoformat()
    drill_down_questions = (job_data.get('drill_down_questions', '') or '')[:30000]
    
    insert_data = {
        'job_id': versioned_job_id,
        'position': job_data['position'],
        'background': job_data.get('background', '') or '',
        'description': job_data.get('description', '') or '',
        'responsibilities': job_data.get('responsibilities', '') or '',
        'requirements': job_data.get('requirements', '') or '',
        'target_profile': job_data.get('target_profile', '') or '',
        'keywords': job_data.get('keywords', {'positive': [], 'negative': []}),
        'drill_down_questions': drill_down_questions,
        'candidate_filters': job_data.get('candidate_filters'),
        'job_embedding': [0.0] * EMBEDDING_DIM,
        'version': 1,
        'current': True,
        'created_at': now,
        'updated_at': now,
    }
    
    client.insert(collection_name=COLLECTION_NAME, data=[insert_data])
    return True

def update_job(job_id: str, **job_data) -> bool:
    """Update job (creates new version)"""
    client = get_client()
    base_job_id = get_base_job_id(job_id)
    
    # Get current job
    current_job = get_job_by_id(base_job_id)
    if not current_job:
        return False
    
    # Get all versions
    all_versions = get_job_versions(base_job_id)
    max_version = max([v.get('version', 0) for v in all_versions], default=0)
    next_version = max_version + 1
    new_versioned_job_id = f'{base_job_id}_v{next_version}'
    
    # Set old version's current=False (use partial_update to only update the current field)
    client.upsert(
        collection_name=COLLECTION_NAME,
        data=[{'job_id': current_job['job_id'], 'current': False}],
        partial_update=True
    )
    
    # Create new version
    now = datetime.now().isoformat()
    drill_down_questions = (job_data.get('drill_down_questions', current_job.get('drill_down_questions', '')) or '')[:30000]
    
    new_version_data = {
        'job_id': new_versioned_job_id,
        'position': job_data.get('position', current_job.get('position', '')),
        'background': job_data.get('background', current_job.get('background', '')) or '',
        'description': job_data.get('description', current_job.get('description', '')) or '',
        'responsibilities': job_data.get('responsibilities', current_job.get('responsibilities', '')) or '',
        'requirements': job_data.get('requirements', current_job.get('requirements', '')) or '',
        'target_profile': job_data.get('target_profile', current_job.get('target_profile', '')) or '',
        'keywords': job_data.get('keywords', current_job.get('keywords', {'positive': [], 'negative': []})),
        'drill_down_questions': drill_down_questions,
        'candidate_filters': job_data.get('candidate_filters', current_job.get('candidate_filters')),
        'job_embedding': [0.0] * EMBEDDING_DIM,
        'version': next_version,
        'current': True,
        'created_at': current_job.get('created_at', now),
        'updated_at': now,
    }
    
    client.insert(collection_name=COLLECTION_NAME, data=[new_version_data])
    return True

def get_job_versions(base_job_id: str) -> List[Dict[str, Any]]:
    """Get all versions of a job"""
    client = get_client()
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w"',
        output_fields=[
            'job_id', 'position', 'version', 'current', 'created_at', 'updated_at'
        ],
        limit=1000
    )
    
    versions = [
        {k: v for k, v in job.items() if v is not None and v != ''}
        for job in results
        if job.get('job_id', '').startswith(f'{base_job_id}_v') and re.match(rf'^{re.escape(base_job_id)}_v\d+$', job.get('job_id', ''))
    ]
    
    versions.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return versions

def switch_job_version(base_job_id: str, version: int) -> bool:
    """Switch the current version"""
    client = get_client()
    all_versions = get_job_versions(base_job_id)
    
    target_job_id = f'{base_job_id}_v{version}'
    target_version = next((v for v in all_versions if v.get('job_id') == target_job_id), None)
    
    if not target_version:
        return False
    
    # Get full job data for all versions to ensure we have all required fields
    # Query all versions to get complete data
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'job_id >= "{base_job_id}_v" && job_id < "{base_job_id}_w"',
        output_fields=['job_id', 'position', 'current'],
        limit=1000
    )
    
    # Create a map of job_id to position for quick lookup
    job_positions = {job.get('job_id'): job.get('position', '') for job in results if job.get('job_id')}
    
    # Set all versions' current=False (include position to avoid DataNotMatchException)
    for v in all_versions:
        if v.get('job_id'):
            job_position = job_positions.get(v['job_id'], '')
            if job_position:  # Only update if we have the position
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    data=[{'job_id': v['job_id'], 'position': job_position, 'current': False}],
                    partial_update=True
                )
    
    # Set target version's current=True (include position to avoid DataNotMatchException)
    target_position = job_positions.get(target_job_id, '')
    if target_position:
        client.upsert(
            collection_name=COLLECTION_NAME,
            data=[{'job_id': target_job_id, 'position': target_position, 'current': True}],
            partial_update=True
        )
    else:
        # Fallback: query the specific job to get its position
        target_job = get_job_by_id(target_job_id)
        if target_job and target_job.get('position'):
            client.upsert(
                collection_name=COLLECTION_NAME,
                data=[{'job_id': target_job_id, 'position': target_job['position'], 'current': True}],
                partial_update=True
            )
        else:
            return False
    
    return True

def delete_job_version(base_job_id: str, version: int) -> bool:
    """Delete a specific version"""
    client = get_client()
    versioned_job_id = f'{base_job_id}_v{version}'
    client.delete(collection_name=COLLECTION_NAME, filter=f'job_id == "{versioned_job_id}"')
    return True

# Vercel handler - must inherit from BaseHTTPRequestHandler
# See: https://vercel.com/docs/functions/runtimes/python
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote

class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler - inherits from BaseHTTPRequestHandler"""
    
    def _send_json_response(self, status_code, data):
        """Helper to send JSON response"""
        response_body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)
    
    def _get_query_params(self):
        """Extract query parameters from path"""
        if '?' in self.path:
            query_string = self.path.split('?', 1)[1]
            return parse_qs(query_string)
        return {}
    
    def _get_body(self):
        """Read and parse request body"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        
        body_bytes = self.rfile.read(content_length)
        try:
            body_str = body_bytes.decode('utf-8')
            return json.loads(body_str) if body_str else {}
        except:
            return {}
    
    def _extract_job_id(self, path, query):
        """Extract job_id from path or query"""
        # Check query params (parse_qs returns lists)
        if 'job_id' in query:
            job_id_val = query['job_id']
            if isinstance(job_id_val, list) and job_id_val:
                # Query params may be URL-encoded
                return unquote(job_id_val[0])
            return unquote(job_id_val) if job_id_val else None
        # Try to extract from path: /api/jobs/{job_id}/...
        # Path is already URL-decoded in do_GET/do_POST/do_DELETE
        parts = path.split('/')
        if len(parts) >= 4 and parts[2] == 'jobs':
            return parts[3]
        return None
    
    def _handle_route(self, method, path, query, body):
        """Handle routing logic"""
        try:
            print(f"DEBUG: Method={method}, Path={path}, Query={query}", file=sys.stderr)
            
            # Route handling
            if method == 'GET' and (path.endswith('/list') or path == '/api/jobs' or '/list' in path):
                # GET /api/jobs/list
                try:
                    jobs = get_all_jobs()
                    self._send_json_response(200, {'success': True, 'data': jobs})
                    return
                except Exception as e:
                    error_msg = str(e)
                    print(f"Error in get_all_jobs: {error_msg}", file=sys.stderr)
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    self._send_json_response(500, {'success': False, 'error': error_msg})
                    return
            
            elif method == 'POST' and path.endswith('/create'):
                # POST /api/jobs/create
                if not body.get('job_id') or not body.get('position'):
                    self._send_json_response(400, {'success': False, 'error': 'job_id and position are required'})
                    return
                
                base_job_id = get_base_job_id(body['job_id'])
                existing = get_job_by_id(base_job_id)
                if existing:
                    self._send_json_response(400, {'success': False, 'error': f"Job ID '{base_job_id}' already exists"})
                    return
                
                if insert_job(**body):
                    new_job = get_job_by_id(base_job_id)
                    self._send_json_response(200, {'success': True, 'data': new_job})
                else:
                    self._send_json_response(500, {'success': False, 'error': 'Failed to create job'})
                return
            
            elif method == 'GET' and '/versions' in path:
                # GET /api/jobs/[job_id]/versions
                job_id = self._extract_job_id(path, query)
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                versions = get_job_versions(base_job_id)
                self._send_json_response(200, {'success': True, 'data': versions})
                return
            
            elif method == 'POST' and '/switch-version' in path:
                # POST /api/jobs/[job_id]/switch-version
                job_id = self._extract_job_id(path, query)
                version = body.get('version')
                
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                if version is None:
                    self._send_json_response(400, {'success': False, 'error': 'version is required'})
                    return
                
                try:
                    version = int(version)
                except (ValueError, TypeError):
                    self._send_json_response(400, {'success': False, 'error': 'version must be a number'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                if switch_job_version(base_job_id, version):
                    updated_job = get_job_by_id(base_job_id)
                    self._send_json_response(200, {'success': True, 'data': updated_job})
                else:
                    self._send_json_response(404, {'success': False, 'error': f'Version {version} not found'})
                return
            
            elif method == 'DELETE' and '/delete' in path:
                # DELETE /api/jobs/[job_id]/delete
                job_id = self._extract_job_id(path, query)
                version = body.get('version')
                
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                if version is None:
                    self._send_json_response(400, {'success': False, 'error': 'version is required'})
                    return
                
                try:
                    version = int(version)
                except (ValueError, TypeError):
                    self._send_json_response(400, {'success': False, 'error': 'version must be a number'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                all_versions = get_job_versions(base_job_id)
                
                # Allow deletion even if only 1 version left (frontend handles confirmation)
                # No need to prevent it at API level
                
                # Check if the version to delete exists and if it's the current version
                version_to_delete = next((v for v in all_versions if v.get('version') == version), None)
                if not version_to_delete:
                    self._send_json_response(404, {'success': False, 'error': f'Version v{version} not found'})
                    return
                
                is_deleting_current = version_to_delete.get('current', False)
                
                if delete_job_version(base_job_id, version):
                    remaining_versions = get_job_versions(base_job_id)
                    if remaining_versions:
                        # Always ensure there's a current version after deletion
                        current_version = next((v for v in remaining_versions if v.get('current')), None)
                        
                        if not current_version or is_deleting_current:
                            # No current version found, or we deleted the current version
                            if is_deleting_current:
                                # If we deleted the current version N, try to set N-1 as current
                                # If N-1 doesn't exist, set the highest remaining version
                                version_minus_one = next((v for v in remaining_versions if v.get('version') == version - 1), None)
                                if version_minus_one:
                                    # Set N-1 as current
                                    switch_job_version(base_job_id, version - 1)
                                else:
                                    # N-1 doesn't exist, set the highest remaining version as current
                                    remaining_versions_sorted = sorted(remaining_versions, key=lambda v: v.get('version', 0), reverse=True)
                                    if remaining_versions_sorted:
                                        switch_job_version(base_job_id, remaining_versions_sorted[0].get('version'))
                            else:
                                # We deleted a non-current version, but there's no current version
                                # Set the highest remaining version as current
                                remaining_versions_sorted = sorted(remaining_versions, key=lambda v: v.get('version', 0), reverse=True)
                                if remaining_versions_sorted:
                                    switch_job_version(base_job_id, remaining_versions_sorted[0].get('version'))
                        
                        self._send_json_response(200, {'success': True, 'message': f'Version v{version} deleted'})
                    else:
                        # Last version deleted - job is completely removed
                        self._send_json_response(200, {'success': True, 'message': 'Job deleted (last version removed)'})
                else:
                    self._send_json_response(500, {'success': False, 'error': 'Failed to delete version'})
                return
            
            elif method == 'POST' and '/update' in path:
                # POST /api/jobs/[job_id]/update
                job_id = self._extract_job_id(path, query)
                
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                if not body.get('position'):
                    self._send_json_response(400, {'success': False, 'error': 'position is required'})
                    return
                
                base_job_id = get_base_job_id(job_id)
                new_base_job_id = get_base_job_id(body.get('job_id', job_id))
                
                existing = get_job_by_id(base_job_id)
                if not existing:
                    self._send_json_response(404, {'success': False, 'error': 'Job not found'})
                    return
                
                if new_base_job_id != base_job_id:
                    conflict = get_job_by_id(new_base_job_id)
                    if conflict:
                        self._send_json_response(400, {'success': False, 'error': f"Job ID '{new_base_job_id}' already exists"})
                        return
                
                # Remove job_id from body to avoid conflict with positional argument
                job_data = {k: v for k, v in body.items() if k != 'job_id'}
                if update_job(base_job_id, **job_data):
                    updated_job = get_job_by_id(new_base_job_id)
                    self._send_json_response(200, {'success': True, 'data': updated_job})
                else:
                    self._send_json_response(500, {'success': False, 'error': 'Failed to update job'})
                return
            
            else:
                # GET /api/jobs/[job_id] - Get specific job
                job_id = self._extract_job_id(path, query)
                if not job_id:
                    self._send_json_response(400, {'success': False, 'error': 'job_id is required'})
                    return
                
                job = get_job_by_id(job_id)
                if not job:
                    self._send_json_response(404, {'success': False, 'error': 'Job not found'})
                    return
                
                self._send_json_response(200, {'success': True, 'data': job})
                return
        
        except Exception as e:
            import traceback
            error_msg = str(e)
            error_type = type(e).__name__
            traceback_str = traceback.format_exc()
            
            print(f"ERROR: {error_type}: {error_msg}", file=sys.stderr)
            print(traceback_str, file=sys.stderr)
            sys.stderr.flush()
            
            self._send_json_response(500, {
                'success': False, 
                'error': error_msg,
                'type': error_type
            })
    
    def do_GET(self):
        """Handle GET requests"""
        path = unquote(self.path.split('?')[0])
        query = self._get_query_params()
        body = {}
        self._handle_route('GET', path, query, body)
    
    def do_POST(self):
        """Handle POST requests"""
        path = unquote(self.path.split('?')[0])
        query = self._get_query_params()
        body = self._get_body()
        self._handle_route('POST', path, query, body)
    
    def do_DELETE(self):
        """Handle DELETE requests"""
        path = unquote(self.path.split('?')[0])
        query = self._get_query_params()
        body = self._get_body()
        self._handle_route('DELETE', path, query, body)
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
