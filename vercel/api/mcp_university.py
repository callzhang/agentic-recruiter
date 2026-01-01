#!/usr/bin/env python3
"""Vercel serverless MCP endpoint: university background lookup.

This hosts a single MCP tool `lookup_university_background` backed by the local
XLSX dataset stored next to this file:
  - `vercel/api/2026_qs_world_university_rankings.xlsx`

Endpoint (prod):
  https://boss-hunter.vercel.app/api/mcp_university
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any


def _load_university_lookup_module():
    """Load `university_lookup.py` from the same directory as this file.

    Vercel's runtime module search path differs between `vercel dev` and deployed
    serverless execution. Loading by absolute file path is the most reliable.
    """
    try:
        here = os.path.dirname(__file__)
        module_path = os.path.join(here, "university_lookup.py")
        if not os.path.exists(module_path):
            return None
        spec = importlib.util.spec_from_file_location("university_lookup", module_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Some stdlib decorators (e.g. @dataclass) expect the module to exist in
        # sys.modules during execution.
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod
    except Exception:
        return None


university_lookup = _load_university_lookup_module()


_SUPPORTED_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
}


def _send_json(handler_obj: BaseHTTPRequestHandler, status_code: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler_obj.send_response(status_code)
    handler_obj.send_header("Content-Type", "application/json; charset=utf-8")
    handler_obj.send_header("Access-Control-Allow-Origin", "*")
    handler_obj.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler_obj.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler_obj.send_header("Content-Length", str(len(body)))
    handler_obj.end_headers()
    handler_obj.wfile.write(body)


def _send_no_content(handler_obj: BaseHTTPRequestHandler, status_code: int = 204) -> None:
    handler_obj.send_response(status_code)
    handler_obj.send_header("Access-Control-Allow-Origin", "*")
    handler_obj.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler_obj.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler_obj.end_headers()


def _rpc_ok(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _rpc_error(rpc_id: Any, code: int, message: str, *, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": err}


def _contains_zh(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "lookup_university_background",
            "title": "University Background Lookup (QS/211/985)",
            "description": (
                "Lookup QS rank (QS 2026) and whether a university is in China's 211/985 lists. "
                "Provide either `school_name_zh`, `school_name_en`, or a single `school_name`."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "school_name": {
                        "type": "string",
                        "description": "School/university name in Chinese or English.",
                    },
                    "school_name_zh": {
                        "type": "string",
                        "description": "School/university name in Chinese.",
                    },
                    "school_name_en": {
                        "type": "string",
                        "description": "School/university name in English.",
                    },
                },
                "additionalProperties": False,
            },
        }
    ]


def _handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = (params or {}).get("protocolVersion") or "2025-06-18"
    protocol_version = requested if requested in _SUPPORTED_PROTOCOL_VERSIONS else "2025-06-18"
    return {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "boss-hunter-university", "version": "1.0.0"},
    }


def _handle_tools_list() -> dict[str, Any]:
    return {"tools": _tool_definitions()}


def _handle_empty_list(kind: str) -> dict[str, Any]:
    return {kind: []}


def _handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    if university_lookup is None:
        raise RuntimeError("university_lookup module unavailable")

    name = (params or {}).get("name") or ""
    args = (params or {}).get("arguments") or {}
    if name != "lookup_university_background":
        raise ValueError(f"Unknown tool: {name}")

    school_name_zh = (args.get("school_name_zh") or "").strip()
    school_name_en = (args.get("school_name_en") or "").strip()
    school_name = (args.get("school_name") or "").strip()

    if not school_name_zh and not school_name_en and school_name:
        if _contains_zh(school_name):
            school_name_zh = school_name
        else:
            school_name_en = school_name

    if not school_name_zh and not school_name_en:
        raise ValueError("Missing school_name / school_name_zh / school_name_en")

    res = university_lookup.lookup_university_background(
        school_name_zh=school_name_zh or None,
        school_name_en=school_name_en or None,
    )
    payload = {
        "input": {
            "school_name": school_name or None,
            "school_name_zh": school_name_zh or None,
            "school_name_en": school_name_en or None,
        },
        "result": res.model_dump(),
    }

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ]
    }


class handler(BaseHTTPRequestHandler):
    """Vercel entrypoint for MCP tool server (streamable HTTP)."""

    def do_OPTIONS(self) -> None:  # noqa: N802
        _send_no_content(self, 204)

    def do_GET(self) -> None:  # noqa: N802
        _send_json(
            self,
            200,
            {
                "ok": True,
                "name": "boss-hunter-university",
                "mcp": True,
                "tools": [t["name"] for t in _tool_definitions()],
                "xlsx_present": os.path.exists(os.path.join(os.path.dirname(__file__), "2026_qs_world_university_rankings.xlsx")),
                "university_lookup_loaded": university_lookup is not None,
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                req = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                _send_json(self, 400, {"error": "invalid_json"})
                return

            method = req.get("method") or ""
            rpc_id = req.get("id", None)
            params = req.get("params") or {}

            # Notifications don't expect a response body.
            if rpc_id is None:
                _send_no_content(self, 204)
                return

            if method == "initialize":
                result = _handle_initialize(params if isinstance(params, dict) else {})
                _send_json(self, 200, _rpc_ok(rpc_id, result))
                return

            if method == "tools/list":
                _send_json(self, 200, _rpc_ok(rpc_id, _handle_tools_list()))
                return

            if method == "resources/list":
                _send_json(self, 200, _rpc_ok(rpc_id, _handle_empty_list("resources")))
                return

            if method == "prompts/list":
                _send_json(self, 200, _rpc_ok(rpc_id, _handle_empty_list("prompts")))
                return

            if method == "ping":
                _send_json(self, 200, _rpc_ok(rpc_id, {}))
                return

            if method == "tools/call":
                if not isinstance(params, dict):
                    _send_json(self, 200, _rpc_error(rpc_id, -32602, "Invalid params"))
                    return
                try:
                    result = _handle_tools_call(params)
                    _send_json(self, 200, _rpc_ok(rpc_id, result))
                except Exception as exc:
                    _send_json(self, 200, _rpc_error(rpc_id, -32000, str(exc)))
                return

            _send_json(self, 200, _rpc_error(rpc_id, -32601, f"Method not found: {method}"))
        except Exception as exc:
            _send_json(self, 500, {"error": f"{type(exc).__name__}: {exc}"})

