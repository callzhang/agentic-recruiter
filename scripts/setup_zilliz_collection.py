#!/usr/bin/env python3
"""Utility script to ensure the Zilliz collection exists."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.qa_store import QAStore, load_config

logging.basicConfig(level=logging.INFO)


def main() -> None:
    cfg = load_config()
    if not cfg:
        logging.error("No Zilliz configuration found; aborting")
        return
    store = QAStore(cfg)
    if store.enabled:
        logging.info("Collection '%s' is ready", cfg.collection_name)
    else:
        logging.error("Failed to initialise QAStore")


if __name__ == "__main__":
    main()
