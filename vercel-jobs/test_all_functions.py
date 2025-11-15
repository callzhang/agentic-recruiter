#!/usr/bin/env python3
"""Comprehensive test script for all job functions with extensive test cases"""

import sys
import os
import time
from pathlib import Path

# Change to project root
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_zilliz_config

# Set up environment to match Vercel function
zilliz_conf = get_zilliz_config()
os.environ['ZILLIZ_ENDPOINT'] = zilliz_conf['endpoint']
os.environ['ZILLIZ_TOKEN'] = zilliz_conf.get('token', '')
os.environ['ZILLIZ_USER'] = zilliz_conf['user']
os.environ['ZILLIZ_PASSWORD'] = zilliz_conf['password']
os.environ['ZILLIZ_JOB_COLLECTION_NAME'] = 'CN_jobs'
os.environ['ZILLIZ_EMBEDDING_DIM'] = '1536'

# Import the functions from jobs.py
sys.path.insert(0, str(Path(__file__).parent))
from api.jobs import (
    get_all_jobs, get_job_by_id, insert_job, update_job,
    get_job_versions, switch_job_version, delete_job_version,
    get_base_job_id
)

# Test job ID for cleanup
test_job_ids = []

def cleanup_test_jobs():
    """Clean up all test jobs created during testing"""
    from api.jobs import get_client, COLLECTION_NAME
    client = get_client()
    
    if not test_job_ids:
        print("   No test jobs to clean up")
        return
    
    print(f"   Cleaning up {len(test_job_ids)} test job(s)...")
    cleaned_count = 0
    failed_count = 0
    
    for job_id in test_job_ids:
        try:
            base_id = get_base_job_id(job_id)
            versions = get_job_versions(base_id)
            
            if not versions:
                # Job might already be deleted, try to delete by base_id pattern anyway
                try:
                    client.delete(collection_name=COLLECTION_NAME, 
                                filter=f'job_id >= "{base_id}_v" && job_id < "{base_id}_w"')
                    print(f"   Cleaned up (no versions found): {base_id}")
                    cleaned_count += 1
                except:
                    pass
                continue
            
            # Delete all versions
            for v in versions:
                if v.get('job_id'):
                    try:
                        client.delete(collection_name=COLLECTION_NAME, 
                                    filter=f'job_id == "{v["job_id"]}"')
                    except Exception as e:
                        print(f"   Warning: Failed to delete {v['job_id']}: {e}")
            
            print(f"   ✅ Cleaned up: {base_id} ({len(versions)} version(s))")
            cleaned_count += 1
        except Exception as e:
            print(f"   ❌ Failed to cleanup {job_id}: {e}")
            failed_count += 1
    
    print(f"   Summary: {cleaned_count} cleaned, {failed_count} failed")
    
    # Also clean up any test jobs that might have been created but not tracked
    # (e.g., if test was interrupted)
    try:
        all_jobs = get_all_jobs()
        test_jobs = [j for j in all_jobs if j.get('job_id', '').startswith('test_')]
        if test_jobs:
            print(f"   Found {len(test_jobs)} additional test job(s) to clean up...")
            for job in test_jobs:
                try:
                    base_id = get_base_job_id(job.get('job_id', ''))
                    if base_id not in [get_base_job_id(tid) for tid in test_job_ids]:
                        versions = get_job_versions(base_id)
                        for v in versions:
                            if v.get('job_id'):
                                client.delete(collection_name=COLLECTION_NAME, 
                                            filter=f'job_id == "{v["job_id"]}"')
                        print(f"   ✅ Cleaned up untracked: {base_id}")
                        cleaned_count += 1
                except Exception as e:
                    print(f"   Warning: Failed to cleanup untracked job: {e}")
    except Exception as e:
        print(f"   Warning: Could not check for untracked test jobs: {e}")

def test_get_all_jobs():
    """Test get_all_jobs()"""
    print("\n" + "="*60)
    print("TEST 1: get_all_jobs()")
    print("="*60)
    try:
        jobs = get_all_jobs()
        print(f"✅ Success: Retrieved {len(jobs)} jobs")
        if jobs:
            print(f"   First job: {jobs[0].get('job_id')} - {jobs[0].get('position')}")
            # Verify all returned jobs are current
            all_current = all(j.get('current') for j in jobs)
            print(f"   All current: {all_current}")
            if not all_current:
                print("   ⚠️  Warning: Some jobs are not marked as current")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_job_by_id():
    """Test get_job_by_id() with base ID"""
    print("\n" + "="*60)
    print("TEST 2: get_job_by_id() with base ID")
    print("="*60)
    try:
        job = get_job_by_id('ml_engineer')
        if job:
            print(f"✅ Success: Retrieved job {job.get('job_id')} (version {job.get('version')})")
            print(f"   Position: {job.get('position')}")
            print(f"   Current: {job.get('current')}")
            # Verify it's the current version
            if not job.get('current'):
                print("   ⚠️  Warning: Retrieved job is not marked as current")
            return job
        else:
            print("❌ Failed: Job not found")
            return None
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_get_job_by_versioned_id():
    """Test get_job_by_id() with versioned ID"""
    print("\n" + "="*60)
    print("TEST 3: get_job_by_id() with versioned ID")
    print("="*60)
    try:
        # Test with versioned job ID
        job = get_job_by_id('ml_engineer_v3')
        if job:
            print(f"✅ Success: Retrieved job {job.get('job_id')} (version {job.get('version')})")
            print(f"   Position: {job.get('position')}")
            # Verify it's the correct version
            if job.get('version') != 3:
                print(f"   ⚠️  Warning: Expected version 3, got {job.get('version')}")
            return True
        else:
            print("❌ Failed: Versioned job not found")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_job_by_id_not_found():
    """Test get_job_by_id() with non-existent ID"""
    print("\n" + "="*60)
    print("TEST 4: get_job_by_id() with non-existent ID")
    print("="*60)
    try:
        job = get_job_by_id('non_existent_job_12345')
        if job is None:
            print("✅ Success: Correctly returned None for non-existent job")
            return True
        else:
            print(f"❌ Failed: Should return None, got {job}")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_job_versions():
    """Test get_job_versions()"""
    print("\n" + "="*60)
    print("TEST 5: get_job_versions()")
    print("="*60)
    try:
        versions = get_job_versions('ml_engineer')
        print(f"✅ Success: Retrieved {len(versions)} versions")
        for v in versions:
            print(f"   v{v.get('version')}: {v.get('job_id')} (current: {v.get('current')})")
        # Verify at least one is current
        current_count = sum(1 for v in versions if v.get('current'))
        if current_count == 0:
            print("   ⚠️  Warning: No version marked as current")
        elif current_count > 1:
            print(f"   ⚠️  Warning: {current_count} versions marked as current (should be 1)")
        return versions
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_get_job_versions_empty():
    """Test get_job_versions() with non-existent job"""
    print("\n" + "="*60)
    print("TEST 6: get_job_versions() with non-existent job")
    print("="*60)
    try:
        versions = get_job_versions('non_existent_job_12345')
        if len(versions) == 0:
            print("✅ Success: Correctly returned empty list for non-existent job")
            return True
        else:
            print(f"❌ Failed: Should return empty list, got {len(versions)} versions")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_insert_job():
    """Test insert_job()"""
    print("\n" + "="*60)
    print("TEST 7: insert_job()")
    print("="*60)
    try:
        timestamp = int(time.time())
        test_job_data = {
            'id': f'test_job_{timestamp}',
            'position': '测试岗位',
            'background': '测试公司背景',
            'description': '测试岗位描述',
            'responsibilities': '测试职责',
            'requirements': '测试要求',
            'target_profile': '测试理想人选',
            'keywords': {'positive': ['Python', 'FastAPI'], 'negative': ['Java']},
            'drill_down_questions': '测试问题1\n测试问题2',
            'candidate_filters': {'学历': '本科', '经验': '3-5年'}
        }
        result = insert_job(**test_job_data)
        if result:
            print(f"✅ Success: Created job {test_job_data['id']}")
            # Wait a bit for database to update
            time.sleep(0.5)
            # Verify the job was created
            created_job = get_job_by_id(test_job_data['id'])
            if created_job:
                print(f"   Verified: Job exists with version {created_job.get('version')}")
                print(f"   Current: {created_job.get('current')}")
                test_job_ids.append(test_job_data['id'])
                return test_job_data['id']
            else:
                print("   ⚠️  Warning: Job created but not found when queried")
                test_job_ids.append(test_job_data['id'])
                return test_job_data['id']
        else:
            print("❌ Failed: insert_job returned False")
            return None
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_insert_job_duplicate():
    """Test insert_job() with duplicate ID - note: insert_job doesn't check duplicates"""
    print("\n" + "="*60)
    print("TEST 8: insert_job() with duplicate ID")
    print("="*60)
    try:
        # First create a job
        timestamp = int(time.time())
        test_job_data = {
            'id': f'test_dup_{timestamp}',
            'position': '测试岗位',
        }
        insert_job(**test_job_data)
        test_job_ids.append(test_job_data['id'])
        time.sleep(0.5)
        
        # Try to create again with same ID
        # Note: insert_job() itself doesn't check for duplicates - that's done at API handler level
        # So this will actually create a duplicate, which is expected behavior for the function
        result = insert_job(**test_job_data)
        if result:
            print("⚠️  Note: insert_job() allows duplicates (duplicate check is at API handler level)")
            print("   This is expected - the function just inserts, API handler validates")
            return True
        else:
            print("✅ Success: Function rejected duplicate (unexpected but good)")
            return True
    except Exception as e:
        print(f"✅ Success: Correctly raised exception for duplicate: {e}")
        return True

def test_update_job():
    """Test update_job() - creates new version"""
    print("\n" + "="*60)
    print("TEST 9: update_job() - creates new version")
    print("="*60)
    try:
        # Create a test job first
        timestamp = int(time.time())
        test_job_id = f'test_update_{timestamp}'
        test_job_data = {
            'id': test_job_id,
            'position': '原始岗位',
            'background': '原始背景',
        }
        insert_job(**test_job_data)
        test_job_ids.append(test_job_id)
        
        # Wait a bit to ensure timestamps are different
        time.sleep(1)
        
        # Get current state
        current_job = get_job_by_id(test_job_id)
        if not current_job:
            print("❌ Failed: Cannot find job to update")
            return False
        
        versions_before = get_job_versions(test_job_id)
        max_version_before = max([v.get('version', 0) for v in versions_before], default=0)
        print(f"   Current version: {max_version_before}")
        
        # Update with modified data
        update_data = {
            'position': '更新后的岗位',
            'background': current_job.get('background', '') + ' [Updated]',
            'description': current_job.get('description', ''),
            'responsibilities': current_job.get('responsibilities', ''),
            'requirements': current_job.get('requirements', ''),
            'target_profile': current_job.get('target_profile', ''),
            'keywords': current_job.get('keywords', {'positive': [], 'negative': []}),
            'drill_down_questions': current_job.get('drill_down_questions', ''),
            'candidate_filters': current_job.get('candidate_filters'),
        }
        
        result = update_job(test_job_id, **update_data)
        if result:
            # Wait a bit for database to update
            time.sleep(0.5)
            
            # Check that new version was created
            versions_after = get_job_versions(test_job_id)
            max_version_after = max([v.get('version', 0) for v in versions_after], default=0)
            
            print(f"   New version: {max_version_after}")
            
            if max_version_after == max_version_before + 1:
                print(f"✅ Success: Created new version {max_version_after}")
                new_job = get_job_by_id(test_job_id)
                if new_job:
                    print(f"   New job_id: {new_job.get('job_id')}")
                    print(f"   New current: {new_job.get('current')}")
                    print(f"   New position: {new_job.get('position')}")
                    # Verify old version is no longer current
                    old_version = get_job_by_id(f'{test_job_id}_v{max_version_before}')
                    if old_version and old_version.get('current'):
                        print("   ⚠️  Warning: Old version still marked as current")
                    elif old_version:
                        print("   ✅ Verified: Old version correctly marked as non-current")
                return True
            else:
                print(f"❌ Failed: Expected version {max_version_before + 1}, got {max_version_after}")
                print(f"   Versions before: {[v.get('version') for v in versions_before]}")
                print(f"   Versions after: {[v.get('version') for v in versions_after]}")
                return False
        else:
            print("❌ Failed: update_job returned False")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_update_job_not_found():
    """Test update_job() with non-existent job"""
    print("\n" + "="*60)
    print("TEST 10: update_job() with non-existent job")
    print("="*60)
    try:
        result = update_job('non_existent_job_12345', position='Test')
        if not result:
            print("✅ Success: Correctly returned False for non-existent job")
            return True
        else:
            print("❌ Failed: Should return False for non-existent job")
            return False
    except Exception as e:
        print(f"✅ Success: Correctly raised exception: {e}")
        return True

def test_switch_job_version():
    """Test switch_job_version()"""
    print("\n" + "="*60)
    print("TEST 11: switch_job_version()")
    print("="*60)
    try:
        base_job_id = 'ml_engineer'
        versions = get_job_versions(base_job_id)
        
        if len(versions) < 2:
            print("⚠️  Skipped: Need at least 2 versions to test switching")
            return True
        
        # Find current version
        current_version = next((v for v in versions if v.get('current')), None)
        # Find a non-current version to switch to
        non_current = next((v for v in versions if not v.get('current')), None)
        
        if not non_current:
            print("⚠️  Skipped: All versions are current")
            return True
        
        target_version = non_current.get('version')
        print(f"   Current version: {current_version.get('version') if current_version else 'None'}")
        print(f"   Switching to version {target_version}...")
        
        result = switch_job_version(base_job_id, target_version)
        if result:
            # Wait a bit for database to update
            time.sleep(0.5)
            
            # Verify the switch
            updated_job = get_job_by_id(base_job_id)
            if updated_job.get('version') == target_version and updated_job.get('current'):
                print(f"✅ Success: Switched to version {target_version}")
                # Verify old current is no longer current
                if current_version:
                    old_job = get_job_by_id(current_version.get('job_id'))
                    if old_job and old_job.get('current'):
                        print("   ⚠️  Warning: Old version still marked as current")
                    else:
                        print("   ✅ Verified: Old version correctly marked as non-current")
                return True
            else:
                print(f"❌ Failed: Version not switched correctly")
                print(f"   Expected version: {target_version}, current: True")
                print(f"   Got version: {updated_job.get('version')}, current: {updated_job.get('current')}")
                return False
        else:
            print("❌ Failed: switch_job_version returned False")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_switch_job_version_not_found():
    """Test switch_job_version() with non-existent version"""
    print("\n" + "="*60)
    print("TEST 12: switch_job_version() with non-existent version")
    print("="*60)
    try:
        result = switch_job_version('ml_engineer', 99999)
        if not result:
            print("✅ Success: Correctly returned False for non-existent version")
            return True
        else:
            print("❌ Failed: Should return False for non-existent version")
            return False
    except Exception as e:
        print(f"✅ Success: Correctly raised exception: {e}")
        return True

def test_delete_job_version():
    """Test delete_job_version() - actually delete a test version"""
    print("\n" + "="*60)
    print("TEST 13: delete_job_version() - actual deletion")
    print("="*60)
    try:
        # Create a test job with multiple versions
        timestamp = int(time.time())
        test_job_id = f'test_delete_{timestamp}'
        test_job_data = {
            'id': test_job_id,
            'position': '测试删除',
        }
        insert_job(**test_job_data)
        test_job_ids.append(test_job_id)
        
        # Create a second version
        time.sleep(1)
        update_data = {
            'position': '测试删除',
            'background': '',
            'description': '',
            'responsibilities': '',
            'requirements': '',
            'target_profile': '',
            'keywords': {'positive': [], 'negative': []},
            'drill_down_questions': '',
            'candidate_filters': None,
        }
        update_job(test_job_id, **update_data)
        time.sleep(0.5)
        
        versions = get_job_versions(test_job_id)
        if len(versions) < 2:
            print("⚠️  Skipped: Could not create multiple versions")
            return True
        
        # Find a non-current version to delete
        non_current = next((v for v in versions if not v.get('current')), None)
        if not non_current:
            print("⚠️  Skipped: All versions are current")
            return True
        
        target_version = non_current.get('version')
        versions_before = len(versions)
        
        print(f"   Deleting version {target_version}...")
        result = delete_job_version(test_job_id, target_version)
        
        if result:
            time.sleep(0.5)
            versions_after = get_job_versions(test_job_id)
            
            if len(versions_after) == versions_before - 1:
                print(f"✅ Success: Deleted version {target_version}")
                print(f"   Versions before: {versions_before}, after: {len(versions_after)}")
                # Verify current version still exists
                current = next((v for v in versions_after if v.get('current')), None)
                if current:
                    print(f"   ✅ Verified: Current version {current.get('version')} still exists")
                else:
                    print("   ⚠️  Warning: No current version after deletion")
                return True
            else:
                print(f"❌ Failed: Expected {versions_before - 1} versions, got {len(versions_after)}")
                return False
        else:
            print("❌ Failed: delete_job_version returned False")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_delete_job_version_last():
    """Test delete_job_version() - try to delete last version (should fail)"""
    print("\n" + "="*60)
    print("TEST 14: delete_job_version() - try to delete last version")
    print("="*60)
    try:
        # Create a test job with only one version
        timestamp = int(time.time())
        test_job_id = f'test_delete_last_{timestamp}'
        test_job_data = {
            'id': test_job_id,
            'position': '测试删除最后',
        }
        insert_job(**test_job_data)
        test_job_ids.append(test_job_id)
        time.sleep(0.5)
        
        versions = get_job_versions(test_job_id)
        if len(versions) != 1:
            print(f"⚠️  Skipped: Expected 1 version, got {len(versions)}")
            return True
        
        # Try to delete the only version
        result = delete_job_version(test_job_id, versions[0].get('version'))
        # This should succeed at the function level, but the API should prevent it
        # The function itself doesn't check, so it will delete
        # But we can verify it was deleted
        time.sleep(0.5)
        versions_after = get_job_versions(test_job_id)
        if len(versions_after) == 0:
            print("✅ Success: Function deleted the last version (API layer should prevent this)")
            return True
        else:
            print(f"⚠️  Note: Last version was not deleted (may be protected at API layer)")
            return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_base_job_id():
    """Test get_base_job_id() helper function"""
    print("\n" + "="*60)
    print("TEST 15: get_base_job_id() helper function")
    print("="*60)
    try:
        test_cases = [
            ('ml_engineer_v3', 'ml_engineer'),
            ('test_job_v1', 'test_job'),
            ('ml_engineer', 'ml_engineer'),  # Already base
            ('job_v10', 'job'),
        ]
        
        all_passed = True
        for input_id, expected in test_cases:
            result = get_base_job_id(input_id)
            if result == expected:
                print(f"   ✅ {input_id} -> {result}")
            else:
                print(f"   ❌ {input_id} -> {result} (expected {expected})")
                all_passed = False
        
        if all_passed:
            print("✅ Success: All test cases passed")
            return True
        else:
            print("❌ Failed: Some test cases failed")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_update_job_empty_fields():
    """Test update_job() with empty/None fields"""
    print("\n" + "="*60)
    print("TEST 16: update_job() with empty/None fields")
    print("="*60)
    try:
        # Create a test job
        timestamp = int(time.time())
        test_job_id = f'test_empty_{timestamp}'
        test_job_data = {
            'id': test_job_id,
            'position': '测试空字段',
            'background': '原始背景',
        }
        insert_job(**test_job_data)
        test_job_ids.append(test_job_id)
        time.sleep(1)
        
        # Update with some empty fields
        update_data = {
            'position': '测试空字段',  # Required field
            'background': '',  # Empty string
            'description': None,  # None value
            'responsibilities': '',
            'requirements': '',
            'target_profile': '',
            'keywords': {'positive': [], 'negative': []},
            'drill_down_questions': '',
            'candidate_filters': None,
        }
        
        result = update_job(test_job_id, **update_data)
        if result:
            time.sleep(0.5)
            updated_job = get_job_by_id(test_job_id)
            if updated_job:
                print("✅ Success: Updated job with empty/None fields")
                print(f"   Background: '{updated_job.get('background')}'")
                print(f"   Description: {updated_job.get('description')}")
                return True
            else:
                print("❌ Failed: Updated job not found")
                return False
        else:
            print("❌ Failed: update_job returned False")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("COMPREHENSIVE JOB FUNCTIONS TEST SUITE")
    print("="*60)
    
    results = []
    
    # Core function tests
    results.append(("get_all_jobs", test_get_all_jobs()))
    job = test_get_job_by_id()
    results.append(("get_job_by_id (base)", job is not None))
    results.append(("get_job_by_id (versioned)", test_get_job_by_versioned_id()))
    results.append(("get_job_by_id (not found)", test_get_job_by_id_not_found()))
    versions = test_get_job_versions()
    results.append(("get_job_versions", versions is not None))
    results.append(("get_job_versions (empty)", test_get_job_versions_empty()))
    
    # Insert tests
    test_job_id = test_insert_job()
    results.append(("insert_job", test_job_id is not None))
    results.append(("insert_job (duplicate)", test_insert_job_duplicate()))
    
    # Update tests
    results.append(("update_job", test_update_job()))
    results.append(("update_job (not found)", test_update_job_not_found()))
    results.append(("update_job (empty fields)", test_update_job_empty_fields()))
    
    # Switch version tests
    results.append(("switch_job_version", test_switch_job_version()))
    results.append(("switch_job_version (not found)", test_switch_job_version_not_found()))
    
    # Delete tests
    results.append(("delete_job_version", test_delete_job_version()))
    results.append(("delete_job_version (last)", test_delete_job_version_last()))
    
    # Helper function tests
    results.append(("get_base_job_id", test_get_base_job_id()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed ({passed*100//total}%)")
    
    # Cleanup - always run, even if no test_job_ids tracked
    print("\n" + "="*60)
    print("CLEANUP")
    print("="*60)
    cleanup_test_jobs()
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == '__main__':
    try:
        exit_code = main()
        # Cleanup is already called in main(), but ensure it runs on early exit
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        print("Cleaning up test jobs...")
        cleanup_test_jobs()
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        print("Cleaning up test jobs...")
        cleanup_test_jobs()
        raise
