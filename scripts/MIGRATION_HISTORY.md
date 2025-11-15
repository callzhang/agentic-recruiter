# Migration Scripts History

This document tracks the migration scripts that have been used and their status.

## Completed Migrations

### Jobs Collection Migrations
All jobs migration scripts have been completed and are no longer needed. The current jobs collection uses versioning with `version` and `current` fields.

**Completed Scripts (can be deleted):**
- `migrate_jobs_add_fields.py` - Added version/current fields to jobs collection
- `migrate_jobs_add_versions.py` - Migrated jobs to versioned format (ml_engineer -> ml_engineer_v1)
- `migrate_jobs_recreate_collection.py` - Recreated collection with new schema (alternative approach)
- `migrate_jobs_to_cn_jobs_2.py` - Migrated from CN_jobs to CN_jobs_2 (if used)

**Current State:**
- Collection: Uses `job_collection_name` from config (typically `CN_jobs` or `CN_jobs_2`)
- Schema: Includes `version` (INT64) and `current` (BOOL) fields
- Format: Jobs use versioned IDs (e.g., `ml_engineer_v1`, `ml_engineer_v2`)

### Candidates Collection Migrations
- `migrate_candidates_data.py` - Migrated from `CN_candidates` to `CN_candidates_v3`
  - **Status:** ✅ Completed on 2025-11-14
  - **Changes:**
    - Removed `thread_id`, replaced with `conversation_id`
    - Added `generated_message` field (VARCHAR, max_length=5000, nullable)
    - Increased `resume_text` and `full_resume` max_length to 65535
    - Deduplicated records by name (444 → 415 records)
  - **Action Required:** Update config to use `CN_candidates_v3`

## Active Scripts

- `migrate_candidates_data.py` - Keep for reference (recently used)
- `recover_algo_job.py` - Utility script to recover deleted jobs from backup
- `restore_jobs_from_backup.py` - Utility script to restore jobs from backup

## Notes

- Old migration scripts can be safely deleted once migrations are verified complete
- Always backup data before running migrations
- Test migrations on a development environment first

