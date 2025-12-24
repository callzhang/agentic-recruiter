"""
Test whether the configured OpenAI-compatible endpoint supports Conversations API,
and whether a created conversation_id can be reused with the Responses API.

This mirrors the flow in src/assistant_actions.py:
  - client.conversations.create(...)
  - client.responses.create(conversation=conversation_id, ...)

Usage:
  python scripts/test_openai_conversation_id.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys
from typing import Any, Optional

from dotenv import load_dotenv


def _mask_secret(value: str, keep_start: int = 6, keep_end: int = 4) -> str:
    value = (value or "").strip()
    if len(value) <= keep_start + keep_end:
        return "***"
    return f"{value[:keep_start]}...{value[-keep_end:]}"


def _normalize_base_url(raw: str) -> str:
    base_url = (raw or "").strip()
    while base_url.endswith("/"):
        base_url = base_url[:-1]
    return base_url


def _candidate_base_urls(raw: str) -> list[str]:
    """
    Try a few common shapes:
    - https://host/v1  (OpenAI python SDK default)
    - https://host     (some proxies mount endpoints at root)
    """
    base_url = _normalize_base_url(raw)
    candidates: list[str] = []
    if base_url:
        candidates.append(base_url)
        if base_url.endswith("/v1"):
            candidates.append(base_url[: -len("/v1")])
        else:
            candidates.append(f"{base_url}/v1")
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for u in candidates:
        u = _normalize_base_url(u)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


@dataclass(frozen=True)
class ConversationProbeResult:
    ok: bool
    base_url: str
    model: str
    conversation_id: Optional[str]
    response_id: Optional[str]
    error: Optional[str]


def _probe(base_url: str, api_key: str, model: str) -> ConversationProbeResult:
    try:
        from openai import OpenAI
    except Exception as exc:
        return ConversationProbeResult(
            ok=False,
            base_url=base_url,
            model=model,
            conversation_id=None,
            response_id=None,
            error=f"Failed to import openai SDK: {exc}",
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        # Minimal items list matching assistant_actions.py's shape
        items: list[dict[str, Any]] = [
            {
                "type": "message",
                "role": "developer",
                "content": "你是招聘顾问。请简短回复。",
            },
            {
                "type": "message",
                "role": "user",
                "content": "ping",
            },
        ]
        conversation = client.conversations.create(
            metadata={"probe": "test_openai_conversation_id"},
            items=items,
        )
        # Some non-compliant proxies might return HTML/text; guard for that explicitly.
        if isinstance(conversation, str):
            snippet = conversation.strip().replace("\n", " ")[:180]
            raise RuntimeError(f"conversations.create returned non-JSON text: {snippet}")

        conversation_id = getattr(conversation, "id", None)
        if not conversation_id:
            raise RuntimeError("conversations.create succeeded but returned no id")

        # Verify we can read it back.
        _ = client.conversations.retrieve(conversation_id)

        # Verify Responses can attach to this conversation.
        resp = client.responses.create(
            model=model,
            conversation=conversation_id,
            input="继续。只回答：OK",
            max_output_tokens=16,
        )
        response_id = getattr(resp, "id", None)

        return ConversationProbeResult(
            ok=True,
            base_url=base_url,
            model=model,
            conversation_id=conversation_id,
            response_id=response_id,
            error=None,
        )
    except Exception as exc:
        return ConversationProbeResult(
            ok=False,
            base_url=base_url,
            model=model,
            conversation_id=None,
            response_id=None,
            error=str(exc),
        )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    dotenv_path = repo_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path)
    else:
        load_dotenv()

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    base_url_raw = (os.getenv("OPENAI_BASE_URL") or "").strip()
    model = (
        (os.getenv("OPENAI_MODEL_CONVERSATION") or "").strip()
        or (os.getenv("OPENAI_MODEL") or "").strip()
        or "gpt-5-mini"
    )

    if not api_key:
        print("❌ Missing OPENAI_API_KEY in environment/.env", file=sys.stderr)
        return 2
    if not base_url_raw:
        print("❌ Missing OPENAI_BASE_URL in environment/.env", file=sys.stderr)
        return 2

    print(f"OPENAI_BASE_URL = {base_url_raw}")
    print(f"OPENAI_API_KEY  = {_mask_secret(api_key)}")
    print(f"MODEL           = {model}")

    last: Optional[ConversationProbeResult] = None
    for base_url in _candidate_base_urls(base_url_raw):
        print(f"\n--- Probing Conversations via base_url={base_url} ---")
        last = _probe(base_url=base_url, api_key=api_key, model=model)
        if last.ok:
            print("✅ conversations.create succeeded")
            print(f"conversation_id  = {last.conversation_id}")
            if last.response_id:
                print(f"response.id      = {last.response_id}")
            print("✅ conversation_id reuse with Responses succeeded")
            return 0
        print(f"❌ Failed: {last.error}")

    if last is None:
        print("❌ No base_url candidates to probe.", file=sys.stderr)
        return 2

    print(
        "\nConclusion:\n"
        "- This OPENAI_BASE_URL likely does NOT support the Conversations API endpoints.\n"
        "- If you need conversation_id (as in src/assistant_actions.py), switch to a provider/base_url that supports /conversations.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
