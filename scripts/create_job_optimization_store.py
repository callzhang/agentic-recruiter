#!/usr/bin/env python3
"""Create the Zilliz collection for job-portrait optimization feedback.

Usage:
    python scripts/create_job_optimization_store.py
    python scripts/create_job_optimization_store.py --collection CN_job_optimizations
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.job_optimization_feedback_store import create_collection  # noqa: E402
from src.config import get_zilliz_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create job optimization feedback collection")
    parser.add_argument("--collection", default=None, help="Collection name (optional)")
    args = parser.parse_args()

    zilliz_config = get_zilliz_config()
    default_name = zilliz_config.get("job_optimization_collection_name", "CN_job_optimizations")
    name = args.collection or default_name

    ok = create_collection(name)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

