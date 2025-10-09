# Four Independent Automation Workflow Entry Points - Implementation Plan

## 1. Objectives
- Move all scheduling/business decisions from FastAPI (`boss_service.py`) into Streamlit so the browser automation API focuses on primitive actions only.
- Preserve existing Playwright automation primitives (`chat_actions.py`, `recommendation_actions.py`) while exposing missing operations as TODO stubs for future refinement.
- Provide **four independent workflow entry points** where each can execute independently, processing candidates from different sources and updating their stage states with live feedback (summary, analysis, action taken, status).
- Reuse the Threads-based `generate_message()` pipeline with a `purpose` flag so prompts adapt to greet / analyze / chat / followup.
- Avoid redundant resume fetches by reading from the Zilliz vector store when available before hitting Playwright again.

## 2. Business Logic Overview

**CRITICAL**: These are **four independent entry points**, NOT a sequential pipeline. Each workflow can execute independently and update candidate stage states bidirectionally.

### Workflows vs Stages

**Work flow Entry Points** (4 independent):
- **推荐牛人**: Process recommend page candidates
- **新招呼**: Process new greetings in chat
- **沟通中**: Process active conversations
- **追结果**: Follow up on stale candidates

**Candidate Stage States** (bidirectional transitions):
```
PASS ↔ GREET ↔ SEEK ↔ CONTACT
        ↕
  WAITING_LIST
```

### Data Flow Architecture
```
推荐牛人 Entry → Create record (chat_id=NULL)
新招呼 Entry   → Query by chat_id → Update record (add chat_id)
沟通中 Entry   → Query by chat_id → Update record (update stage/full_resume)
追结果 Entry   → Filter by stage → Update record (update updated_at)
```

## 3. Available Automation Actions

### Chat primitives (`src/chat_actions.py`)
- `get_chat_list_action(page, limit)` — list chat sidebar items with tab/status filtering
- `get_chat_history_action(page, chat_id)` — fetch right-pane conversation history
- `view_online_resume_action(page, chat_id)` — capture online resume (async pipeline + WASM hooks)
- `view_full_resume_action(page, chat_id)` — capture offline resume/PDF attachments
- `request_resume_action`, `send_message_action`, `accept_resume_action`, `discard_candidate_action`
- `select_chat_job_action`, `get_chat_stats_action`
- **New stubs**: `mark_candidate_stage_action` (#TODO), `notify_hr_action` (#TODO) for PASS/SEEK/CONTACT bookkeeping

### Recommendation primitives (`src/recommendation_actions.py`)
- `_prepare_recommendation_page`, `select_recommend_job_action`, `list_recommended_candidates_action`
- `view_recommend_candidate_resume_action`, `greet_recommend_candidate_action`
- **New stub**: `skip_recommend_candidate_action` (#TODO) to label/skip cards without server logic yet

### Assistant utilities (`src/assistant_actions.py`)
**Thread API architecture (v2.2.0)**:
- `init_chat(name, job_info, resume_text, chat_id=None, chat_history=None)` — create OpenAI thread + Zilliz record, return thread_id
- `generate_message(thread_id, assistant_id, purpose, user_message=None, full_resume=None, instruction=None, format_json=False)` — generate message using existing thread
- Purpose presets: `analyze`, `greet`, `chat`, `followup`
- Thread stores ALL context: job description, resume, analysis, chat history
- `analyze_candidate`, `upsert_candidate` — maintain Zilliz for stage tracking and routing
- **Important**: `init_chat` called ONLY when resume_text is available and BEFORE analysis
- **Named Parameters**: Explicit parameters instead of dictionaries for better clarity and type safety

### Data storage (`src/candidate_store.py`)
**Zilliz role**: Stage tracker + Router + Cache (NOT primary conversation store)
- `upsert_candidate` — store/update stage, thread_id, analysis, resume cache
- `get_candidate_by_chat_id` — retrieve candidate to get thread_id for routing
- `get_cached_resume` — retrieve resume_text/full_resume from cache (avoid 10s browser fetch)
- Schema: `candidate_id`, `chat_id` (nullable), `thread_id`, `stage`, `resume_vector`, `resume_text`, `full_resume`, `analysis`, `updated_at`

## 4. Four Independent Workflow Implementations

The Streamlit automation page (`pages/1_自动化.py`) provides **four independent workflow entry points**, each with its own execution button:

### Workflow 1: 推荐牛人 (Recommend Page Entry)
**API Endpoints**: `GET /recommend/candidates`, `/recommend/candidate/{idx}/resume`, `init_chat`, `generate_message`

**Implementation Steps (Thread API)**:
1. Fetch candidates via `GET /recommend/candidates`
2. For each candidate index:
   - Pull resume: `/recommend/candidate/{idx}/resume` → get resume_text
   - **Init chat**: `init_chat(name=name, job_info={position, description}, resume_text=resume_text)` → get thread_id, candidate_id
   - **Analyze**: `generate_message(thread_id, purpose="analyze")` → get analysis, updates Zilliz stage
   - Stage decision: If stage in [`GREET`, `SEEK`, `WAITING_LIST`] → continue, else (`PASS`) → skip
   - **Greet**: `generate_message(thread_id, purpose="greet")` + `/recommend/candidate/{idx}/greet`
   - Zilliz now has: thread_id, stage, analysis, resume_text, chat_id=NULL
3. Display: Streamlit table with `候选人 / 分析结果 / 动作 / 阶段 / thread_id`

### Workflow 2: 新招呼 (New Greetings Entry)
**API Endpoints**: `get_chat_list_action`, `get_candidate_by_chat_id`, `init_chat`, `generate_message`, `send_message_action`

**Implementation Steps (Thread API)**:
1. Source chat list: `get_chat_list_action(tab="新招呼", status="未读")`
2. For each chat:
   - Query record: `get_candidate_by_chat_id(chat_id)` from Zilliz → get thread_id if exists
   - If no record:
     - Pull resume: `view_online_resume_action(chat_id)` → get resume_text
     - **Init chat**: `init_chat(name=name, job_info=job_info, resume_text=resume_text, chat_id=chat_id)` → get thread_id
     - **Analyze**: `generate_message(thread_id, purpose="analyze")` → updates stage
   - **Generate reply**: `generate_message(thread_id, purpose="chat", user_message=latest_from_candidate)`
   - Update Zilliz: chat_id (if new), stage, updated_at
3. Display: Streamlit table logs outcome

### Workflow 3: 沟通中 (Active Chats Entry)
**API Endpoints**: `get_candidate_by_chat_id`, `generate_message`, `request_resume_action`, `view_full_resume_action`, `notify_hr_action`

**Implementation Steps (Thread API)**:
1. Iterate "沟通中" chats: `get_chat_list_action(tab="沟通中", status="未读")`
2. For each chat:
   - Query record: `get_candidate_by_chat_id(chat_id)` → get thread_id
   - Cache priority: Check Zilliz `full_resume` field (avoid 10s browser fetch)
   - Resume request: If no `full_resume` in Zilliz, trigger `request_resume_action`
   - Full resume: `view_full_resume_action` when available
   - **Re-analyze**: `generate_message(thread_id, purpose="analyze", additional_context={full_resume})` → **stage can go backwards** (e.g., `SEEK` → `GREET`)
   - **Generate reply**: `generate_message(thread_id, purpose="chat", user_message=latest_from_candidate)`
   - Contact info: When phone/WeChat appears, call `notify_hr_action` (#TODO) → update stage to `CONTACT`
   - Update Zilliz: `stage`, `full_resume` (cache), `updated_at`
3. Display: Status for each candidate

### Workflow 4: 追结果 (Follow-up Entry)
**API Endpoints**: Zilliz query filter, `generate_message`, `send_message_action`

**Implementation Steps (Thread API)**:
1. Filter: Zilliz query `updated_at > 1 day AND stage IN ['GREET', 'SEEK', 'WAITING_LIST']` → get candidate list with thread_id
2. For each candidate:
   - **Generate nudge**: `generate_message(thread_id, purpose="followup")` → uses complete conversation history from thread
   - Send: `send_message_action`
   - Update Zilliz: `updated_at`, potentially update `stage` based on response
3. Display: Follow-up results

**UI Layout**: Four independent panels/buttons in Streamlit, each with dataframe/log lines summarising: `候选人 / 分析结果 / 动作 / 阶段 / thread_id`

## 5. Data & Resume Handling

### Zilliz Integration
- Leverage `AssistantActions.get_cached_resume(candidate_id)` before Playwright fetches to skip 10s delays when data already lives in Zilliz
- On every upsert, include stage, analysis summary, and thread metadata (`thread_id`, `assistant_id`) so later workflows can resume context without recomputing
- Support nullable `chat_id` field: recommend workflow creates records with `chat_id=NULL`, chat workflows query by `chat_id` directly
- **No semantic search needed**: Chat workflows use `chat_id` as direct lookup key
- Stage values: `PASS`, `GREET`, `SEEK`, `CONTACT`, `WAITING_LIST` - all support bidirectional transitions

### Streamlit Caching
- Maintain a lightweight local cache in Streamlit (e.g., `st.session_state['automation_logs']`) for rerun persistence
- Use `@st.cache_data` for job configuration and API responses
- Cache invalidation on candidate updates (create/update/delete)

## 6. Streamlit Implementation Notes

### UI Layout (`pages/1_自动化.py`)
- Replace current scheduler toggle UI with **four independent execution panels/buttons**
- Each workflow has its own "Run" button that executes independently
- Provide progress via `st.progress` / `st.spinner` for each candidate
- Allow job selection via sidebar (reuse existing `load_jobs()`)
- Job metadata should include optional `assistant_id` for message generation
- Clearly indicate that workflows are independent, not sequential

### Data Display
- Log entries aggregated using `st.dataframe` or `st.markdown` bullet lists
- Display format: `候选人 / 分析结果 / 动作 / 阶段 / thread_id`
- Real-time updates via `st.session_state` persistence
- Error handling and retry mechanisms client-side

### API Integration
- Keep API interaction functions (`call_api`) for server primitives
- Orchestrate error handling client-side
- Support batch operations for efficiency

## 7. Implementation TODOs

### Missing Functions
- [ ] `mark_candidate_stage_action(chat_id, stage)` - Support all stages including `WAITING_LIST`
- [ ] `notify_hr_action(candidate_info)` - DingTalk/HTTP notification (partially exists)
- [ ] `skip_recommend_candidate_action(index)` - Label/skip cards
- [ ] `purpose="followup"` prompt variant for workflow 4
- [ ] Add `WAITING_LIST` to Zilliz schema as valid stage value

### Server Endpoints
- [ ] Add REST endpoints for stage updates (`POST /chat/stage`) if UI automation proves unstable
- [ ] Enhance HR notification endpoints
- [ ] Remove legacy BRD scheduler once independent workflows are stable

### Data Management
- [ ] Implement chat_id-based direct lookup (no semantic search)
- [ ] Add candidate deduplication logic
- [ ] Enhance Zilliz query capabilities for stage filtering (including `WAITING_LIST`)
- [ ] Support bidirectional stage transitions in all workflows

## 8. Change Management

### Documentation Updates
- [x] Update `docs/technical.md` to reflect independent workflows and bidirectional stage transitions
- [x] Update `tasks.md` with v2.2.0 four independent automation workflow entry points
- [x] Consolidate `docs/automation_plan.md` with concrete implementation details
- [x] Clarify workflows vs stages distinction across all documentation
- [ ] Deprecate any docs referring to server-side scheduler or `generate_chat_message`

### Testing & Validation
- [ ] Coordinate QA to validate each workflow independently using the new Streamlit interface
- [ ] Test bidirectional stage transitions (including backward transitions)
- [ ] Validate Zilliz integration with chat_id-based direct lookup
- [ ] Test all stage values including `WAITING_LIST`
- [ ] Performance testing for each workflow independently

### Deployment
- [ ] Gradual rollout of independent automation workflows
- [ ] Monitor system performance and error rates for each workflow
- [ ] User training emphasizing independent workflow execution
- [ ] Documentation updates to reflect architectural changes
