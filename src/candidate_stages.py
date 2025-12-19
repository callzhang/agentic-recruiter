"""Candidate stage definitions and utilities.

This module provides a unified definition of candidate stages used throughout
the recruitment system. All stage-related logic should reference this module.

Stage Definitions:
    PASS: 分数低于 chat_threshold，不匹配，已拒绝
    CHAT: 分数高于 chat_threshold，沟通中
    SEEK: 分数高于 borderline_threshold，弱匹配，主动沟通
    CONTACT: 分数高于 seek_threshold，已获得联系方式

Stage Flow:
    PASS → CHAT → SEEK → CONTACT
    (Note: PASS is a terminal stage, not part of the forward flow)
"""

from enum import Enum
from typing import Literal, Optional


# 统一的阶段定义：包含所有阶段信息
STAGES = {
    "PASS": {
        "name": "PASS",
        "description": "分数低于 chat_threshold，不匹配，已拒绝",
        "in_flow": False,  # PASS 是终止阶段，不参与正向流程
    },
    "CHAT": {
        "name": "CHAT",
        "description": "分数高于 chat_threshold，需要进一步通过沟通挖掘匹配情况",
        "in_flow": True,
    },
    "SEEK": {
        "name": "SEEK",
        "description": "分数高于 borderline_threshold，弱匹配，主动沟通",
        "in_flow": True,
    },
    "CONTACT": {
        "name": "CONTACT",
        "description": "分数高于 seek_threshold，强匹配，已获得联系方式",
        "in_flow": True,
    },
}

# 从统一定义导出所有需要的常量和列表
STAGE_PASS = STAGES["PASS"]["name"]
STAGE_CHAT = STAGES["CHAT"]["name"]
STAGE_SEEK = STAGES["SEEK"]["name"]
STAGE_CONTACT = STAGES["CONTACT"]["name"]

ALL_STAGES = [stage["name"] for stage in STAGES.values()]
STAGE_FLOW = [stage["name"] for stage in STAGES.values() if stage["in_flow"]]
STAGE_DESCRIPTIONS = {stage["name"]: stage["description"] for stage in STAGES.values()}

# 枚举类（用于类型检查）
class CandidateStage(str, Enum):
    """Candidate recruitment stage enumeration."""
    PASS = STAGE_PASS
    CHAT = STAGE_CHAT
    SEEK = STAGE_SEEK
    CONTACT = STAGE_CONTACT

# Type alias for stage values
StageType = Literal["PASS", "CHAT", "SEEK", "CONTACT"]


def determine_stage(
    score: float,
    chat_threshold: float = 6.0,
    borderline_threshold: float = 7.0,
    seek_threshold: float = 8.0,
) -> str:
    """Determine candidate stage based on score and thresholds.
    
    Args:
        score: Overall candidate score (typically 1-10)
        chat_threshold: Minimum score to enter CHAT stage (default: 6.0)
        borderline_threshold: Minimum score to enter SEEK stage (default: 7.0)
        seek_threshold: Minimum score to enter CONTACT stage (default: 8.0)
    
    Returns:
        Stage name: "PASS", "CHAT", "SEEK", or "CONTACT"
    
    Examples:
        >>> determine_stage(5.0)  # score < chat_threshold (6.0)
        'PASS'
        >>> determine_stage(6.5)  # chat_threshold (6.0) <= score < borderline_threshold (7.0)
        'CHAT'
        >>> determine_stage(7.5)  # borderline_threshold (7.0) <= score < seek_threshold (8.0)
        'SEEK'
        >>> determine_stage(8.5)  # score >= seek_threshold (8.0)
        'CONTACT'
    """
    if score < chat_threshold:
        return STAGE_PASS
    elif score < borderline_threshold:
        return STAGE_CHAT
    elif score < seek_threshold:
        return STAGE_SEEK
    else:
        return STAGE_CONTACT


def is_valid_stage(stage: Optional[str]) -> bool:
    """Check if a stage name is valid.
    
    Args:
        stage: Stage name to validate
    
    Returns:
        True if stage is valid, False otherwise
    """
    if stage is None:
        return False
    return stage.upper() in ALL_STAGES


def normalize_stage(stage: Optional[str]) -> Optional[str]:
    """Normalize stage name to uppercase.
    
    Args:
        stage: Stage name (case-insensitive)
    
    Returns:
        Uppercase stage name, or None if invalid
    """
    if stage is None:
        return None
    stage_upper = stage.upper()
    return stage_upper if stage_upper in ALL_STAGES else None


def get_stage_description(stage: Optional[str]) -> str:
    """Get description for a stage.
    
    Args:
        stage: Stage name
    
    Returns:
        Stage description, or empty string if invalid
    """
    if stage is None:
        return ""
    stage_upper = normalize_stage(stage)
    return STAGE_DESCRIPTIONS.get(stage_upper or "", "")


# Export all public symbols
__all__ = [
    "CandidateStage",
    "STAGE_PASS",
    "STAGE_CHAT",
    "STAGE_SEEK",
    "STAGE_CONTACT",
    "STAGE_FLOW",
    "ALL_STAGES",
    "STAGE_DESCRIPTIONS",
    "StageType",
    "determine_stage",
    "is_valid_stage",
    "normalize_stage",
    "get_stage_description",
]

