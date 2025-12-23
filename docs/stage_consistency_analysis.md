# 阶段定义一致性说明（以运行时为准）

本项目历史上出现过 `GREET`（推荐页“已打招呼”语义），但目前“候选人筛选阶段”的统一口径以 `src/candidate_stages.py` 为准：`PASS/CHAT/SEEK/CONTACT`。

## ✅ 统一阶段定义（src/candidate_stages.py）

- `PASS`：不匹配，终止
- `CHAT`：需要线上继续甄别（可问 1 个关键问题）
- `SEEK`：接近强匹配，强推进（但不约面试；由 HR 决定时间/方式/地点）
- `CONTACT`：联系阶段（待拿联系方式或已拿联系方式）

默认阈值（仅默认，可在 UI 中配置）：

```python
overall < 6  -> PASS
overall < 7  -> CHAT
overall < 8  -> SEEK
overall >= 8 -> CONTACT
```

## 🟡 GREET 的处理（历史兼容）

- `GREET` 可能出现在推荐流程的历史数据中（例如“已打招呼/等待回复”）。
- 对于统计/阶段流转/岗位日报：
  - 建议将 `GREET` 视为 `CHAT` 的同义/子状态（“已发起沟通但未获得有效回复”）
  - 新代码中避免继续扩散 `GREET` 作为核心阶段

## ✅ 合规与边界

- `CONTACT/SEEK` 均不代表“已约面试”：AI 不应安排/确认面试时间、方式、地点；统一引导 HR。
- `PASS` 时不发送消息（message 必须为空），避免无意义打扰。
