#!/usr/bin/env python3
"""Smoke test: OpenAI Responses API + MCP university lookup tool.

This script helps confirm that:
1) OpenAI Responses API can reach our MCP server URL
2) The model actually performs a tool call

Requirements:
- Configure OpenAI creds in `config/secrets.yaml` (preferred) or env vars.
- Ensure `config/config.yaml` includes `openai.university_mcp_server_url`
  (defaults to https://boss-hunter.vercel.app/api/mcp_university).

Run:
  python scripts/test_mcp_university_tool.py --school "清华大学"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.config import get_openai_config


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return json.dumps({"unserializable": str(obj)}, ensure_ascii=False, indent=2)


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of tool calls from an OpenAI Responses object."""
    calls: list[dict[str, Any]] = []

    output = getattr(response, "output", None) or []
    for item in output:
        item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
        if not item_type:
            continue

        # Common patterns: "tool_call", "mcp_call" (varies by SDK/runtime)
        if "tool" in str(item_type) or "mcp" in str(item_type):
            if hasattr(item, "model_dump"):
                calls.append(item.model_dump())
            elif isinstance(item, dict):
                calls.append(item)
            else:
                calls.append({"type": str(item_type), "repr": repr(item)})

    # Fallback: scan serialized response for the tool name string.
    if not calls:
        try:
            raw = response.model_dump() if hasattr(response, "model_dump") else {}
            s = json.dumps(raw, ensure_ascii=False, default=str)
            if "lookup_university_background" in s:
                calls.append({"detected": "lookup_university_background", "note": "found in response dump"})
        except Exception:
            pass

    return calls


def _summarize_output_items(response: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in getattr(response, "output", None) or []:
        if hasattr(item, "model_dump"):
            raw = item.model_dump()
        elif isinstance(item, dict):
            raw = item
        else:
            raw = {"repr": repr(item)}
        out.append(
            {
                "type": raw.get("type"),
                "id": raw.get("id"),
                "name": raw.get("name"),
                "server_label": raw.get("server_label"),
                "status": raw.get("status"),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school", required=True, help="School name (zh/en), e.g. 清华大学")
    parser.add_argument("--model", default=None, help="Override model")
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="Override MCP server url (must be publicly reachable by OpenAI servers)",
    )
    parser.add_argument("--server-label", default="UniversityDB", help="MCP server_label to use")
    parser.add_argument("--verbose", action="store_true", help="Print full response dump (can be large)")
    args = parser.parse_args()

    openai_config = get_openai_config()
    api_key = openai_config.get("api_key") or os.getenv("OPENAI_API_KEY")
    base_url = openai_config.get("base_url") or os.getenv("OPENAI_BASE_URL")
    model = args.model or openai_config.get("model")

    if not api_key:
        raise SystemExit("Missing OpenAI API key (config/secrets.yaml openai.api_key or env OPENAI_API_KEY).")
    if not model:
        raise SystemExit("Missing OpenAI model (config/config.yaml openai.model or --model).")

    mcp_url = (
        args.mcp_url
        or os.getenv("UNIVERSITY_MCP_SERVER_URL")
        or openai_config.get("university_mcp_server_url")
    )
    if not mcp_url:
        raise SystemExit(
            "Missing MCP url. Set config/config.yaml openai.university_mcp_server_url "
            "or env UNIVERSITY_MCP_SERVER_URL or pass --mcp-url."
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    instructions = (
        "You are testing an MCP tool integration.\n"
        "You MUST call the MCP tool `lookup_university_background` exactly once.\n"
        "Call it with arguments: {\"school_name\": \"<the provided school>\"}.\n"
        "Then return a short plain-text confirmation that includes the tool result fields "
        "(qs_rank, is_211, is_985).\n"
        "If the tool call fails, say 'TOOL_CALL_FAILED' and include the error.\n"
    )

    user_input = f"School: {args.school}"

    tools = [
        {
            "type": "mcp",
            "server_url": str(mcp_url).strip(),
            "server_label": str(args.server_label).strip(),
            "allowed_tools": ["lookup_university_background"],
            "require_approval": "never",
        },
    ]

    print("=== Config ===")
    print(_safe_json({"model": model, "base_url": base_url, "mcp_url": mcp_url, "server_label": args.server_label}))

    try:
        response = client.responses.create(
            model=str(model),
            instructions=instructions,
            input=user_input,
            tools=tools,
            max_tool_calls=1,
            tool_choice={
                "type": "mcp",
                "server_label": str(args.server_label).strip(),
                "name": "lookup_university_background",
            },
        )
    except Exception as exc:
        print("\n=== OpenAI Error ===")
        print(f"type: {type(exc).__name__}")
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code is not None:
            print(f"status_code: {status_code}")
        body = getattr(exc, "body", None)
        if body is not None:
            print("body:")
            print(_safe_json(body))
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                print("response_text:")
                print(resp.text)
            except Exception:
                pass
        raise

    print("\n=== Output Text ===")
    print(getattr(response, "output_text", "") or "(空)")

    print("\n=== Output Items (summary) ===")
    print(_safe_json(_summarize_output_items(response)))

    print("\n=== Tool Calls (best-effort) ===")
    print(_safe_json(_extract_tool_calls(response)))

    if args.verbose:
        print("\n=== Full Response Dump ===")
        if hasattr(response, "model_dump"):
            print(_safe_json(response.model_dump()))
        else:
            print(repr(response))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
