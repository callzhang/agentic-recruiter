#!/usr/bin/env python3
"""Prepare a prompt-optimization dataset and a single-batch report scaffold.

Design goals (per iteration workflow):
- Each run produces ONE batch (default: 10 newest valid candidates).
- Each run creates a NEW run folder (no per-day de-dup).
- The report includes a lightweight comparison with the previous run for the same job
  (to check whether last iteration's prompt/portrait changes were effective).

Run:
  python scripts/prompt_optmization/download_data_for_prompt_optimization.py --job-position 架构师
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Optional

# Add repo root to path to import modules (same pattern as other scripts/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.global_logger import logger
from src.prompts.assistant_actions_prompts import ACTION_PROMPTS, AnalysisSchema

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    def tqdm(it, **_kwargs):  # type: ignore
        return it


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _safe_dirname(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "unknown_job"
    safe = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", name)
    safe = safe.strip("_")
    return safe or "unknown_job"


def _safe_filename(name: str) -> str:
    name = (name or "").strip()
    safe = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", name)
    safe = safe.strip("_")
    return safe or "unknown"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _list_run_dirs(job_dir: Path) -> list[Path]:
    runs = [p for p in job_dir.glob("run_*") if p.is_dir()]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs


def _read_distribution_txt(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    stats: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        if k in {"Total candidates", "With overall", "Missing overall"}:
            try:
                stats[k] = int(v)
            except Exception:
                stats[k] = v
        elif k in {"Mean", "Median", "Min", "Max"}:
            try:
                stats[k] = float(v)
            except Exception:
                stats[k] = v
        elif k.startswith("Ratio"):
            try:
                stats[k] = float(v)
            except Exception:
                stats[k] = v
    return stats


def _analysis_compliance_stats(candidates: list["CandidateExport"]) -> dict[str, Any]:
    """Heuristic check: whether new prompt rules are visible in stored analysis."""

    def _has_scorecard(summary: str) -> bool:
        # New prompt asks for "门槛=...,场景=...,基础=...,契合=...,潜力=...(+..),总分=..../100=>..../10"
        s = (summary or "").replace(" ", "")
        return all(x in s for x in ("门槛=", "场景=", "基础=", "契合=", "潜力=", "总分="))

    def _has_persona(summary: str) -> bool:
        s = (summary or "").replace(" ", "")
        return all(x in s for x in ("技术深度=", "抽象能力=", "机制化=", "建议="))

    total = len(candidates)
    scorecard = 0
    persona = 0
    for c in candidates:
        summary = (c.analysis or {}).get("summary") or ""
        if _has_scorecard(summary):
            scorecard += 1
        if _has_persona(summary):
            persona += 1
    return {
        "count": total,
        "scorecard_in_summary": scorecard,
        "persona_in_summary": persona,
        "scorecard_ratio": (scorecard / total) if total else 0.0,
        "persona_ratio": (persona / total) if total else 0.0,
    }


def _chat_policy_risk_stats(candidates: list["CandidateExport"]) -> dict[str, Any]:
    """Heuristic checks on stored chat history (not regenerated in this script)."""

    salary_keywords = ["薪资", "待遇", "年包", "月薪", "预付", "结算", "发薪", "offer", "入职"]
    material_keywords = ["代码", "PR", "仓库", "repo", "链接", "架构图", "流程图", "设计文档", "文档", "截图", "DDL", "日志"]

    # Scheduling: require a time-ish hint + a scheduling context hint.
    time_re = re.compile(r"(\b\d{1,2}\s*[:：]\s*\d{2}\b|\b\d{1,2}\s*[-~到]\s*\d{1,2}\s*点\b|\b(今天|明天|后天|今晚|本周|下周|周[一二三四五六日天])\b|\b(上午|下午|晚上)\b|\b\d{1,2}\s*点\b)")
    ctx_re = re.compile(r"(面试|通话|短聊|约|安排|视频|线下|线上|地点|会议|已确认|Zoom|Teams|钉钉)")

    salary_msgs: list[tuple[str, str]] = []
    material_msgs: list[tuple[str, str]] = []
    scheduling_msgs: list[tuple[str, str]] = []

    def _hit_any(text: str, keys: list[str]) -> Optional[str]:
        for k in keys:
            if k and k in text:
                return k
        return None

    for idx, c in enumerate(candidates, start=1):
        for m in c.history or []:
            if (m.get("role") or "") != "assistant":
                continue
            text = (m.get("content") or "").strip()
            if not text:
                continue

            if _hit_any(text, salary_keywords):
                salary_msgs.append((f"{idx:03d}_{c.name}", text[:80].replace("\n", " ")))
            if _hit_any(text, material_keywords):
                material_msgs.append((f"{idx:03d}_{c.name}", text[:80].replace("\n", " ")))
            if time_re.search(text) and ctx_re.search(text):
                scheduling_msgs.append((f"{idx:03d}_{c.name}", text[:80].replace("\n", " ")))

    return {
        "salary_messages": len(salary_msgs),
        "material_request_messages": len(material_msgs),
        "scheduling_messages": len(scheduling_msgs),
        "salary_examples": salary_msgs[:8],
        "material_examples": material_msgs[:8],
        "scheduling_examples": scheduling_msgs[:8],
    }


def _read_json_if_exists(path: Optional[Path]) -> Optional[dict[str, Any]]:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_latest_matching(run_dir: Path, pattern: str) -> Optional[Path]:
    matches = sorted(run_dir.glob(pattern))
    if not matches:
        return None
    # Prefer highest numeric suffix for legacy batch files.
    best: Optional[Path] = None
    best_n = -1
    for p in matches:
        m = re.search(r"_(\d+)\.(py|json)$", p.name)
        n = int(m.group(1)) if m else 0
        if n >= best_n:
            best_n = n
            best = p
    return best or matches[-1]


def _load_action_prompts_from_python(path: Path) -> Optional[dict[str, str]]:
    """Load ACTION_PROMPTS from a python file via AST literal eval (no execution)."""

    try:
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "ACTION_PROMPTS":
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict):
                            return {str(k): str(v) for k, v in value.items()}
    except Exception:
        return None
    return None


def _load_previous_optimized_baseline(previous_run_dir: Optional[Path]) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Return (action_prompts, job_portrait_optimized_or_none) from previous run if available."""

    if not previous_run_dir:
        return dict(ACTION_PROMPTS), None

    # Prompt baseline (preferred order):
    # 1) prompt_optimized.py (new rolling name)
    # 2) prompt_batch_*.py (legacy batch names)
    prompt_path = previous_run_dir / "prompt_optimized.py"
    prompts = _load_action_prompts_from_python(prompt_path) if prompt_path.exists() else None
    if not prompts:
        legacy_prompt = _find_latest_matching(previous_run_dir, "prompt_batch_*.py")
        if legacy_prompt:
            prompts = _load_action_prompts_from_python(legacy_prompt)

    # Job portrait baseline (preferred order):
    # 1) job_portrait_optimized.json (new rolling name)
    # 2) job_protrait_batch_*.json (legacy misspelling)
    job_portrait = _read_json_if_exists(previous_run_dir / "job_portrait_optimized.json")
    if job_portrait is None:
        legacy_job = _find_latest_matching(previous_run_dir, "job_protrait_batch_*.json")
        job_portrait = _read_json_if_exists(legacy_job) if legacy_job else None

    return prompts or dict(ACTION_PROMPTS), job_portrait


def _write_prompt_optimized_py(path: Path, prompts: dict[str, str]) -> None:
    """Write a full optimized prompt file (complete content, not a patch)."""

    payload = "\n".join(
        [
            "# Generated by scripts/prompt_optmization/download_data_for_prompt_optimization.py",
            "# Rolling optimized prompt (edit this file; next run will use it as baseline)",
            "",
            "from __future__ import annotations",
            "",
            "ACTION_PROMPTS = " + json.dumps(prompts, ensure_ascii=False, indent=2),
            "",
        ]
    )
    _write_text(path, payload)


def _write_job_portrait_optimized_json(path: Path, job_portrait: dict[str, Any]) -> None:
    """Write a full optimized job portrait json (complete content, not a patch)."""

    payload = dict(job_portrait)
    notes = payload.get("prompt_optimization_notes") if isinstance(payload.get("prompt_optimization_notes"), dict) else {}
    notes = dict(notes)
    notes["generated_at"] = datetime.now().isoformat(timespec="seconds")
    notes["single_batch_mode"] = True
    notes["rolling_mode"] = True
    payload["prompt_optimization_notes"] = notes
    _write_json(path, payload)


def _parse_history_last_timestamp(history: list[dict[str, Any]]) -> Optional[datetime]:
    if not history:
        return None
    last = history[-1] or {}
    ts = (last.get("timestamp") or "").strip()
    if not ts:
        return None
    try:
        # Stored format in metadata.history: "YYYY-MM-DD HH:MM:SS"
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        # Best-effort fallback (accept ISO variants)
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateExport:
    name: str
    conversation_id: str
    resume: str
    analysis: dict[str, Any]
    history: list[dict[str, Any]]
    candidate_id: str | None = None
    updated_at: str | None = None
    job_applied: str | None = None
    last_history_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "conversation_id": self.conversation_id,
            "resume": self.resume,
            "analysis": self.analysis,
            "history": self.history,
            "candidate_id": self.candidate_id,
            "updated_at": self.updated_at,
            "job_applied": self.job_applied,
            "last_history_at": self.last_history_at,
        }


@dataclass(frozen=True)
class ExcludedCandidate:
    name: str
    conversation_id: str
    candidate_id: str | None
    updated_at: str | None
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "conversation_id": self.conversation_id,
            "candidate_id": self.candidate_id,
            "updated_at": self.updated_at,
            "reasons": self.reasons,
        }


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


def _has_assistant_dialogue(history: list[dict[str, Any]]) -> bool:
    for item in history or []:
        role = _normalize_history_role(item)
        content = (item.get("content") or item.get("message") or "").strip()
        if role == "assistant" and content:
            return True
    return False


def _resume_loaded(resume: str, min_len: int = 100) -> bool:
    text = (resume or "").strip()
    if len(text) < min_len:
        return False
    if "正在加载在线简历" in text or text.startswith("⏳"):
        return False
    return True


def _has_valid_analysis(analysis: dict[str, Any]) -> bool:
    if not analysis:
        return False
    return any(k in analysis for k in ("overall", "skill", "startup_fit", "background", "summary"))


def _should_exclude_candidate(
    resume: str,
    analysis: dict[str, Any],
    history: list[dict[str, Any]],
    min_resume_len: int = 100,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not _resume_loaded(resume, min_len=min_resume_len):
        reasons.append(f"resume_not_loaded_or_too_short(<{min_resume_len})")
    if not _has_valid_analysis(analysis):
        reasons.append("missing_or_empty_analysis")
    if not _has_assistant_dialogue(history):
        reasons.append("no_assistant_dialogue_in_history")
    return (len(reasons) > 0), reasons


# ---------------------------------------------------------------------------
# Step 1: pick job + create run dir
# ---------------------------------------------------------------------------


def step1_select_job_and_create_run_dir(
    prompt_opt_dir: Path,
    job_id: Optional[str],
    job_position: Optional[str],
) -> tuple[dict[str, Any], Path, Path, Optional[Path]]:
    """Get all jobs, pick one, create a new run folder, and save job_portrait.json."""

    from src.jobs_store import get_all_jobs, get_job_by_id

    job: Optional[dict[str, Any]] = None
    if job_id:
        job = get_job_by_id(job_id)
        if not job:
            raise RuntimeError(f"Job not found by id: {job_id}")
    else:
        jobs = get_all_jobs()
        if not jobs:
            raise RuntimeError("No jobs found in jobs store")

        candidates = jobs
        if job_position:
            keyword = job_position.strip()
            candidates = [
                j
                for j in jobs
                if keyword in (j.get("position") or "") or keyword in (j.get("base_job_id") or "")
            ]
            if not candidates:
                raise RuntimeError(f"No jobs matched --job-position={job_position!r}")

        if len(candidates) == 1:
            job = candidates[0]
        else:
            logger.info("Multiple jobs matched. Please select one:")
            for i, j in enumerate(candidates, start=1):
                logger.info(
                    "%s) position=%s base_job_id=%s job_id=%s updated_at=%s",
                    i,
                    j.get("position"),
                    j.get("base_job_id"),
                    j.get("job_id"),
                    j.get("updated_at"),
                )
            selection = input(f"Select job [1-{len(candidates)}]: ").strip()
            idx = int(selection) - 1
            if idx < 0 or idx >= len(candidates):
                raise RuntimeError("Invalid selection")
            job = candidates[idx]

    assert job is not None

    position = job.get("position") or job.get("base_job_id") or "unknown_job"
    job_dir = prompt_opt_dir / _safe_dirname(position)
    job_dir.mkdir(parents=True, exist_ok=True)

    previous_run_dir: Optional[Path] = None
    existing = _list_run_dirs(job_dir)
    if existing:
        previous_run_dir = existing[0]

    run_name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = job_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    job_profile_path = run_dir / "job_portrait.json"
    _write_json(job_profile_path, job)

    logger.info("Saved job portrait: %s", job_profile_path)
    if previous_run_dir:
        logger.info("Previous run dir: %s", previous_run_dir)

    return job, run_dir, job_profile_path, previous_run_dir


# ---------------------------------------------------------------------------
# Step 2: fetch N newest candidates (valid only)
# ---------------------------------------------------------------------------


def step2_fetch_recent_candidates_and_save(
    job: dict[str, Any],
    run_dir: Path,
    batch_size: int = 10,
    fetch_multiplier: int = 5,
) -> list[CandidateExport]:
    """Fetch newest candidates and save one json per candidate.

    Note: to get *valid* N samples, we fetch N*multiplier then filter by
    resume/analysis/dialogue availability.
    """

    from src.candidate_store import search_candidates_advanced

    job_applied = job.get("position") or ""
    if not job_applied:
        raise RuntimeError("Job position is empty; cannot filter candidates by job_applied")

    # We want the newest conversations by metadata.history[-1].timestamp, but Milvus
    # cannot sort by nested JSON fields. We therefore:
    # 1) fetch N * fetch_multiplier raw candidates (sorted by updated_at as a proxy),
    #    including metadata.history so we can compute history[-1].timestamp locally;
    # 2) sort locally by history[-1].timestamp desc and pick the newest ones.
    target_size = min(batch_size, 50)
    raw_limit = max(target_size, target_size * max(1, fetch_multiplier))

    # Phase 1: fetch raw candidates with metadata so we can rank by history timestamp.
    raw_fields = ["candidate_id", "name", "conversation_id", "metadata", "updated_at", "job_applied"]
    try:
        raw_candidates = search_candidates_advanced(
            job_applied=job_applied,
            limit=raw_limit,
            sort_by="updated_at",
            sort_direction="desc",
            fields=raw_fields,
            strict=True,
        )
        logger.info(
            "Fetched %d raw candidates (with metadata) for job_applied=%s (raw_limit=%d)",
            len(raw_candidates),
            job_applied,
            raw_limit,
        )
    except Exception as exc:
        # Fallback: older clusters/settings may reject large metadata payloads.
        logger.exception("Failed to fetch raw candidates with metadata; falling back to header-only: %s", exc)
        list_fields = ["candidate_id", "name", "conversation_id", "updated_at", "job_applied"]
        raw_candidates = search_candidates_advanced(
            job_applied=job_applied,
            limit=raw_limit,
            sort_by="updated_at",
            sort_direction="desc",
            fields=list_fields,
            strict=True,
        )
        logger.info(
            "Fetched %d candidate headers for job_applied=%s (raw_limit=%d)",
            len(raw_candidates),
            job_applied,
            raw_limit,
        )
        meta_fields = ["candidate_id", "metadata", "updated_at"]
        enriched: list[dict[str, Any]] = []
        for header in tqdm(raw_candidates, desc="Fetch metadata (fallback)", total=len(raw_candidates)):
            candidate_id = header.get("candidate_id")
            if not candidate_id:
                continue
            rows = search_candidates_advanced(candidate_ids=[candidate_id], limit=1, fields=meta_fields, strict=True)
            c = rows[0] if rows else {}
            merged = dict(header)
            merged["metadata"] = c.get("metadata")
            enriched.append(merged)
        raw_candidates = enriched

    candidates_dir = run_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    exports: list[CandidateExport] = []
    excluded: list[ExcludedCandidate] = []

    # Rank by metadata.history[-1].timestamp desc, and keep only candidates with dialogue.
    ranked: list[tuple[datetime, dict[str, Any]]] = []
    for c in raw_candidates:
        candidate_id = c.get("candidate_id")
        if not candidate_id:
            continue
        metadata = c.get("metadata") or {}
        history = metadata.get("history") or []
        last_dt = _parse_history_last_timestamp(history)
        if not last_dt:
            excluded.append(
                ExcludedCandidate(
                    name=(c.get("name") or "").strip() or "unknown",
                    conversation_id=(c.get("conversation_id") or "").strip(),
                    candidate_id=candidate_id,
                    updated_at=c.get("updated_at"),
                    reasons=["no_history_timestamp"],
                )
            )
            continue
        ranked.append((last_dt, c))

    ranked.sort(key=lambda x: x[0], reverse=True)
    ranked = ranked[:target_size]

    detail_fields = [
        "candidate_id",
        "name",
        "conversation_id",
        "resume_text",
        "full_resume",
        "analysis",
        "metadata",
        "updated_at",
        "job_applied",
    ]

    # Phase 2: download selected candidates' details.
    # Default to small batches to avoid 4MB gRPC response limit.
    candidate_ids = [c.get("candidate_id") for _dt, c in ranked if c.get("candidate_id")]
    chunk_size = 5

    def _chunks(items: list[str], size: int) -> list[list[str]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    chunks = _chunks(candidate_ids, max(1, min(chunk_size, len(candidate_ids))))
    fetched: dict[str, dict[str, Any]] = {}
    for chunk in tqdm(chunks, desc="Download candidates", total=len(chunks)):
        try:
            rows = search_candidates_advanced(candidate_ids=chunk, limit=len(chunk), fields=detail_fields, strict=False)
        except Exception:
            # Fallback to one-by-one within this chunk.
            rows = []
            for cid in chunk:
                try:
                    one = search_candidates_advanced(candidate_ids=[cid], limit=1, fields=detail_fields, strict=True)
                    if one:
                        rows.append(one[0])
                except Exception:
                    continue
        for r in rows:
            cid = r.get("candidate_id")
            if cid:
                fetched[cid] = r

    for last_dt, header in ranked:
        candidate_id = header.get("candidate_id")
        if not candidate_id:
            continue
        c = fetched.get(candidate_id) or {}

        name = (c.get("name") or header.get("name") or "").strip() or "unknown"
        conversation_id = (c.get("conversation_id") or header.get("conversation_id") or "").strip()
        analysis = c.get("analysis") or {}
        metadata = c.get("metadata") or {}
        history = metadata.get("history") or []
        resume = (c.get("full_resume") or "").strip() or (c.get("resume_text") or "").strip()

        exclude, reasons = _should_exclude_candidate(resume=resume, analysis=analysis, history=history)
        if exclude:
            excluded.append(
                ExcludedCandidate(
                    name=name,
                    conversation_id=conversation_id,
                    candidate_id=candidate_id,
                    updated_at=c.get("updated_at") or header.get("updated_at"),
                    reasons=reasons,
                )
            )
            continue

        export = CandidateExport(
            name=name,
            conversation_id=conversation_id,
            resume=resume,
            analysis=analysis,
            history=history,
            candidate_id=candidate_id,
            updated_at=c.get("updated_at") or header.get("updated_at"),
            job_applied=c.get("job_applied") or header.get("job_applied"),
            last_history_at=last_dt.isoformat(sep=" ", timespec="seconds"),
        )
        exports.append(export)

    # Write outputs
    for i, e in enumerate(exports, start=1):
        conv_short = (e.conversation_id or "")[:12]
        filename = f"{i:03d}_{_safe_filename(e.name)}_{_safe_filename(conv_short)}.json"
        _write_json(candidates_dir / filename, e.to_dict())

    _write_json(run_dir / "excluded_candidates.json", [x.to_dict() for x in excluded])

    logger.info(
        "Saved %d candidates under %s (excluded=%d; fetched=%d)",
        len(exports),
        candidates_dir,
        len(excluded),
        len(raw_candidates),
    )
    return exports


# ---------------------------------------------------------------------------
# Step 3: distribution
# ---------------------------------------------------------------------------


def step3_compute_overall_distribution_and_save(
    candidates: list[CandidateExport],
    run_dir: Path,
) -> tuple[dict[str, Any], Path]:
    scores: list[int] = []
    missing = 0
    for c in candidates:
        overall = (c.analysis or {}).get("overall")
        if isinstance(overall, int):
            scores.append(overall)
        else:
            missing += 1

    hist = {str(i): 0 for i in range(1, 11)}
    for s in scores:
        if 1 <= s <= 10:
            hist[str(s)] += 1

    stats: dict[str, Any] = {
        "count_total": len(candidates),
        "count_with_overall": len(scores),
        "count_missing_overall": missing,
        "histogram_1_to_10": hist,
        "ratio_ge_7": (sum(1 for s in scores if s >= 7) / len(scores)) if scores else 0.0,
        "ratio_ge_8": (sum(1 for s in scores if s >= 8) / len(scores)) if scores else 0.0,
        "ratio_le_6": (sum(1 for s in scores if s <= 6) / len(scores)) if scores else 0.0,
    }
    if scores:
        stats.update(
            {
                "mean": round(mean(scores), 3),
                "median": median(scores),
                "min": min(scores),
                "max": max(scores),
            }
        )

    lines = [
        f"Total candidates: {stats['count_total']}",
        f"With overall: {stats['count_with_overall']}",
        f"Missing overall: {stats['count_missing_overall']}",
        "",
        "Histogram (overall 1-10):",
        *[f"  {k}: {v}" for k, v in hist.items()],
        "",
    ]
    if scores:
        lines += [
            f"Mean: {stats['mean']}",
            f"Median: {stats['median']}",
            f"Min: {stats['min']}",
            f"Max: {stats['max']}",
            "",
            f"Ratio >= 7: {stats['ratio_ge_7']:.3f}",
            f"Ratio >= 8: {stats['ratio_ge_8']:.3f}",
            f"Ratio <= 6: {stats['ratio_le_6']:.3f}",
        ]
    else:
        lines.append("No valid overall scores found.")

    out_path = run_dir / "overall_distribution.txt"
    _write_text(out_path, "\n".join(lines) + "\n")
    logger.info("Saved overall distribution: %s", out_path)
    return stats, out_path


# ---------------------------------------------------------------------------
# Step 4: export prompts/schema snapshot
# ---------------------------------------------------------------------------


def step4_export_prompt_files(prompt_opt_dir: Path) -> dict[str, Path]:
    prompt_opt_dir.mkdir(parents=True, exist_ok=True)

    prompt_json_path = prompt_opt_dir / "assistant_actions_prompts.json"
    _write_json(prompt_json_path, {"ACTION_PROMPTS": ACTION_PROMPTS})

    schema_json_path = prompt_opt_dir / "analysis_schema.json"
    _write_json(schema_json_path, AnalysisSchema.model_json_schema())

    prompt_md_path = prompt_opt_dir / "assistant_actions_prompts.md"
    md_lines = ["# Assistant Actions Prompts", ""]
    for k, v in ACTION_PROMPTS.items():
        md_lines += [f"## {k}", "", "```", (v or "").strip(), "```", ""]
    md_lines += [
        "## AnalysisSchema",
        "",
        "```json",
        json.dumps(AnalysisSchema.model_json_schema(), ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    _write_text(prompt_md_path, "\n".join(md_lines))

    logger.info("Exported prompt files to: %s", prompt_opt_dir)
    return {
        "assistant_actions_prompts.json": prompt_json_path,
        "analysis_schema.json": schema_json_path,
        "assistant_actions_prompts.md": prompt_md_path,
    }


# ---------------------------------------------------------------------------
# Step 5: write report + generate next prompt/portrait suggestion files
# ---------------------------------------------------------------------------


def _batch_optimization_suggestions(job: dict[str, Any], candidates: list[CandidateExport]) -> list[str]:
    # Keep it short; detailed guidance lives in the screening guide README/job portrait.
    aggregated = [
        "引入“Level2 真架构师”画像校准：强制区分 Senior IC vs Architect/Lead，增加反废话压测与红绿灯信号。",
        "年限不做一票否决：以主编码占比>=70%与关键场景能力为核心；偏管理/方案型候选人整体降档并提示HR重点核实。",
        "强制 100 分评分表（门槛/场景/基础/契合/潜力按50%/总分）并映射到 10 分制；summary 必须输出评分表+画像判断。",
        "把 HighLevel Design 的关键场景写成筛选主轴：state+command 持久化恢复、at-least-once 幂等键+DLQ+回放、IR/DSL、血缘版本化、安全授权。",
        "followup_tips 固定为 3 个反废话开放问题（推翻决策/10x爆点/一次事故复盘含量化与取舍），禁止索取任何工作隐私材料。",
    ]

    seen: set[str] = set()
    out: list[str] = []
    for s in aggregated:
        s = (s or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[:8]


def _build_prompt_variant_for_batch(suggestions: list[str]) -> str:
    base_analyze = (ACTION_PROMPTS.get("ANALYZE_ACTION") or "").strip()
    patch_lines = "\n".join([f"- {s}" for s in suggestions])
    patched_analyze = "\n\n".join([base_analyze, "【本批次优化补丁（建议）】", patch_lines]).strip()

    prompts = dict(ACTION_PROMPTS)
    prompts["ANALYZE_ACTION"] = patched_analyze

    return "\n".join(
        [
            "# Generated by scripts/prompt_optmization/download_data_for_prompt_optimization.py",
            "# batch: 1",
            "",
            "from __future__ import annotations",
            "",
            "ACTION_PROMPTS = " + json.dumps(prompts, ensure_ascii=False, indent=2),
            "",
        ]
    )


def _build_job_portrait_variant_for_batch(job: dict[str, Any], suggestions: list[str]) -> dict[str, Any]:
    variant = dict(job)
    patch_lines = "\n".join([f"- {s}" for s in suggestions])
    existing_requirements = (variant.get("requirements") or "").strip()
    variant["requirements"] = "\n\n".join(
        [
            "【本批次优化补丁（建议）】",
            patch_lines,
            "【原 requirements】",
            existing_requirements,
        ]
    ).strip()
    variant["prompt_optimization_notes"] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "batch_suggestions": suggestions,
        "single_batch_mode": True,
    }
    return variant


def step5_write_report_and_generate_variants(
    job: dict[str, Any],
    candidates: list[CandidateExport],
    distribution_stats: dict[str, Any],
    run_dir: Path,
    previous_run_dir: Optional[Path],
) -> Path:
    report_path = run_dir / "优化报告.md"

    excluded_count = 0
    excluded_path = run_dir / "excluded_candidates.json"
    if excluded_path.exists():
        try:
            excluded_count = len(json.loads(excluded_path.read_text(encoding="utf-8")))
        except Exception:
            excluded_count = 0

    prev_dist = _read_distribution_txt(previous_run_dir / "overall_distribution.txt") if previous_run_dir else {}
    prev_compliance = {}
    if previous_run_dir and (previous_run_dir / "candidates").exists():
        try:
            prev_candidates: list[CandidateExport] = []
            for p in sorted((previous_run_dir / "candidates").glob("*.json")):
                d = json.loads(p.read_text(encoding="utf-8"))
                prev_candidates.append(
                    CandidateExport(
                        name=d.get("name") or "unknown",
                        conversation_id=d.get("conversation_id") or "",
                        resume=d.get("resume") or "",
                        analysis=d.get("analysis") or {},
                        history=d.get("history") or [],
                        candidate_id=d.get("candidate_id"),
                        updated_at=d.get("updated_at"),
                        job_applied=d.get("job_applied"),
                    )
                )
            prev_compliance = _analysis_compliance_stats(prev_candidates)
        except Exception:
            prev_compliance = {}

    cur_compliance = _analysis_compliance_stats(candidates)
    cur_chat_risk = _chat_policy_risk_stats(candidates)

    # Rolling optimized artifacts: start from previous optimized baseline if available.
    baseline_prompts, baseline_job_portrait = _load_previous_optimized_baseline(previous_run_dir)
    prompt_optimized_path = run_dir / "prompt_optimized.py"
    _write_prompt_optimized_py(prompt_optimized_path, baseline_prompts)

    job_portrait_optimized_path = run_dir / "job_portrait_optimized.json"
    _write_job_portrait_optimized_json(job_portrait_optimized_path, baseline_job_portrait or dict(job))

    header = [
        "# 候选人筛选批次复盘（单批次）",
        "",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 岗位: {job.get('position')}",
        f"- job_id: {job.get('job_id')}",
        f"- base_job_id: {job.get('base_job_id')}",
        f"- 本批次候选人数量: {len(candidates)}（默认每批10个）",
        f"- 排除候选人数量: {excluded_count}（简历<100/无analysis/无assistant对话）",
        "",
        "## 上一批次对比（用于检查迭代是否有效）",
        "",
        f"- 上一批次目录: `{previous_run_dir}`" if previous_run_dir else "- 上一批次目录: （无）",
    ]

    if previous_run_dir and prev_dist:
        header += [
            f"- 上一批次 Mean/Median: {prev_dist.get('Mean')}/{prev_dist.get('Median')}",
            f"- 上一批次 Ratio>=7: {prev_dist.get('Ratio >= 7')}",
            f"- 上一批次 Ratio<=6: {prev_dist.get('Ratio <= 6')}",
        ]

    if prev_compliance:
        header += [
            f"- 上一批次 summary含评分表占比: {prev_compliance.get('scorecard_ratio'):.3f}",
            f"- 上一批次 summary含画像判断占比: {prev_compliance.get('persona_ratio'):.3f}",
        ]

    header += [
        f"- 本批次 Mean/Median: {distribution_stats.get('mean')}/{distribution_stats.get('median')}",
        f"- 本批次 Ratio>=7: {distribution_stats.get('ratio_ge_7')}",
        f"- 本批次 Ratio<=6: {distribution_stats.get('ratio_le_6')}",
        f"- 本批次 summary含评分表占比: {cur_compliance.get('scorecard_ratio'):.3f}",
        f"- 本批次 summary含画像判断占比: {cur_compliance.get('persona_ratio'):.3f}",
        "",
        "## 对话合规性快照（历史对话，非本次脚本生成）",
        "",
        f"- assistant消息涉及“薪资/预付/待遇”等: {cur_chat_risk.get('salary_messages')}",
        f"- assistant消息涉及“约时间/面试方式/地点”等: {cur_chat_risk.get('scheduling_messages')}",
        f"- assistant消息涉及“索取材料(代码/PR/仓库/文档等)”等: {cur_chat_risk.get('material_request_messages')}",
    ]

    if cur_chat_risk.get("salary_examples") or cur_chat_risk.get("scheduling_examples") or cur_chat_risk.get("material_examples"):
        header += [
            "",
            "示例（用于快速定位问题，不代表本批次 prompt 已生效）：",
        ]
        for title, key in [
            ("- 薪资相关:", "salary_examples"),
            ("- 约时间/面试相关:", "scheduling_examples"),
            ("- 索取材料相关:", "material_examples"),
        ]:
            examples = cur_chat_risk.get(key) or []
            if not examples:
                continue
            header.append(title)
            for who, preview in examples:
                header.append(f"  - {who}: {preview}")

    header += [
        "",
        "## 本批次滚动版本（要编辑的文件）",
        "",
        f"- prompt: `{prompt_optimized_path.name}`（完整版本，下一批次会以它为基线）",
        f"- job portrait: `{job_portrait_optimized_path.name}`（完整版本，下一批次会以它为基线）",
        "",
        "迭代检查建议：",
        "- 如果“评分表/画像判断”占比仍低，说明 prompt 未生效或旧 analysis 未更新；需要用最新 prompt 重新分析候选人再导出。",
        "- 如果 overall 仍大量集中在 7，优先排查：是否缺少反废话压测（推翻决策/10x爆点/故障复盘），以及是否把“关键词覆盖”当成“机制与取舍”。",
        "",
        "## 候选人逐个复盘（本批次）",
        "",
    ]

    body: list[str] = []
    for i, c in enumerate(candidates, start=1):
        analysis = c.analysis or {}
        score_line = (
            f"skill={analysis.get('skill')}, startup_fit={analysis.get('startup_fit')}, "
            f"background={analysis.get('background')}, overall={analysis.get('overall')}"
        )
        resume_preview = (c.resume or "").strip().replace("\n", " ")
        if len(resume_preview) > 300:
            resume_preview = resume_preview[:300] + "…"

        body += [
            f"### {i}. {c.name}",
            "",
            f"- conversation_id: `{c.conversation_id}`",
            f"- candidate_id: `{c.candidate_id}`",
            f"- updated_at: `{c.updated_at}`",
            f"- score: {score_line}",
            "",
            "**简历预览**",
            "",
            f"> {resume_preview or '[空]'}",
            "",
            "**当前 analysis（原样）**",
            "",
            "```json",
            json.dumps(analysis, ensure_ascii=False, indent=2),
            "```",
            "",
            "**人工补充（按筛选指南）**",
            "",
            "- 准确性评价（真架构师还是伪高P）:",
            "- 画像判断（技术深度/抽象能力/机制化/最终建议）:",
            "- 红灯/绿灯信号:",
            "- 反废话追问（写3个）:",
            "",
        ]

    suggestions = _batch_optimization_suggestions(job, candidates)

    footer = [
        "## 本批次自动总结（脚本生成）",
        "",
        f"- overall均值/中位数: {distribution_stats.get('mean')}/{distribution_stats.get('median')}",
        f"- overall>=7占比: {distribution_stats.get('ratio_ge_7'):.3f}；overall>=8占比: {distribution_stats.get('ratio_ge_8'):.3f}；overall<=6占比: {distribution_stats.get('ratio_le_6'):.3f}",
        f"- summary含评分表占比: {cur_compliance.get('scorecard_ratio'):.3f}",
        f"- summary含画像判断占比: {cur_compliance.get('persona_ratio'):.3f}",
        "",
        "本批次优化建议（自动汇总）：",
        *[f"- {s}" for s in suggestions],
        "",
        f"- 已生成滚动版本文件: `{prompt_optimized_path.name}`、`{job_portrait_optimized_path.name}`",
        "",
        "## 本批次小结（人工补充）",
        "",
        "- 共同误判点:",
        "- 岗位肖像需要补充/澄清的点:",
        "- prompt需要补充/约束的点:",
        "",
    ]

    _write_text(report_path, "\n".join(header + body + footer))
    logger.info("Wrote report scaffold: %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=None, help="Select job by job_id/base_job_id")
    parser.add_argument("--job-position", default=None, help="Select job by position keyword (e.g., 架构师)")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of newest candidates per run (default: 10)")
    parser.add_argument(
        "--prompt-opt-dir",
        default=str(Path("scripts") / "prompt_optmization"),
        help="Output root directory",
    )
    args = parser.parse_args()

    prompt_opt_dir = Path(args.prompt_opt_dir)

    # Step 4 first: always export the current prompts/schema for editing.
    step4_export_prompt_files(prompt_opt_dir)

    job, run_dir, _job_profile_path, previous_run_dir = step1_select_job_and_create_run_dir(
        prompt_opt_dir=prompt_opt_dir,
        job_id=args.job_id,
        job_position=args.job_position,
    )
    candidates = step2_fetch_recent_candidates_and_save(job=job, run_dir=run_dir, batch_size=args.batch_size)
    dist_stats, _dist_path = step3_compute_overall_distribution_and_save(candidates=candidates, run_dir=run_dir)
    step5_write_report_and_generate_variants(
        job=job,
        candidates=candidates,
        distribution_stats=dist_stats,
        run_dir=run_dir,
        previous_run_dir=previous_run_dir,
    )

    logger.info("Done. Run directory: %s", run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
