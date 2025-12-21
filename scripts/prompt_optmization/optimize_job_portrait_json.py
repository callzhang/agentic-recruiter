#!/usr/bin/env python3
"""Optimize a job portrait JSON without changing the jobs-store schema.

Key idea:
- Do NOT add new top-level fields (schema is defined in `src/jobs_store.py`)
- Keep all content inside existing fields:
  - `requirements` as a plain-text scorecard (one line per item)
  - `drill_down_questions` as a plain-text online screening question list

Typical use:
1) Download current portrait via Vercel:
   python scripts/prompt_optmization/publish_job_portrait.py --api-type vercel --api-base https://<domain> \\
     --download-job-id architecture --download-out job_portrait.json
2) Optimize JSON (rewrite requirements/drill_down_questions as plain text):
   python scripts/prompt_optmization/optimize_job_portrait_json.py --input job_portrait.json --output job_portrait_optimized.json
3) Publish optimized portrait (creates new version):
   python scripts/prompt_optmization/publish_job_portrait.py --api-type vercel --api-base https://<domain> \\
     --job-portrait job_portrait_optimized.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_question_bank_architect() -> dict[str, Any]:
    # Keep this script simple: only produce an online-screening question list.
    # Job-specific content should live in the job portrait JSON and be published via API.
    return {
        "online_questions": [
            "讲一次你最想推翻重写的架构决策：当时为什么选它，现在为什么觉得它错了？",
            "如果你负责的系统流量/数据量暴涨10倍，最先崩的会是哪一块？你会按什么顺序止血与改造？",
            "讲一次你亲历并主导处理的线上事故：怎么发现→怎么止血→怎么长期治理？关键指标前后变化如何？",
            "讲一次你处理过的异步/MQ事故（毒丸/重试风暴/重复消费/顺序错乱任选）：你如何隔离、止血、建立长期闭环？",
            "讲一次你做过的长任务断点续传/恢复设计：恢复点存哪里、如何幂等、恢复流程怎么走？",
            "讲一次你做过的一致性+补偿/回放/对账：哪些必须强一致？哪些可最终一致？补偿失败怎么办？",
            "别讲技术名词，口头描述你的领域模型：核心实体有哪些？边界/聚合怎么划？为什么这样划？",
            "讲一次你做过的私有化/混合云交付：在网络/权限/资源受限下如何适配并保证可重复交付？",
        ]
    }

def _build_requirements_text_architect() -> str:
    return "\n".join(
        [
            "30 门槛：硬性条件1；硬性条件2；硬性条件3（能从简历判断满足/不满足/未体现）",
            "45 场景：关键场景1（亲历/取舍/量化指标/你负责的部分）；关键场景2；关键场景3",
            "15 基础：表达结构化；能量化结果；学习迁移能力",
            "10 契合：Owner意识；协作推进（不聊绩效管理）",
            "备注：缺失信息可记为潜力（最多按50%计入），并提示HR后续重点验证。",
        ]
    )


def _is_scorecard_v1_json(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    try:
        obj = json.loads(raw)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    return obj.get("schema") == "scorecard_v1" and obj.get("total") == 100 and isinstance(obj.get("items"), list)


def _optimize_job_portrait(job: dict[str, Any]) -> dict[str, Any]:
    out = dict(job)
    # Ensure no non-schema top-level fields (we only touch known keys).
    out.pop("followup_questions", None)

    # requirements: prefer plain-text scorecard (one line per item).
    existing_requirements = str(out.get("requirements", "") or "").strip()
    if not existing_requirements or _is_scorecard_v1_json(existing_requirements):
        out["requirements"] = _build_requirements_text_architect()

    bank = _build_question_bank_architect()
    # Keep it as plain text for human readability; prompt should treat it as online-screening only.
    questions = bank.get("online_questions") or []
    lines: list[str] = [
        "【线上甄别追问（只用于线上沟通）】",
        "- 每次只选 1 个问题；不要合并多问；不要问管理/绩效/制度推进类问题。",
        "- 优先问候选人亲历：过程、关键取舍、量化指标变化、你负责的部分。",
        "",
    ]
    for i, q in enumerate(questions, start=1):
        lines.append(f"{i}. {q}")
    out["drill_down_questions"] = "\n".join(lines).strip()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to job_portrait.json (downloaded/current)")
    parser.add_argument("--output", required=True, help="Path to write optimized job portrait JSON")
    args = parser.parse_args()

    inp = Path(args.input)
    outp = Path(args.output)
    job = _read_json(inp)
    optimized = _optimize_job_portrait(job)
    _write_json(outp, optimized)
    print("Wrote optimized job portrait to:", str(outp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
