# 阶段定义一致性分析报告

## 📋 参考定义（agent/prompts.py）

```python
STAGES = {
    "PASS": "< 7, 不匹配，已拒绝",
    "CHAT": ">= 7, 沟通中",
    "SEEK": ">= 9, 强匹配，主动寻求联系方式",
    "CONTACT": "已获得联系方式",
}
```

## 🔍 各文件中的阶段定义

### 1. agent/prompts.py

**STAGES 字典定义：**
- ✅ PASS: < 7, 不匹配，已拒绝
- ✅ CHAT: >= 7, 沟通中
- ✅ SEEK: >= 9, 强匹配，主动寻求联系方式
- ✅ CONTACT: 已获得联系方式
- ❌ **缺少 GREET**

**RECRUITER_PROMPT 中的逻辑：**
```python
- overall_score<7 → PASS
- overall_score>=7 → GREET  # ⚠️ 这里用的是 GREET，不是 CHAT
- overall_score>=9 → SEEK
```

**不一致问题：**
- STAGES 定义中没有 GREET，但 RECRUITER_PROMPT 中使用了 GREET
- STAGES 中有 CHAT，但逻辑中 overall_score>=7 时用的是 GREET

---

### 2. src/assistant_actions.py

```python
STAGES = [
    "PASS", # < chat_threshold,不匹配，已拒绝
    "CHAT", # >= chat_threshold,沟通中
    "SEEK", # >= borderline_threshold,寻求联系方式
    "CONTACT", # >= seek_threshold,已获得联系方式
]
```

**不一致问题：**
- ❌ 使用阈值变量（chat_threshold, borderline_threshold, seek_threshold）而不是固定值（7, 9）
- ❌ 缺少 GREET 阶段

---

### 3. agent/tools.py (analyze_resume_tool)

```python
if overall < 7:
    stage = 'PASS'
elif overall < 9:
    stage = 'GREET'  # ⚠️ 这里用的是 GREET
else:
    stage = 'SEEK'
```

**不一致问题：**
- ❌ 使用了 GREET，但参考定义中没有 GREET
- ❌ 没有处理 CONTACT 阶段

---

### 4. agent/states.py

```python
stage: Literal["GREET", "PASS", "CHAT", "SEEK", "CONTACT"]
```

**不一致问题：**
- ⚠️ 包含了 GREET，但参考定义中没有 GREET
- ✅ 包含了所有其他阶段

---

### 5. src/stats_service.py

```python
STAGE_FLOW = ["GREET", "CHAT", "SEEK", "CONTACT"]
```

**不一致问题：**
- ❌ 包含 GREET，但参考定义中没有 GREET
- ❌ 缺少 PASS 阶段（虽然代码中单独处理了 PASS）

---

## 🚨 主要不一致问题总结

### 问题 1: GREET 阶段的存在性
- **参考定义（STAGES）**: 没有 GREET
- **实际使用**: 多个地方使用了 GREET
  - agent/prompts.py 的 RECRUITER_PROMPT
  - agent/tools.py 的 analyze_resume_tool
  - agent/states.py
  - src/stats_service.py 的 STAGE_FLOW

### 问题 2: CHAT vs GREET 的混淆
- **参考定义**: overall_score>=7 → CHAT
- **实际逻辑**: overall_score>=7 → GREET（在 RECRUITER_PROMPT 和 analyze_resume_tool 中）

### 问题 3: 阈值定义不一致
- **参考定义**: 固定值（7, 9）
- **src/assistant_actions.py**: 使用变量（chat_threshold, borderline_threshold, seek_threshold）

### 问题 4: 阶段流程顺序
- **src/stats_service.py**: ["GREET", "CHAT", "SEEK", "CONTACT"]
- **参考定义**: 没有明确的流程顺序

---

## 💡 建议的统一方案

### 方案 A: 保留 GREET，统一为 5 个阶段

```python
STAGES = {
    "PASS": "< 7, 不匹配，已拒绝",
    "GREET": ">= 7, 已打招呼，等待回复",
    "CHAT": ">= 7, 沟通中（已回复）",
    "SEEK": ">= 9, 强匹配，主动寻求联系方式",
    "CONTACT": "已获得联系方式",
}
```

**阶段转换逻辑：**
- overall_score < 7 → PASS
- overall_score >= 7 且未回复 → GREET
- overall_score >= 7 且已回复 → CHAT
- overall_score >= 9 → SEEK
- 已获得联系方式 → CONTACT

### 方案 B: 移除 GREET，统一为 4 个阶段（符合参考定义）

```python
STAGES = {
    "PASS": "< 7, 不匹配，已拒绝",
    "CHAT": ">= 7, 沟通中",
    "SEEK": ">= 9, 强匹配，主动寻求联系方式",
    "CONTACT": "已获得联系方式",
}
```

**阶段转换逻辑：**
- overall_score < 7 → PASS
- overall_score >= 7 → CHAT
- overall_score >= 9 → SEEK
- 已获得联系方式 → CONTACT

**需要修改的文件：**
1. agent/prompts.py: RECRUITER_PROMPT 中的 GREET → CHAT
2. agent/tools.py: analyze_resume_tool 中的 GREET → CHAT
3. agent/states.py: 移除 GREET
4. src/stats_service.py: STAGE_FLOW 移除 GREET

---

## 📊 当前代码使用情况统计

| 阶段 | agent/prompts.py | src/assistant_actions.py | agent/tools.py | agent/states.py | src/stats_service.py |
|------|------------------|---------------------------|----------------|-----------------|----------------------|
| PASS | ✅ | ✅ | ✅ | ✅ | ✅ (单独处理) |
| GREET | ⚠️ (逻辑中) | ❌ | ✅ | ✅ | ✅ |
| CHAT | ✅ | ✅ | ❌ | ✅ | ✅ |
| SEEK | ✅ | ✅ | ✅ | ✅ | ✅ |
| CONTACT | ✅ | ✅ | ❌ | ✅ | ✅ |

---

## ✅ 建议

**推荐方案 B**（移除 GREET，统一为 4 个阶段），因为：
1. 符合参考定义（agent/prompts.py 的 STAGES）
2. 逻辑更简单清晰
3. GREET 和 CHAT 的区分在实际业务中可能不够明确

**如果必须保留 GREET**，则采用方案 A，但需要：
1. 更新 agent/prompts.py 的 STAGES 定义
2. 明确 GREET 和 CHAT 的区别和转换条件
3. 统一所有文件中的阶段定义

