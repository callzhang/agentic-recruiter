#!/usr/bin/env python3
"""Generate *fresh* analysis + next message from candidate history for prompt iteration.

Why this script exists
- `download_data_for_prompt_optimization.py` is primarily for dataset export.
- This script is for *fast iteration*: edit prompt/persona files, regenerate outputs,
  and write the generation results into `优化报告.md` for review.

Key behavior
- Uses candidate `history` as the primary context (latest messages).
- Generates:
  1) `analysis` via `ANALYZE_ACTION` (strict JSON Schema = AnalysisSchema)
  2) one next message via `CHAT_ACTION` or `FOLLOWUP_ACTION` (heuristic choice)
- Appends the generation outputs into the run's `优化报告.md`

Prompt sources (choose one)
- Default: `<run_dir>/prompt_optimized.py` (ACTION_PROMPTS dict)
- Optional:  `scripts/prompt_optmization/assistant_actions_prompts.md` (parse fenced blocks)

Run (example)
  python scripts/prompt_optmization/generate_optimized.py \
    --run-dir scripts/prompt_optmization/架构师/run_20251219_161733 \
    --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_openai_config
from src.global_logger import logger
from src.prompts.assistant_actions_prompts import AnalysisSchema, ChatActionSchema

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover

    def tqdm(it, **_kwargs):  # type: ignore
        return it


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_history_role(item: dict[str, Any]) -> str:
    role = (item.get("role") or "").strip().lower()
    if role:
        return role
    msg_type = (item.get("type") or "").strip().lower()
    if msg_type == "candidate":
        return "user"
    if msg_type in {"recruiter", "assistant", "system"}:
        return "assistant"
    return ""


def _format_history(history: list[dict[str, Any]], max_messages: int) -> str:
    if not history:
        return ""
    tail = history[-max(1, max_messages) :]
    lines: list[str] = []
    for item in tail:
        role = _normalize_history_role(item) or "unknown"
        content = (item.get("content") or item.get("message") or "").strip()
        if not content:
            continue
        ts = (item.get("timestamp") or "").strip()
        if ts:
            lines.append(f"[{ts}] {role}: {content}")
        else:
            lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()


def _compact_job_portrait(job_portrait: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "position",
        "target_profile",
        "background",
        "responsibilities",
        "requirements",
        "candidate_filters",
        "drill_down_questions",
        "followup_questions",
        "keywords",
        "description",
        "prompt_optimization_notes",
        "base_job_id",
        "job_id",
    ]
    out: dict[str, Any] = {}
    for k in keys:
        if k in job_portrait:
            out[k] = job_portrait.get(k)
    return out or dict(job_portrait)


def _extract_first_json_object(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    stack = 0
    end = None
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            stack += 1
        elif ch == "}":
            stack -= 1
            if stack == 0:
                end = i + 1
                break
    if end is None:
        return None
    blob = text[start:end]
    try:
        obj = json.loads(blob)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _load_action_prompts_from_python(path: Path) -> dict[str, str]:
    import ast

    tree = ast.parse(_read_text(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "ACTION_PROMPTS":
                value = ast.literal_eval(node.value)
                if isinstance(value, dict):
                    return {str(k): str(v) for k, v in value.items()}
    raise RuntimeError(f"Failed to load ACTION_PROMPTS from: {path}")


def _load_action_prompts_from_md(path: Path) -> dict[str, str]:
    """Parse scripts/prompt_optmization/assistant_actions_prompts.md."""

    text = _read_text(path)
    prompts: dict[str, str] = {}
    # Sections look like: "## CHAT_ACTION" followed by fenced block.
    pattern = re.compile(r"^##\\s+([A-Z0-9_]+)\\s*$", re.M)
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        key = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end]
        fence = re.search(r"```\\s*\\n(.*?)\\n```", chunk, re.S)
        if not fence:
            continue
        prompts[key] = fence.group(1).strip()
    if not prompts:
        raise RuntimeError(f"No prompts parsed from: {path}")
    return prompts


def _clip(text: str, max_chars: int) -> str:
    s = (text or "").strip()
    if max_chars <= 0:
        return s
    return s if len(s) <= max_chars else (s[:max_chars] + "…")


def _choose_message_action(history: list[dict[str, Any]]) -> str:
    """Heuristic: if last message is from assistant, generate a follow-up; else chat."""

    if not history:
        return "CHAT_ACTION"
    last_role = _normalize_history_role(history[-1]) or ""
    return "FOLLOWUP_ACTION" if last_role == "assistant" else "CHAT_ACTION"


def _build_analyze_instructions(analyze_prompt: str) -> str:
    base = (analyze_prompt or "").strip()
    contract = """

【输出格式（强制）】
- 只输出一个 JSON 对象，不要 markdown，不要代码块，不要多余文字。
- JSON 字段必须且只能包含：
  - skill (int, 1-10)
  - startup_fit (int, 1-10)
  - background (int, 1-10)
  - overall (int, 1-10)
  - summary (str)
  - followup_tips (str)
"""
    return (base + contract).strip()


def _gen_analysis(
    client: Any,
    model: str,
    analyze_prompt: str,
    job_portrait: dict[str, Any],
    resume: str,
    history: list[dict[str, Any]],
    history_max_messages: int,
    resume_max_chars: int,
) -> Optional[dict[str, Any]]:
    instructions = _build_analyze_instructions(analyze_prompt)
    payload = "\n\n".join(
        [
            "【岗位肖像】",
            json.dumps(_compact_job_portrait(job_portrait), ensure_ascii=False, indent=2),
            "",
            "【候选人简历】",
            _clip(resume, resume_max_chars),
            "",
            "【对话记录（截取最近若干条）】",
            _format_history(history, max_messages=history_max_messages) or "(无)",
        ]
    ).strip()

    try:
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=payload,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "AnalysisSchema",
                    "schema": AnalysisSchema.model_json_schema(),
                    "strict": True,
                },
            },
        )
        obj = _extract_first_json_object(getattr(resp, "output_text", "") or "")
    except TypeError:
        obj = None
    except Exception as exc:
        logger.warning("analysis call failed, fallback to text parse: %s", exc)
        obj = None

    if obj is None:
        try:
            resp = client.responses.create(
                model=model,
                instructions=instructions,
                input=payload,
            )
        except Exception as exc:
            logger.error("analysis call failed: %s", exc)
            return None
        obj = _extract_first_json_object(getattr(resp, "output_text", "") or "")

    if obj is None:
        return None
    try:
        parsed = AnalysisSchema.model_validate(obj)
    except Exception:
        return None
    return parsed.model_dump()


def _gen_message(
    client: Any,
    model: str,
    action_prompt: str,
    job_portrait: dict[str, Any],
    resume: str,
    analysis: Optional[dict[str, Any]],
    history: list[dict[str, Any]],
    history_max_messages: int,
    resume_max_chars: int,
) -> Optional[dict[str, Any]]:
    instructions = (action_prompt or "").strip()
    payload = "\n\n".join(
        [
            "【岗位肖像】",
            json.dumps(_compact_job_portrait(job_portrait), ensure_ascii=False, indent=2),
            "",
            "【候选人简历】",
            _clip(resume, resume_max_chars),
            "",
            "【候选人分析（仅供你组织语言，不要原样复述评分表）】",
            json.dumps(analysis or {}, ensure_ascii=False, indent=2),
            "",
            "【对话记录（截取最近若干条）】",
            _format_history(history, max_messages=history_max_messages) or "(无)",
        ]
    ).strip()
    try:
        resp = client.responses.parse(
            model=model,
            instructions=instructions,
            input=payload,
            text_format=ChatActionSchema,
        )
    except Exception as exc:
        logger.error("message call failed: %s", exc)
        return None
    parsed = getattr(resp, "output_parsed", None)
    if not parsed:
        return None
    return parsed.model_dump()


def _simple_message_checks(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    qmarks = s.count("?") + s.count("？")
    salary = bool(re.search(r"(薪资|薪酬|年包|月薪|预付|\\b\\d{2,3}k\\b|k/\\s*月)", s, re.I))
    material = bool(re.search(r"(代码|PR|pull request|仓库|repo|链接|文档|架构图|设计文档|截图|附件)", s, re.I))
    # Scheduling is only a risk when the assistant tries to pick/confirm specifics.
    # Mentioning "由HR确认" is acceptable and should not be flagged as scheduling risk.
    explicit_time = bool(
        re.search(
            r"(\\b\\d{1,2}\\s*[:：]\\s*\\d{2}\\b|\\b\\d{1,2}\\s*点\\b|今天|明天|后天|今晚|本周|下周|周[一二三四五六日天])",
            s,
            re.I,
        )
    )
    scheduling_ctx = bool(re.search(r"(面试|通话|视频|会议|线上|线下|地点|Zoom|腾讯会议)", s, re.I))
    hr_confirm = "由HR确认" in s or "由 hr 确认" in s.lower() or "由hr统一" in s.lower()
    scheduling = (explicit_time and scheduling_ctx) or (scheduling_ctx and not hr_confirm and "安排" in s)
    return {
        "len": len(s),
        "qmarks": qmarks,
        "salary_like": salary,
        "material_like": material,
        "scheduling_like": scheduling,
    }


def _append_generation_to_report(report_path: Path, section_md: str) -> None:
    marker_start = "<!-- generate_optimized:begin -->"
    marker_end = "<!-- generate_optimized:end -->"
    existing = _read_text(report_path) if report_path.exists() else ""

    if marker_start in existing and marker_end in existing:
        before = existing.split(marker_start, 1)[0].rstrip()
        after = existing.split(marker_end, 1)[1].lstrip()
        merged = "\n".join([before, marker_start, section_md.strip(), marker_end, after]).strip() + "\n"
        _write_text(report_path, merged)
        return

    appended = "\n".join(
        [
            existing.rstrip(),
            "",
            marker_start,
            section_md.strip(),
            marker_end,
            "",
        ]
    ).strip() + "\n"
    _write_text(report_path, appended)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, help="Run directory path (contains candidates/ + job_portrait_optimized.json)")
    parser.add_argument(
        "--prompt-source",
        default="md",
        choices=["optimized_py", "md"],
        help="Where to load ACTION_PROMPTS from (default: scripts/prompt_optmization/assistant_actions_prompts.md)",
    )
    parser.add_argument(
        "--assistant-prompts-md",
        default=str(Path("scripts") / "prompt_optmization" / "assistant_actions_prompts.md"),
        help="Path to assistant_actions_prompts.md (used when --prompt-source=md)",
    )
    parser.add_argument("--model", default=None, help="Override OpenAI model (default: config model)")
    parser.add_argument("--limit", type=int, default=0, help="Max candidates to process (0=all)")
    parser.add_argument("--history-max-messages", type=int, default=20, help="How many history messages to include")
    parser.add_argument("--resume-max-chars", type=int, default=8000, help="Clip resume to this many chars for generation")
    parser.add_argument("--start-index", type=int, default=1, help="1-based start index within sorted candidates files")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    candidates_dir = run_dir / "candidates"
    if not candidates_dir.exists():
        raise SystemExit(f"candidates dir not found: {candidates_dir}")

    job_portrait_path = run_dir / "job_portrait_optimized.json"
    if not job_portrait_path.exists():
        raise SystemExit(f"job_portrait_optimized.json not found: {job_portrait_path}")
    job_portrait = json.loads(_read_text(job_portrait_path))

    if args.prompt_source == "optimized_py":
        prompt_py = run_dir / "prompt_optimized.py"
        if not prompt_py.exists():
            raise SystemExit(f"prompt_optimized.py not found: {prompt_py}")
        prompts = _load_action_prompts_from_python(prompt_py)
    else:
        prompts = _load_action_prompts_from_md(Path(args.assistant_prompts_md))

    if OpenAI is None:
        raise SystemExit("openai sdk not installed/available")
    openai_config = get_openai_config()
    api_key = openai_config.get("api_key")
    base_url = openai_config.get("base_url")
    model = args.model or openai_config.get("model")
    if not api_key or not model:
        raise SystemExit("OpenAI config missing api_key or model")
    client = OpenAI(api_key=api_key, base_url=base_url)

    candidate_files = sorted(candidates_dir.glob("*.json"))
    if args.start_index > 1:
        candidate_files = candidate_files[args.start_index - 1 :]
    if args.limit and args.limit > 0:
        candidate_files = candidate_files[: args.limit]

    out_dir = run_dir / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = run_dir / "优化报告.md"
    now = datetime.now().isoformat(timespec="seconds")
    section: list[str] = [
        "## 模型生成回放（generate_optimized.py）",
        "",
        f"- 生成时间: {now}",
        f"- run_dir: `{run_dir}`",
        f"- prompt_source: `{args.prompt_source}`",
        f"- model: `{model}`",
        f"- history_max_messages: {args.history_max_messages}",
        f"- resume_max_chars: {args.resume_max_chars}",
        "",
    ]

    for idx, path in enumerate(tqdm(candidate_files, desc="Generate", total=len(candidate_files)), start=args.start_index):
        data = json.loads(_read_text(path))
        name = data.get("name") or "unknown"
        conversation_id = data.get("conversation_id") or ""
        resume = data.get("resume") or ""
        history = data.get("history") or []

        analyze_prompt = prompts.get("ANALYZE_ACTION") or ""
        analysis = _gen_analysis(
            client,
            model=str(model),
            analyze_prompt=analyze_prompt,
            job_portrait=job_portrait,
            resume=resume,
            history=history,
            history_max_messages=args.history_max_messages,
            resume_max_chars=args.resume_max_chars,
        )

        msg_action = _choose_message_action(history)
        msg_prompt = prompts.get(msg_action) or prompts.get("CHAT_ACTION") or ""
        msg_obj = _gen_message(
            client,
            model=str(model),
            action_prompt=msg_prompt,
            job_portrait=job_portrait,
            resume=resume,
            analysis=analysis,
            history=history,
            history_max_messages=args.history_max_messages,
            resume_max_chars=args.resume_max_chars,
        )
        message_text = ""
        action_out = None
        reason_out = None
        if isinstance(msg_obj, dict):
            action_out = msg_obj.get("action")
            reason_out = msg_obj.get("reason")
            message_text = (msg_obj.get("message") or "").strip()
        checks = _simple_message_checks(message_text)

        out_payload = {
            "generated_at": now,
            "candidate_file": str(path),
            "name": name,
            "conversation_id": conversation_id,
            "message_action": msg_action,
            "message": message_text,
            "message_obj": msg_obj,
            "message_checks": checks,
            "analysis": analysis,
        }
        out_path = out_dir / f"{path.stem}.generated.json"
        _write_json(out_path, out_payload)

        section += [
            f"### 回放 {idx}. {name}",
            "",
            f"- candidate_file: `{path.name}`",
            f"- conversation_id: `{conversation_id}`",
            f"- message_action: `{msg_action}`",
            f"- message_checks: len={checks['len']}, qmarks={checks['qmarks']}, salary_like={checks['salary_like']}, scheduling_like={checks['scheduling_like']}, material_like={checks['material_like']}",
            f"- generated_json: `{out_path.relative_to(run_dir)}`",
            "",
            "**生成的 message（可直接发给候选人）**",
            "",
            "```",
            (message_text or "[生成失败]").strip(),
            "```",
            "",
            "**生成的 chat JSON（内部）**",
            "",
            "```json",
            json.dumps(msg_obj or {"error": "chat_generation_failed"}, ensure_ascii=False, indent=2),
            "```",
            "",
            "**生成的 analysis（JSON）**",
            "",
            "```json",
            json.dumps(analysis or {"error": "analysis_generation_failed"}, ensure_ascii=False, indent=2),
            "```",
            "",
            "**人工评价（写在这里，便于下一轮改 prompt/画像）**",
            "",
            "- message 是否合规（不约时间/不聊薪资/不索要材料/<=160字/问号数）:",
            "- message 是否“更容易回复”（一句主问题，开放）:",
            "- analysis 是否结构化、是否避免伪高P、评分是否自洽:",
            "- 需要改 prompt 的点（写到 assistant_actions_prompts.md 或 prompt_optimized.py）:",
            "- 需要改画像/追问库（写到 job_portrait_optimized.json）:",
            "",
        ]

    _append_generation_to_report(report_path, "\n".join(section))
    logger.info("Wrote/updated report: %s", report_path)
    logger.info("Generated outputs dir: %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
