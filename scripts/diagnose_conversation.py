#!/usr/bin/env python3
"""
Diagnose conversation behavior for a candidate_id.

Usage:
  python scripts/diagnose_conversation.py --candidate-id <id> [--tail 8]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from openai import OpenAI

from src.candidate_store import get_candidate_by_dict


def load_openai_client() -> OpenAI:
    config_path = Path("config/config.yaml")
    secrets_path = Path("config/secrets.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config_values = yaml.safe_load(f) or {}
    with open(secrets_path, "r", encoding="utf-8") as f:
        secrets_values = yaml.safe_load(f) or {}
    openai_config = {**config_values.get("openai", {}), **secrets_values.get("openai", {})}
    return OpenAI(
        api_key=openai_config.get("api_key"),
        base_url=openai_config.get("base_url"),
    )


def extract_text(content_raw: Any) -> str:
    if isinstance(content_raw, list):
        parts: List[str] = []
        for c in content_raw:
            if hasattr(c, "text"):
                parts.append(c.text)
            elif isinstance(c, str):
                parts.append(c)
        return "".join(parts)
    if isinstance(content_raw, str):
        return content_raw
    return ""


def list_conversation_items(client: OpenAI, conversation_id: str) -> List[Any]:
    items: List[Any] = []
    after = None
    has_more = True
    while has_more:
        params: Dict[str, Any] = {"conversation_id": conversation_id}
        if after:
            params["after"] = after
        resp = client.conversations.items.list(**params, order="asc")
        page_items = resp.data if hasattr(resp, "data") else []
        items.extend(page_items)
        has_more = getattr(resp, "has_more", False)
        if page_items:
            after = page_items[-1].id
        else:
            break
    return items


def summarize_items(items: List[Any], tail: int = 8) -> None:
    start = max(0, len(items) - tail)
    print(f"\nLast {min(tail, len(items))} items:")
    for idx in range(start, len(items)):
        item = items[idx]
        item_type = getattr(item, "type", "")
        item_id = getattr(item, "id", "")
        role = getattr(item, "role", None)
        content = extract_text(getattr(item, "content", ""))
        preview = content.replace("\n", " ")[:140]
        print(f"[{idx+1}/{len(items)}] type={item_type} role={role} id={item_id}")
        if preview:
            print(f"  {preview}")


def find_tool_calls(items: List[Any]) -> List[Tuple[str, str]]:
    calls: List[Tuple[str, str]] = []
    for item in items:
        item_type = getattr(item, "type", "")
        if item_type in ("tool_call", "tool_result"):
            name = getattr(item, "name", "") or ""
            calls.append((item_type, name))
        if getattr(item, "role", "") == "tool":
            name = getattr(item, "name", "") or ""
            calls.append(("tool", name))
    return calls


def analyze_last_turn(items: List[Any]) -> None:
    messages: List[Tuple[str, str]] = []
    for item in items:
        if getattr(item, "type", None) == "message":
            role = getattr(item, "role", "")
            content = extract_text(getattr(item, "content", ""))
            messages.append((role, content))

    if not messages:
        print("\nNo messages found.")
        return

    last_user = next((c for r, c in reversed(messages) if r == "user"), "")
    last_assistant = next((c for r, c in reversed(messages) if r == "assistant"), "")

    print("\nLast user message:")
    print(last_user[:500] + ("..." if len(last_user) > 500 else ""))
    print("\nLast assistant message:")
    print(last_assistant[:500] + ("..." if len(last_assistant) > 500 else ""))

    is_json = False
    try:
        parsed = json.loads(last_assistant)
        is_json = isinstance(parsed, dict)
    except Exception:
        parsed = None

    if is_json:
        print("\nAssistant output is JSON. Keys:", list(parsed.keys()) if parsed else [])
        if last_user and "?" in last_user:
            print("⚠️ Last user message is a question, but assistant replied in JSON.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True, help="Candidate ID in Milvus.")
    parser.add_argument("--tail", type=int, default=8, help="How many trailing items to print.")
    args = parser.parse_args()

    candidate = get_candidate_by_dict({"candidate_id": args.candidate_id})
    if not candidate:
        print(f"❌ candidate not found: {args.candidate_id}")
        return 1

    conversation_id = candidate.get("conversation_id")
    if not conversation_id:
        print(f"❌ conversation_id not found for candidate: {args.candidate_id}")
        return 1

    print(f"✅ candidate_id: {args.candidate_id}")
    print(f"✅ conversation_id: {conversation_id}")
    print(f"   name: {candidate.get('name')}")
    print(f"   job_applied: {candidate.get('job_applied')}")
    print(f"   updated_at: {candidate.get('updated_at')}")

    client = load_openai_client()
    conversation = client.conversations.retrieve(conversation_id)
    meta = getattr(conversation, "metadata", {}) or {}
    print(f"\nConversation metadata: {meta}")

    items = list_conversation_items(client, conversation_id)
    print(f"Total items: {len(items)}")

    summarize_items(items, tail=args.tail)

    calls = find_tool_calls(items)
    if calls:
        print("\nTool calls found:")
        for t, name in calls:
            print(f"- {t}: {name}")
    else:
        print("\nNo tool calls found in items.")

    analyze_last_turn(items)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
