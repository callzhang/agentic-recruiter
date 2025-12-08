"""Data aggregation and daily reporting for hiring metrics.

This module keeps all statistics logic in one place so both the web UI and
scheduled DingTalk reports can share the same calculations.

All functions are written to be side‑effect free except for
``send_daily_dingtalk_report`` which formats and dispatches the message.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Any, Dict, Iterable, List, Optional

from .candidate_store import search_candidates_advanced
from .jobs_store import get_all_jobs
from .assistant_actions import send_dingtalk_notification
from .global_logger import logger


# Stage order used for conversion calculations
STAGE_FLOW = ["GREET", "CHAT", "SEEK", "CONTACT"]
HIGH_SCORE_THRESHOLD = 7


def _parse_dt(value: str) -> Optional[datetime]:
    """Parse ISO timestamp stored in Milvus records.

    Milvus stores timestamps as ISO strings without timezone; we treat them as
    local time to keep day-grouping intuitive for operators.
    """

    if not value:
        return None
    try:
        # Handle both "2024-01-01T12:00:00" and with offset
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001 - defensive
        logger.debug("Failed to parse datetime: %s", value)
        return None


@dataclass
class ScoreAnalysis:
    count: int
    average: float
    high_share: float
    distribution: Dict[int, int]
    quality_score: float
    comment: str


def _score_quality(scores: List[int]) -> ScoreAnalysis:
    if not scores:
        return ScoreAnalysis(0, 0.0, 0.0, {}, 0.0, "暂无评分数据")

    clipped = [min(10, max(1, int(s))) for s in scores]
    dist = Counter(clipped)
    avg = sum(clipped) / len(clipped)

    # Uniformity across 3–8
    focus_scores = [dist.get(i, 0) for i in range(3, 9)]
    focus_total = sum(focus_scores)
    if focus_total:
        max_dev = (max(focus_scores) - min(focus_scores)) / max(1, focus_total)
        uniform_score = max(0.0, 1 - max_dev * 1.5)
    else:
        uniform_score = 0.4  # slight penalty if no data in 3–8 range

    high_share = dist_count(clipped, lambda s: s >= HIGH_SCORE_THRESHOLD) / len(clipped)
    high_penalty = max(0.0, (high_share - 0.25) / 0.75)  # penalty only above 25%
    center_score = max(0.0, 1 - abs(avg - 6) / 6)

    quality = (uniform_score * 0.4) + ((1 - high_penalty) * 0.3) + (center_score * 0.3)
    quality_score = round(max(1.0, min(10.0, quality * 10)), 1)

    comment = (
        "分布集中在高分段，需优化画像" if high_penalty > 0.05
        else "分布均衡，画像质量良好" if uniform_score > 0.6
        else "分布略偏，可再细化画像"
    )

    return ScoreAnalysis(
        count=len(clipped),
        average=round(avg, 2),
        high_share=round(high_share, 3),
        distribution=dict(dist),
        quality_score=quality_score,
        comment=comment,
    )


def dist_count(items: Iterable[int], predicate) -> int:
    return sum(1 for i in items if predicate(i))


def build_daily_series(candidates: List[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)

    bucket = defaultdict(lambda: {"new": 0, "seek": 0})
    for cand in candidates:
        dt = _parse_dt(cand.get("updated_at"))
        if not dt:
            continue
        day = dt.date()
        if day < start:
            continue
        bucket[day]["new"] += 1
        if (cand.get("stage") or "").upper() == "SEEK":
            bucket[day]["seek"] += 1

    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        data = bucket.get(d, {"new": 0, "seek": 0})
        series.append({"date": d.isoformat(), **data})
    return series


def conversion_table(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stage_counts = Counter((cand.get("stage") or "").upper() for cand in candidates)
    rows: List[Dict[str, Any]] = []
    for idx, stage in enumerate(STAGE_FLOW):
        count = stage_counts.get(stage, 0)
        prev = stage_counts.get(STAGE_FLOW[idx - 1], 0) if idx > 0 else 0
        denominator = count + prev if idx > 0 else max(count, 1)
        rate = count / denominator if denominator else 0.0
        rows.append({
            "stage": stage,
            "count": count,
            "previous": prev,
            "rate": round(rate, 3),
        })
    # Track PASS separately to show rejection ratio
    pass_count = stage_counts.get("PASS", 0)
    if pass_count:
        total_screened = pass_count + sum(stage_counts[s] for s in ("GREET", "CHAT", "SEEK", "CONTACT"))
        rows.append({
            "stage": "PASS",
            "count": pass_count,
            "previous": total_screened - pass_count,
            "rate": round(pass_count / max(total_screened, 1), 3),
        })
    return rows


def fetch_job_candidates(job_name: str, limit: int = 2000, days: int | None = None) -> List[Dict[str, Any]]:
    updated_from = None
    if days:
        start_dt = datetime.now() - timedelta(days=days)
        updated_from = start_dt.isoformat()
    return search_candidates_advanced(
        job_applied=job_name,
        limit=limit,
        fields=["candidate_id", "job_applied", "stage", "analysis", "updated_at"],
        updated_from=updated_from,
        sort_by="updated_at",
        sort_direction="desc",
    )


def compile_job_stats(job_name: str) -> Dict[str, Any]:
    candidates = fetch_job_candidates(job_name, limit=2000)
    # Score analysis uses latest 100
    recent_scores = [
        (cand.get("analysis") or {}).get("overall")
        for cand in candidates
        if (cand.get("analysis") or {}).get("overall") is not None
    ][:100]
    score_summary = _score_quality(recent_scores)

    daily = build_daily_series(candidates, days=7)
    conversions = conversion_table(candidates)

    # Today stats for "best record"
    today = datetime.now().date()
    today_candidates = [c for c in candidates if _parse_dt(c.get("updated_at")) and _parse_dt(c.get("updated_at")).date() == today]
    today_high = dist_count(
        [
            (c.get("analysis") or {}).get("overall")
            for c in today_candidates
            if (c.get("analysis") or {}).get("overall") is not None
        ],
        lambda s: s >= HIGH_SCORE_THRESHOLD,
    )
    # 进展分：今日进展到SEEK阶段的候选人数
    today_seek = sum(1 for c in today_candidates if (c.get("stage") or "").upper() == "SEEK")
    # 使用进展分而不是画像质评分
    today_metric = (len(today_candidates) + today_high) * max(today_seek, 1)

    return {
        "job": job_name,
        "daily": daily,
        "conversions": conversions,
        "score_summary": score_summary,
        "today": {
            "count": len(today_candidates),
            "high": today_high,
            "seek": today_seek,
            "metric": round(today_metric, 2),
        },
        "total": len(candidates),
    }


def compile_all_jobs() -> Dict[str, Any]:
    jobs = get_all_jobs() or []
    stats: List[Dict[str, Any]] = []
    for job in jobs:
        position = job.get("position") or job.get("job_id")
        if not position:
            continue
        try:
            stats.append(compile_job_stats(position))
        except Exception as exc:  # noqa: BLE001
            logger.warning("统计岗位 %s 失败: %s", position, exc)
    best = max(stats, key=lambda s: s["today"]["metric"], default=None)
    return {"jobs": stats, "best": best}


def send_daily_dingtalk_report() -> bool:
    summary = compile_all_jobs()
    jobs = summary.get("jobs", [])
    if not jobs:
        logger.info("No jobs found for daily report, skipping DingTalk push")
        return False

    best = summary.get("best")
    title = f"每日招聘战报 - {datetime.now().date().isoformat()}"

    lines = []
    if best:
        ss = best["score_summary"]
        lines.append(
            f"🏆 今日最优岗位：{best['job']} | 成绩 {best['today']['metric']:.1f}"
        )
        lines.append(
            f"  今日新增 {best['today']['count']} 人，其中高分(≥{HIGH_SCORE_THRESHOLD}) {best['today']['high']} 人，进展分 {best['today']['seek']} 人"
        )
    lines.append("")
    lines.append("各岗位摘要：")
    for job in jobs:
        ss = job["score_summary"]
        lines.append(
            f"- {job['job']}: 总数 {job['total']} | 7日新增 {sum(d['new'] for d in job['daily'])} | 画像质 {ss.quality_score}/10 | 高分占比 {ss.high_share*100:.1f}%"
        )

    message = "\n".join(lines)
    return send_dingtalk_notification(title=title, message=message, job_id=None)


__all__ = [
    "compile_all_jobs",
    "compile_job_stats",
    "build_daily_series",
    "conversion_table",
    "send_daily_dingtalk_report",
]
