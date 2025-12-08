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
# Import from unified stage definition
from .candidate_stages import STAGE_FLOW, STAGE_SEEK, STAGE_PASS, normalize_stage
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
    """计算肖像得分，用于评估岗位画像质量。
    
    肖像得分由三个维度组成：
    1. 分布均匀度（40%）：评估3-8分段的分布是否均匀
    2. 高分占比（30%）：评估高分（≥7分）占比是否合理（不超过25%）
    3. 中心分数（30%）：评估平均分是否接近理想值6分
    
    Args:
        scores: 候选人评分列表（1-10分）
        
    Returns:
        ScoreAnalysis: 包含各项统计指标和肖像得分的分析结果
    """
    if not scores:
        return ScoreAnalysis(0, 0.0, 0.0, {}, 0.0, "暂无评分数据")
    # 优先使用 numpy 向量化以加速大样本，若不可用则回退到纯 Python
    try:
        import numpy as np  # type: ignore

        arr = np.clip(np.array(scores, dtype=int), 1, 10)
        avg = float(arr.mean())
        dist_dict = {int(k): int(v) for k, v in zip(*np.unique(arr, return_counts=True))}

        focus = arr[(arr >= 3) & (arr <= 8)]
        if focus.size:
            counts = np.bincount(focus, minlength=11)[3:9]
            max_dev = (counts.max() - counts.min()) / max(1, counts.sum())
            uniform_score = max(0.0, 1 - max_dev * 1.5)
        else:
            uniform_score = 0.4

        high_share = float((arr >= HIGH_SCORE_THRESHOLD).mean())
    except Exception:  # pragma: no cover - fallback path
        clipped = [min(10, max(1, int(s))) for s in scores]
        dist = Counter(clipped)
        dist_dict = dict(dist)
        avg = sum(clipped) / len(clipped)
        focus_scores = [dist.get(i, 0) for i in range(3, 9)]
        focus_total = sum(focus_scores)
        if focus_total:
            max_dev = (max(focus_scores) - min(focus_scores)) / max(1, focus_total)
            uniform_score = max(0.0, 1 - max_dev * 1.5)
        else:
            uniform_score = 0.4
        high_share = dist_count(clipped, lambda s: s >= HIGH_SCORE_THRESHOLD) / len(clipped)

    # 高分占比超过25%开始惩罚
    high_penalty = max(0.0, (high_share - 0.25) / 0.75)
    center_score = max(0.0, 1 - abs(avg - 6) / 6)

    # 综合计算肖像得分：三个维度的加权平均
    # 分布均匀度40% + (1-高分惩罚)30% + 中心分数30%
    quality = (uniform_score * 0.4) + ((1 - high_penalty) * 0.3) + (center_score * 0.3)
    # 将得分映射到1-10分范围，保留1位小数
    quality_score = round(max(1.0, min(10.0, quality * 10)), 1)

    # 根据计算结果生成评语
    comment = (
        "分布集中在高分段，需优化画像" if high_penalty > 0.05  # 高分占比过高
        else "分布均衡，画像质量良好" if uniform_score > 0.6  # 分布均匀
        else "分布略偏，可再细化画像"  # 其他情况
    )

    return ScoreAnalysis(
        count=sum(dist_dict.values()),
        average=round(avg, 2),
        high_share=round(high_share, 3),
        distribution=dist_dict,
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
        if normalize_stage(cand.get("stage")) == STAGE_SEEK:
            bucket[day]["seek"] += 1

    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        data = bucket.get(d, {"new": 0, "seek": 0})
        series.append({"date": d.isoformat(), **data})
    return series


def conversion_table(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Normalize stage names using unified stage utilities
    stage_counts = Counter(normalize_stage(cand.get("stage")) or "" for cand in candidates)
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
    pass_count = stage_counts.get(STAGE_PASS, 0)
    if pass_count:
        total_screened = pass_count + sum(stage_counts[s] for s in STAGE_FLOW)
        rows.append({
            "stage": STAGE_PASS,
            "count": pass_count,
            "previous": total_screened - pass_count,
            "rate": round(pass_count / max(total_screened, 1), 3),
        })
    return rows


def fetch_job_candidates(job_name: str, days: int | None = None) -> List[Dict[str, Any]]:
    """Fetch candidates for a job with optional time range and limit.
    
    Args:
        job_name: Job position name
        limit: Maximum number of candidates to return. If None, uses a large default (10000)
        days: Number of days to look back. If None, fetches all candidates
    
    Returns:
        List of candidate dictionaries
    """
    updated_from = None
    if days:
        start_dt = datetime.now() - timedelta(days=days)
        updated_from = start_dt.isoformat()
    return search_candidates_advanced(
        job_applied=job_name,
        fields=["candidate_id", "job_applied", "stage", "analysis", "updated_at"],
        updated_from=updated_from,
        sort_by="updated_at",
        sort_direction="desc",
    )


def compile_job_stats(job_name: str) -> Dict[str, Any]:
    # 获取最近一周的候选人数据用于统计
    # 不设置 limit，使用默认的 10000 以获取所有符合条件的候选人
    candidates = fetch_job_candidates(job_name, days=7)
    # Score analysis uses latest 100
    recent_scores = [
        (cand.get("analysis") or {}).get("overall")
        for cand in candidates
        if (cand.get("analysis") or {}).get("overall") is not None
    ][:100]
    score_summary = _score_quality(recent_scores)

    daily = build_daily_series(candidates, days=7)
    conversions = conversion_table(candidates)

    # 近7天统计数据（用于进展分计算和"best record"评选）
    # candidates 已经是最近7天的数据（通过 days=7 获取）
    recent_7days_candidates = candidates  # 最近7天的所有候选人
    recent_7days_high = dist_count(
        [
            (c.get("analysis") or {}).get("overall")
            for c in recent_7days_candidates
            if (c.get("analysis") or {}).get("overall") is not None
        ],
        lambda s: s >= HIGH_SCORE_THRESHOLD,
    )
    # 进展分：近7天进展到SEEK阶段的候选人数
    recent_7days_seek = sum(1 for c in recent_7days_candidates if normalize_stage(c.get("stage")) == STAGE_SEEK)
    # 进展分 = (近7天候选人数量 + SEEK阶段人数) × 肖像质量分 / 10 (归一化)
    # 肖像质量分范围是1-10，除以10归一化到0-1范围
    recent_7days_metric = (len(recent_7days_candidates) + recent_7days_seek) * score_summary.quality_score / 10
    
    # 今日数据（用于显示今日新增）
    today = datetime.now().date()
    today_candidates = [c for c in candidates if _parse_dt(c.get("updated_at")) and _parse_dt(c.get("updated_at")).date() == today]

    return {
        "job": job_name,
        "daily": daily,
        "conversions": conversions,
        "score_summary": score_summary,
        "today": {
            "count": len(recent_7days_candidates),  # 近7天候选人数量（用于进展分计算）
            "high": recent_7days_high,  # 近7天高分人数
            "seek": recent_7days_seek,  # 近7天SEEK人数
            "metric": round(recent_7days_metric, 2),  # 进展分（基于近7天）
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
