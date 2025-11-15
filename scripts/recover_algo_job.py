#!/usr/bin/env python3
"""Recover the 'algo' job from backup file."""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.jobs_store import insert_job, get_job_by_id

def recover_algo_job():
    """Recover the algo job from backup."""
    backup_file = Path(__file__).parent.parent / "data" / "jobs_backup_20251114_161133.json"
    
    if not backup_file.exists():
        print(f"❌ Backup file not found: {backup_file}")
        return False
    
    # Load backup data
    with open(backup_file, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    # Find the algo job
    algo_job = None
    for job in jobs:
        if job.get("job_id") == "algo":
            algo_job = job
            break
    
    if not algo_job:
        print("❌ 'algo' job not found in backup file")
        return False
    
    # Check if job already exists
    existing = get_job_by_id("algo")
    if existing:
        print(f"⚠️  Job 'algo' already exists (current version: v{existing.get('version', '?')})")
        response = input("Do you want to restore it anyway? This will create a new version. (y/N): ")
        if response.lower() != 'y':
            print("❌ Cancelled")
            return False
    
    # Prepare job data for insert_job
    # The backup has job_id, but insert_job expects 'id'
    job_data = algo_job.copy()
    job_data["id"] = job_data.pop("job_id")
    
    # Remove fields that insert_job doesn't expect
    job_data.pop("created_at", None)
    job_data.pop("updated_at", None)
    job_data.pop("version", None)
    job_data.pop("current", None)
    job_data.pop("job_embedding", None)
    
    # Insert the job (will create as version 1 with current=True)
    try:
        success = insert_job(**job_data)
        if success:
            print("✅ Successfully recovered 'algo' job as version 1")
            # Verify it was created
            restored = get_job_by_id("algo")
            if restored:
                print(f"   Position: {restored.get('position', 'N/A')}")
                print(f"   Version: v{restored.get('version', '?')}")
                print(f"   Current: {restored.get('current', False)}")
            return True
        else:
            print("❌ Failed to insert job")
            return False
    except Exception as e:
        print(f"❌ Error inserting job: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Recovering 'algo' job from backup...")
    recover_algo_job()

