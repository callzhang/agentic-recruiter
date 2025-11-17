#!/usr/bin/env python3
"""Fix architecture_v1 to set current=True"""

import sys
import time
from pathlib import Path

# Change to project root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import get_zilliz_config
from src.jobs_store import _client, _collection_name, get_job_versions, get_job_by_id

# Get Zilliz config
zilliz_conf = get_zilliz_config()

# Set up client
if not _client:
    print("ERROR: Zilliz client not available")
    sys.exit(1)

base_job_id = "architecture"
versioned_job_id = "architecture_v1"

print(f"Fixing job: {base_job_id}")
print("=" * 60)

# Get all versions
versions = get_job_versions(base_job_id)
print(f"Found {len(versions)} versions:")
for v in versions:
    print(f"  - {v.get('job_id')}: version {v.get('version')}, current={v.get('current')}")

# Check if v1 exists
v1 = next((v for v in versions if v.get('version') == 1), None)
if not v1:
    print(f"ERROR: Version 1 not found for {base_job_id}")
    sys.exit(1)

# Get the job to get its position
job = get_job_by_id(versioned_job_id)
if not job:
    # Try to get position from query
    results = _client.query(
        collection_name=_collection_name,
        filter=f'job_id == "{versioned_job_id}"',
        output_fields=['job_id', 'position'],
        limit=1
    )
    if not results:
        print(f"ERROR: Could not find {versioned_job_id}")
        sys.exit(1)
    position = results[0].get('position', '')
else:
    position = job.get('position', '')

if not position:
    print(f"ERROR: Could not get position for {versioned_job_id}")
    sys.exit(1)

# Set all versions to current=False first
print(f"\nSetting all versions to current=False...")
for v in versions:
    v_job_id = v.get('job_id')
    if v_job_id:
        # Get position for this version
        v_results = _client.query(
            collection_name=_collection_name,
            filter=f'job_id == "{v_job_id}"',
            output_fields=['job_id', 'position'],
            limit=1
        )
        v_position = v_results[0].get('position', '') if v_results else ''
        if v_position:
            _client.upsert(
                collection_name=_collection_name,
                data=[{'job_id': v_job_id, 'position': v_position, 'current': False}],
                partial_update=True
            )

# Set v1 to current=True
print(f"Setting {versioned_job_id} to current=True...")
_client.upsert(
    collection_name=_collection_name,
    data=[{'job_id': versioned_job_id, 'position': position, 'current': True}],
    partial_update=True
)

# Wait a bit for database to update
time.sleep(0.5)

# Verify
print(f"\nVerifying...")
updated_versions = get_job_versions(base_job_id)
current = next((v for v in updated_versions if v.get('current')), None)
if current:
    print(f"✅ Success: {current.get('job_id')} is now current (version {current.get('version')})")
    if current.get('version') == 1:
        print("✅ Verified: architecture_v1 is correctly set as current")
    else:
        print(f"⚠️  Warning: Expected version 1 to be current, but version {current.get('version')} is current")
else:
    print("❌ Failed: No current version found after fix")
    sys.exit(1)

