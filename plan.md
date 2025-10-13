# FastAPI UI Migration Plan

## Goals & Non-Goals
- Replace the Streamlit console under `pages/` with a server-rendered FastAPI experience without regressing existing workflows.
- Deliver a single FastAPI process that serves both the existing JSON APIs and the new HTML UI.
- Preserve current automation behaviour (Playwright control, scheduler, assistant actions, resume capture) while only swapping the presentation layer.
- **Out of scope**: rewriting core automation logic in `src/`, changing API contracts already consumed by external tools, or redesigning long-running scheduler logic.

## Current UI Surface (Streamlit)
- `pages/1_自动化.py`: starts/stops `BRDWorkScheduler`, displays status, exposes toggles for recommend/chat/follow-up flows.
- `pages/2_助理选择.py`: CRUD for assistants through `/assistant/*` endpoints, manages instructions/templates metadata.
- `pages/4_岗位画像.py`: edits YAML job profiles, loads from `config/jobs.yaml`, uploads Markdown to `config/company.md`.
- `pages/5_消息列表.py`: main dialog console; fetches `/chat/dialogs`, resumes (`/resume/*`), chat history, runs AI analysis/drafting, triggers follow-up actions.
- `pages/6_推荐牛人.py`: handles recommendation list from `/recommend/*`, lets user greet/discard candidates.
- `pages/7_问答库.py`: manages FAQ entries, interacts with `config/qa.yml`.
- Shared helpers in `streamlit_shared.py` provide cached API calls, session state, sidebar controls.

## Target FastAPI Web Stack
- Create `web/` package housing `templates/`, `static/`, `routes/`, and optional `services/` (utility layer replacing `streamlit_shared`).
- Use `Jinja2Templates` for HTML, HTMX for partial swaps, Alpine.js for lightweight state, TailwindCSS (with DaisyUI optional) for styling.
- Mount `StaticFiles` at `/static`; keep JSON APIs under existing prefixes while exposing UI entry points at `/web/*`.
- Introduce Server-Sent Events (SSE) endpoints for real-time sections (scheduler status, automation streams).

## Work Breakdown

### Phase 0 – Prep & Environment
- Audit `requirements.txt`: add `jinja2`, `python-multipart` (if needed for forms/uploads), `itsdangerous` (for CSRF if introduced), remove `streamlit` once migration completes.
- Confirm `boss_service.py` exposes a FastAPI `app`; plan integration points for templates, static files, and routers.
- Catalogue config files (`config/jobs.yaml`, `config/company.md`, `config/qa.yml`) and ensure read/write permissions align with FastAPI runtime.

### Phase 1 – Foundation Infrastructure
- Establish `web/__init__.py` and router registration in `boss_service.py` (mount templates, static assets, include routers with prefixes).
- Build base template (`web/templates/base.html`) with shared head, navbar linking to all pages, flash message area, and block sections for content/custom scripts.
- Provide layout components: partials for navigation, pagination controls, confirmation dialogs.
- Create placeholder landing page (`web/templates/index.html`) summarising system status and linking to each module.

### Phase 2 – Shared Utilities & Services
- Port logic from `streamlit_shared.py` into reusable FastAPI-friendly services:
  - `web/services/config_service.py` for job YAML load/save, company markdown handling.
  - `web/services/assistant_service.py` wrapping `/assistant/*` API calls.
  - `web/services/chat_service.py` consolidating `/chat`, `/resume`, `/recommend` access and data shaping.
- Implement caching where helpful (e.g., `functools.lru_cache` with TTL via `asyncio.create_task` invalidation) to replace Streamlit cache.
- Standardise response models for UI consumption; define Pydantic models for forms and SSE payloads.

### Phase 3 – Page Migrations
- **Automation (`/web/automation`)**
  - HTML form replicating scheduler toggles; POST to start/stop endpoints calling `BRDWorkScheduler`.
  - SSE feed (or background polling via HTMX) for live status from `BRDWorkScheduler.get_status()`.
  - Display current config (mirrors Streamlit JSON) and graceful error handling when scheduler unavailable.
- **Assistant Management (`/web/assistants`)**
  - List assistants via `/assistant/list`; provide modals/forms for create, update, delete.
  - Support metadata editing using dynamic form fields; convert `DataFrame` UI to simple add/remove rows.
  - Integrate template defaults (`default_*` strings) and persist via `/assistant/create`, `/assistant/update/{id}`, `/assistant/delete/{id}`.
- **Job Profiles (`/web/jobs`)**
  - Render roles from YAML with CRUD (create/edit/delete roles) and upload handler for `config/company.md`.
  - Add validation and preview of Markdown/company profile.
  - Preserve `SessionKeys.SELECTED_JOB_INDEX` equivalent by storing selected job in query params or session cookie.
- **Message Console (`/web/candidates`)**
  - Dialog list view with filters (`tab`, `status`, `job_title`, `limit`); partial reload using HTMX.
  - Detail pane for selected chat: resume viewer (online/full), chat history, AI analysis (`/assistant/generate-message`), follow-up actions (send message, request resume/contact, discard).
  - Provide resume fetch status indicators and empty states similar to expander UX in Streamlit.
  - Emit toasts / event triggers when actions succeed (e.g., `HX-Trigger: messageSent`).
- **Recommendations (`/web/recommendations`)**
  - Table to display recommended candidates from `/recommend/candidates`; actions to greet or discard using existing endpoints.
  - Inline resume viewer using `/recommend/candidate/{idx}/resume`.
- **FAQ Management (`/web/qa`)**
  - CRUD over QA YAML; maintain structure used by Streamlit (categories/questions/answers).
  - Add simple search/filter to locate entries quickly.

### Phase 4 – Cross-Cutting Enhancements
- Implement authentication/authorisation guard if needed (basic password, token, or leverage existing session concept).
- Centralise flash messaging, confirmation dialogs, loading indicators.
- Add SSE channel for autonomous agent logs once `src/scheduler` exposes stream of events; hook into `/web/automation/stream`.
- Provide client-side utilities in `web/static/js/app.js` (Alpine stores for selected job/assistant, SSE wiring).

### Phase 5 – Cleanup & Documentation
- Remove Streamlit dependencies: delete `pages/`, `streamlit_shared.py`, related imports in repo; update `README.md` and `docs/technical.md` to describe new UI.
- Add developer documentation covering template structure, local development (`uvicorn boss_service:app --reload`), and deployment steps.
- Ensure `start_service.py` launches FastAPI-only stack; optionally add CLI flag to skip Streamlit.

## Implementation Notes
- Reuse existing FastAPI endpoints where possible; when UI needs new behaviour, add dedicated routers under `web.routes.*` that orchestrate calls to `src/*` modules or JSON endpoints instead of duplicating logic.
- Manage long-running tasks (scheduler start/stop) asynchronously; protect with locks to avoid race conditions similar to Streamlit session checks.
- For file edits (YAML/Markdown), use synchronous file IO wrapped in thread executors if necessary to avoid blocking event loop.
- Adopt consistent naming for routes and templates (e.g., `web/routes/candidates.py` renders `templates/candidates/index.html`, partials under `templates/candidates/partials/`).

## Testing & Rollout
- Add FastAPI router tests verifying HTTP 200 responses, form validation, and SSE streaming (use `TestClient`).
- Exercise end-to-end flows manually in browser: scheduler toggle, assistant CRUD, candidate messaging.
- Monitor logs/Sentry after deployment to confirm SSE and template rendering behave under load.
- Stage the migration by introducing new routes behind `/web` while Streamlit remains; once new UI validated, remove Streamlit assets.

## Open Questions / Risks
- Assess whether authentication is required for the new UI (Streamlit previously relied on obscurity); plan for minimal auth if needed.
- Determine how much state (selected job/assistant) should persist between requests—consider signed cookies or query parameters.
- Verify SSE compatibility with existing hosting environment (reverse proxies, timeouts).
- Confirm that file writes to `config/` remain safe under concurrent access (might require file locks).

