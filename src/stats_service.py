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
from .candidate_stages import STAGE_FLOW, STAGE_SEEK, STAGE_PASS, STAGE_CHAT, STAGE_CONTACT, normalize_stage
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
    
    # 使用 numpy 向量化以加速大样本计算
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
        uniform_score = 0.1

    high_share = float((arr >= HIGH_SCORE_THRESHOLD).mean())

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
        "分布集中在高分段，需优化画像" if high_penalty > 0.1  # 高分占比过高
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

    bucket = defaultdict(lambda: {"new": 0, "seek": 0, "processed": 0})
    for cand in candidates:
        dt = _parse_dt(cand.get("updated_at"))
        if not dt:
            continue
        day = dt.date()
        if day < start:
            continue
        bucket[day]["new"] += 1

        stage_norm = normalize_stage(cand.get("stage"))
        if stage_norm == STAGE_SEEK:
            bucket[day]["seek"] += 1
        # Check if processed: strictly contacted metadata
        contacted = cand.get("metadata", {}).get("contacted")
        if contacted:
            bucket[day]["processed"] += 1

    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        data = bucket.get(d, {"new": 0, "seek": 0, "processed": 0})
        series.append({"date": d.isoformat(), **data})
    return series


def conversion_table(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Calculate stage conversion rates.
    
    Stage flow: PASS → CHAT → SEEK → CONTACT
    Conversion rate formula: (current_stage + all_following_stages) / previous_stage_count
    
    - PASS: First stage, rejected candidates (score < chat_threshold)
    - CHAT: From total screened (score >= chat_threshold)
    - SEEK: From CHAT (score >= borderline_threshold)
    - CONTACT: From SEEK (score >= seek_threshold)
    """
    # Normalize stage names using unified stage utilities
    stage_counts = Counter(normalize_stage(cand.get("stage")) or "" for cand in candidates)
    rows: List[Dict[str, Any]] = []
    
    # Calculate stage counts
    pass_count = stage_counts.get(STAGE_PASS, 0)
    chat_count = stage_counts.get(STAGE_CHAT, 0)
    seek_count = stage_counts.get(STAGE_SEEK, 0)
    contact_count = stage_counts.get(STAGE_CONTACT, 0)
    
    # Calculate total screened (all candidates except those without stage)
    total_screened = (pass_count + chat_count + seek_count + contact_count) or 1
    
    # PASS: First stage
    # 转化率 = (PASS + CHAT + SEEK + CONTACT) / 总筛选人数 = 100%
    rows.append({
        "stage": STAGE_PASS,
        "count": pass_count,
        "previous": total_screened,  # Total screened is the "previous" for PASS
        "rate": round(pass_count / total_screened, 3),
    })
    
    # CHAT: Second stage
    # 转化率 = CHAT / PASS人数 (从PASS阶段转化到CHAT阶段的比例)
    rows.append({
        "stage": STAGE_CHAT,
        "count": chat_count,
        "previous": pass_count,  # From PASS
        "rate": round(chat_count / (pass_count or 1), 3),
    })
    
    # SEEK: Third stage
    # 转化率 = SEEK / CHAT人数 (从CHAT阶段转化到SEEK阶段的比例)
    rows.append({
        "stage": STAGE_SEEK,
        "count": seek_count,
        "previous": chat_count,  # From CHAT
        "rate": round(seek_count / (chat_count or 1), 3),
    })
    
    # CONTACT: Fourth stage
    # 转化率 = CONTACT / SEEK人数 (从SEEK阶段转化到CONTACT阶段的比例)
    rows.append({
        "stage": STAGE_CONTACT,
        "count": contact_count,
        "previous": seek_count,  # From SEEK
        "rate": round(contact_count / (seek_count or 1), 3),
    })
    
    return rows


def build_daily_candidate_counts(candidates: List[Dict[str, Any]], total_count: int, days: int = 30) -> List[Dict[str, Any]]:
    """Build daily cumulative candidate counts for historical chart.
    
    Note: Candidate collection only has updated_at field, not created_at.
    We use updated_at as the date for counting.
    
    Args:
        candidates: List of candidate records (limited by Milvus query limit)
        total_count: Total number of candidates in the collection
        days: Number of days to show in the chart
    """
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    
    # Count candidates by updated_at date (candidate collection doesn't have created_at)
    daily_counts = defaultdict(int)
    candidates_without_date = 0
    candidates_in_period = 0
    
    for cand in candidates:
        # Candidate collection only has updated_at, not created_at
        dt = _parse_dt(cand.get("updated_at"))
        if not dt:
            candidates_without_date += 1
            continue
        day = dt.date()
        if day >= start:
            daily_counts[day] += 1
            candidates_in_period += 1
    
    # Calculate candidates before the period
    # Since we can only fetch 16384 candidates, we estimate:
    # total_count - candidates_in_period - candidates_without_date = candidates_before_start
    candidates_before_start = max(0, total_count - candidates_in_period - candidates_without_date)
    
    logger.debug(f"build_daily_candidate_counts: total_fetched={len(candidates)}, total_in_db={total_count}, in_period={candidates_in_period}, without_date={candidates_without_date}, before_start={candidates_before_start}")
    
    # Build cumulative series starting from candidates before the period
    series = []
    cumulative = candidates_before_start
    for i in range(days):
        d = start + timedelta(days=i)
        count = daily_counts.get(d, 0)
        cumulative += count
        series.append({
            "date": d.isoformat(),
            "count": cumulative,
            "new": count
        })
    return series


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
        limit=None,
        fields=["candidate_id", "job_applied", "stage", "analysis", "updated_at", "metadata"],
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
    # 进展分：近7天进展到SEEK和CONTACT阶段的候选人数
    recent_7days_seek = sum(1 for c in recent_7days_candidates if normalize_stage(c.get("stage")) == STAGE_SEEK)
    recent_7days_contacted = sum(1 for c in recent_7days_candidates if normalize_stage(c.get("stage")) == STAGE_CONTACT)
    
    # 进展分 = (近7日候选人数量 + SEEK人数 + CONTACT人数 x 10) × 肖像得分 / 10
    recent_7days_metric = (len(recent_7days_candidates) + recent_7days_seek + recent_7days_contacted * 10) * score_summary.quality_score / 10
    
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
            "contacted": recent_7days_contacted,  # 近7天已联系人数
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
            f"  今日新增 {best['today']['count']} 人，其中高分(≥{HIGH_SCORE_THRESHOLD}) {best['today']['high']} 人，SEEK {best['today']['seek']}，已联系 {best['today']['contacted']}，进展分 {best['today']['metric']:.1f}"
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
