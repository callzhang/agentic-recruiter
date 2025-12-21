#!/usr/bin/env python3
"""Publish an optimized job portrait into the system via Jobs API.

This script is meant to remove manual UI updates from the prompt-optimization loop:
- Edit a run folder's `job_portrait_optimized.json`
- Publish it to the Jobs store (creates a new version)
- Fetch the updated "current" job portrait back via API for verification

Local FastAPI routes live in `web/routes/jobs.py`:
- POST /jobs/{job_id}/update
- GET  /jobs/api/{job_id}

Vercel routes live in `vercel/api/jobs.py`:
- POST /api/jobs/{job_id}/update
- GET  /api/jobs/{job_id}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests


def _get_base_job_id(job_id: str) -> str:
    return re.sub(r"_v\\d+$", "", (job_id or "").strip())

def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate a string by UTF-8 byte length (Milvus VARCHAR max_length is strict)."""
    if not text:
        return ""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore").strip()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_update_payload(job: dict[str, Any]) -> dict[str, Any]:
    """Map an exported/optimized job portrait JSON to the update API payload."""

    base_job_id = (job.get("base_job_id") or "").strip() or _get_base_job_id(str(job.get("job_id") or ""))
    position = (job.get("position") or "").strip()
    if not base_job_id or not position:
        raise ValueError("job_portrait must contain `position` and either `base_job_id` or `job_id`")

    # Only keep fields that exist in the jobs-store schema.
    allowed_keys = {
        "job_id",
        "base_job_id",
        "position",
        "background",
        "description",
        "responsibilities",
        "requirements",
        "target_profile",
        "drill_down_questions",
        "keywords",
        "candidate_filters",
        "notification",
    }
    extra_keys = sorted(set(job.keys()) - allowed_keys)
    if extra_keys:
        print(
            f"WARNING: job_portrait contains non-schema fields that will be ignored: {', '.join(extra_keys)}",
            file=sys.stderr,
        )

    # Align with Milvus schema constraints (see `src/jobs_store.py`):
    # - background/description/responsibilities/requirements/target_profile: VARCHAR max_length=5000
    # - drill_down_questions: VARCHAR max_length=65000
    position = _truncate_utf8(position, 200)
    background = _truncate_utf8((job.get("background") or "").strip(), 5000)
    description = _truncate_utf8((job.get("description") or "").strip(), 5000)
    responsibilities = _truncate_utf8((job.get("responsibilities") or "").strip(), 5000)
    requirements = _truncate_utf8((job.get("requirements") or "").strip(), 5000)
    target_profile = _truncate_utf8((job.get("target_profile") or "").strip(), 5000)
    drill_down_questions = _truncate_utf8((job.get("drill_down_questions") or "").strip(), 65000)

    payload: dict[str, Any] = {
        "job_id": base_job_id,
        "position": position,
        "background": background,
        "description": description,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "target_profile": target_profile,
        "drill_down_questions": drill_down_questions,
    }

    if isinstance(job.get("keywords"), dict):
        payload["keywords"] = job.get("keywords")
    if job.get("candidate_filters") is not None:
        payload["candidate_filters"] = job.get("candidate_filters")
    if job.get("notification") is not None:
        payload["notification"] = job.get("notification")

    return payload


def _build_urls(api_base: str, api_type: str, base_job_id: str) -> tuple[str, str]:
    base = api_base.rstrip("/")
    if api_type == "local":
        return f"{base}/jobs/{base_job_id}/update", f"{base}/jobs/api/{base_job_id}"
    if api_type == "vercel":
        return f"{base}/api/jobs/{base_job_id}/update", f"{base}/api/jobs/{base_job_id}"
    raise ValueError(f"Unsupported api_type: {api_type}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--job-portrait",
        default=None,
        help="Path to job_portrait_optimized.json (or job_portrait.json) to publish",
    )
    parser.add_argument(
        "--download-job-id",
        default=None,
        help="Download current job portrait by job_id/base_job_id and write to --download-out",
    )
    parser.add_argument(
        "--download-out",
        default=None,
        help="Write downloaded job portrait JSON to this path (required with --download-job-id)",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="API base URL (local FastAPI or Vercel deployment)",
    )
    parser.add_argument(
        "--api-type",
        choices=["local", "vercel"],
        default="local",
        help="Which API routing style to use",
    )
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print payload + URLs without calling API")
    args = parser.parse_args()

    if args.download_job_id:
        if not args.download_out:
            raise SystemExit("--download-out is required when using --download-job-id")
        base_job_id = _get_base_job_id(args.download_job_id)
        _update_url, get_url = _build_urls(args.api_base, args.api_type, base_job_id)
        if args.dry_run:
            print("GET_URL:", get_url)
            print("DOWNLOAD_OUT:", args.download_out)
            return 0

        resp = requests.get(get_url, timeout=args.timeout)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw": resp.text}
        if resp.status_code >= 400:
            print("Download failed:", resp.status_code, json.dumps(resp_json, ensure_ascii=False, indent=2))
            return 2
        data = resp_json.get("data") if isinstance(resp_json, dict) else None
        if not isinstance(data, dict):
            print("Download failed: unexpected response shape:", json.dumps(resp_json, ensure_ascii=False, indent=2))
            return 2
        out_path = Path(args.download_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Downloaded current job portrait to:", str(out_path))

        # If the user only wanted download, stop here.
        if not args.job_portrait:
            return 0

    if not args.job_portrait:
        raise SystemExit("Either --job-portrait (publish) or --download-job-id (download) is required")

    portrait_path = Path(args.job_portrait)
    if not portrait_path.exists():
        raise SystemExit(f"job portrait not found: {portrait_path}")

    job = _read_json(portrait_path)
    payload = _build_update_payload(job)
    base_job_id = _get_base_job_id(payload.get("job_id") or "")
    update_url, get_url = _build_urls(args.api_base, args.api_type, base_job_id)

    if args.dry_run:
        print("UPDATE_URL:", update_url)
        print("GET_URL:", get_url)
        print("PAYLOAD:\n", json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    resp = requests.post(update_url, json=payload, timeout=args.timeout)
    try:
        resp_json = resp.json()
    except Exception:
        resp_json = {"raw": resp.text}
    if resp.status_code >= 400:
        print("Update failed:", resp.status_code, json.dumps(resp_json, ensure_ascii=False, indent=2))
        return 2

    print("Update response:", json.dumps(resp_json, ensure_ascii=False, indent=2))

    resp2 = requests.get(get_url, timeout=args.timeout)
    try:
        resp2_json = resp2.json()
    except Exception:
        resp2_json = {"raw": resp2.text}
    if resp2.status_code >= 400:
        print("Fetch failed:", resp2.status_code, json.dumps(resp2_json, ensure_ascii=False, indent=2))
        return 3

    print("Fetched current job:", json.dumps(resp2_json, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
