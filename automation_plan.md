# Client-side Automation Orchestration Plan

## 1. Objectives
- Move all scheduling/business decisions from FastAPI (`boss_service.py`) into Streamlit so the browser automation API focuses on primitive actions only.
- Preserve existing Playwright automation primitives (`chat_actions.py`, `recommendation_actions.py`) while exposing missing operations as TODO stubs for future refinement.
- Provide a deterministic, auditable UI loop where each candidate flows through the four canonical stages (推荐 → 新招呼 → 沟通中 → 追结果) with live feedback (summary, analysis, action taken, status).
- Reuse the Threads-based `generate_message()` pipeline with a `purpose` flag so prompts adapt to greet / analyze / chat / resume updates.
- Avoid redundant resume fetches by reading from the Zilliz vector store when available before hitting Playwright again.

## 2. Available Automation Actions
### Chat primitives (`src/chat_actions.py`)
- `get_chat_list_action(page, limit)` — list chat sidebar items.
- `get_chat_history_action(page, chat_id)` — fetch right-pane conversation.
- `view_online_resume_action(page, chat_id)` — capture online resume (async pipeline + WASM hooks).
- `view_full_resume_action(page, chat_id)` — capture offline resume/PDF.
- `request_resume_action`, `send_message_action`, `accept_resume_action`, `discard_candidate_action`, `select_chat_job_action`, `get_chat_stats_action`.
- **New stubs**: `mark_candidate_stage_action` (#TODO), `notify_hr_action` (#TODO) for PASS/SEEK/CONTACT bookkeeping.

### Recommendation primitives (`src/recommendation_actions.py`)
- `_prepare_recommendation_page`, `select_recommend_job_action`, `list_recommended_candidates_action`, `view_recommend_candidate_resume_action`, `greet_recommend_candidate_action`.
- **New stub**: `skip_recommend_candidate_action` (#TODO) to label/skip cards without server logic yet.

### Assistant utilities (`src/assistant_actions.py`)
- `generate_message(..., purpose)` — unified Threads-based message generator (replaces legacy `generate_chat_message`).
- `analyze_candidate`, `upsert_candidate`, `get_cached_resume` (new helper pulling resume from Zilliz before re-downloading).
- Purpose presets: `chat`, `greet`, `analyze`, `add_resume`; extendable as needed.

## 3. Client-side Scheduler Blueprint
The Streamlit automation page replaces the server scheduler with a deterministic pipeline:

1. **推荐牛人 (Step 1)**
   - Fetch candidates via `GET /recommend/candidates`.
   - For each candidate index:
     1. Pull resume (`/recommend/candidate/{idx}/resume`).
     2. Run analysis (`POST /assistant/analyze-candidate`).
     3. Decide status (`GREET` vs `PASS`).
     4. If GREET → call `generate_message(..., purpose="greet")`, then `/recommend/candidate/{idx}/greet` (when implemented).
     5. Persist to store via `/assistant/upsert-candidate` with stage metadata.
     6. Display row in Streamlit (summary, score, action, resulting stage).

2. **聊天-新招呼 (Step 2)**
   - Source chat list using `get_chat_list_action` filtered to “新招呼”.
   - For each chat:
     1. Pull resume (`view_online_resume_action`).
     2. Run analysis; threshold decides `GREET` (send message + request resume) or `PASS`.
     3. Use `generate_message(..., purpose="chat")` for custom follow-ups.
     4. Upsert record (stage `GREET` or `PASS`).
     5. Streamlit table logs outcome.

3. **聊天-沟通中 (Step 3)**
   - Iterate “沟通中” chats.
     1. Sync chat history, fetch cached resume via `get_cached_resume` before re-downloading.
     2. If no offline resume: trigger `request_resume_action`.
     3. On full resume arrival re-run `analyze_candidate`; threshold -> `SEEK` vs `PASS`.
     4. When contact info appears, call `notify_hr_action` (#TODO) and set stage `CONTACT`.
     5. Display status for each candidate.

4. **追结果 (Step 4)**
   - Filter records older than 1 day in store (stage ∈ {GREET, SEEK}).
   - Generate nudges via `generate_message(..., purpose="chat")` or new `purpose="followup"` if added.
   - Send via `send_message_action`; log result to UI.

Each section renders a Streamlit expander with a dataframe/log lines summarising: `候选人 / 分析结果 / 动作 / 阶段 / thread_id`.

## 4. Data & Resume Handling
- Leverage `AssistantActions.get_cached_resume(candidate_id)` before Playwright fetches to skip 10s delays when data already lives in Zilliz.
- On every upsert, include stage, analysis summary, and thread metadata (`thread_id`, `assistant_id`) so later steps can resume context without recomputing.
- Maintain a lightweight local cache in Streamlit (e.g., `st.session_state['automation_logs']`) for rerun persistence.

## 5. Streamlit Implementation Notes
- Replace current `pages/1_自动化.py` scheduler toggle UI with four collapsible panels, each containing a “Run step” button that executes the loop synchronously.
- Provide progress via `st.progress` / `st.spinner` for each candidate to keep the operator informed.
- Allow job selection via sidebar (reuse existing `load_jobs()`). Job metadata should include optional `assistant_id` for message generation.
- Log entries can be aggregated using `st.dataframe` or `st.markdown` bullet lists appended through `st.session_state`.
- Keep API interaction functions (`call_api`) for server primitives; orchestrate error handling client-side.

## 6. Server Follow-ups / TODOs
- Implement the placeholder stage-tagging and HR notification actions once corresponding UI selectors are confirmed.
- Add REST endpoints for stage updates (`POST /chat/stage`) and HR notifications if UI automation proves unstable.
- Remove legacy BRD scheduler once Streamlit workflow is stable.

## 7. Change Management
- Update documentation (technical.md) to reflect client-driven orchestration and new `purpose` flag.
- Deprecate any docs referring to server-side scheduler or `generate_chat_message`.
- Coordinate QA to validate four-step flow end-to-end using the new Streamlit interface before removing old scheduler endpoints.
