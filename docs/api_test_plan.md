# API Test Plan

## Objectives
- Validate every FastAPI endpoint provided by `boss_service.py`, covering both JSON APIs and the new `/web` UI routes.
- Exercise positive flow, parameter validation, and representative error scenarios without relying on a live Playwright session or external OpenAI services.
- Provide a repeatable automation strategy that integrates with `pytest` and the existing test suite.

## Scope & Assumptions
- Tests are executed locally with Playwright browsers **not** required; browser interaction is mocked.
- Network calls to upstream services (Boss直聘, OpenAI, Sentry) are stubbed; we verify request/response contracts only.
- File system state (e.g., `config/jobs.yaml`, candidate store) is simulated through monkeypatching.
- Authentication is out of scope (service currently assumes trusted local access).

## Tooling
- `pytest` + `fastapi.testclient.TestClient` for endpoint automation.
- `monkeypatch` (built into pytest) to replace Playwright helpers, candidate store accessors, and OpenAI client methods.
- `httpx.AsyncClient` mocking is unnecessary because the service code already uses internal helpers; instead we patch the helpers directly.

## Test Matrix

### 1. System / Diagnostics
- `GET /status` – returns heartbeat metadata and chat counters.
- `POST /login` – verifies login flag is surfaced.
- `GET /sentry-debug` – triggers unified exception handler, expect 500 JSON error.
- `POST /restart` – confirms soft restart coroutine invoked.
- `GET /debug/page` – returns sanitized page content snapshot.
- `GET /debug/cache` – validates both empty cache and custom event manager responses.

### 2. Chat Operations
- `GET /chat/dialogs` – limits, tab/status filters honoured.
- `GET /chat/{chat_id}/messages` – returns formatted history list.
- `POST /chat/{chat_id}/send` – forwards trimmed payload, success flag.
- `POST /chat/greet` – same as send but via greet helper.
- `GET /chat/stats` – mirrors `get_chat_stats_action` output.

Negative / edge cases:
- Invalid chat IDs raise handled errors (mock helper to throw `ValueError`, expect 400).

### 3. Resume Management
- `POST /resume/request` – succeeds when helper returns truthy.
- `POST /resume/view_full` – returns resume payload.
- `POST /resume/check_full_resume_available` – `True/False` branch.
- `POST /resume/online` – fallback payload used.
- `POST /resume/accept` – verifies acceptance flag.

Error path: helper raises timeout → exception handler returns 408 with message.

### 4. Candidate Actions
- `POST /candidate/discard` – ensures discard helper invoked with chat id.
- `GET /candidate/{chat_id}` – pulls record from `candidate_store`.

### 5. Recommendation Workflows
- `GET /recommend/candidates` – returns card summary list.
- `GET /recommend/candidate/{index}/resume` – yields resume detail.
- `POST /recommend/candidate/{index}/greet` – success boolean.
- `POST /recommend/select-job` – confirms selection payload.

Edge case: greeting helper raises `ValueError`, expect 400.

### 6. Assistant & Thread APIs
- `POST /assistant/generate-message` – returns mock response.
- `GET /assistant/list` – list of assistant metadata.
- `POST /assistant/create`, `/assistant/update/{assistant_id}`, `/assistant/delete/{assistant_id}` – CRUD interactions with stub OpenAI client.
- `POST /thread/init-chat`, `GET /thread/{thread_id}/messages` – thread bootstrap and retrieval.

Negative tests: OpenAI client raising `RuntimeError` surfaces 500.

### 7. Web Dashboard Endpoints
- `GET /web` – HTML render succeeds.
- `GET /web/stats` – utilises mocked `service.get_status`, returns Tailwind cards.
- `GET /web/recent-activity` – renders placeholder activity feed.
- `GET /web/candidates`, `/web/automation`, `/web/assistants`, `/web/jobs`, `/web/qa` – smoke test HTMX template responses.
- Auxiliary HTMX endpoints (`/web/candidates/list`, `/web/assistants/list`, etc.) covered via focused unit tests using `httpx` mocks.

### 8. Automation (Scheduler) API
- `/web/automation/start|pause|next|stop|status|stream` – validated separately via component tests (beyond scope of this document’s initial code but covered in future iterations once scheduler is fully injectable).

## Automation Strategy
1. **Fixture setup** – monkeypatch `BossServiceAsync._ensure_browser_session` to return dummy Playwright page, set `startup_complete` event.
2. **Helper stubs** – create reusable coroutine factories (`make_async_stub`) for patching Playwright-dependent helpers.
3. **Response assertions** – verify HTTP status, JSON/HTML payload and that patched helpers were called with expected arguments.
4. **Error handling** – for each category, include at least one test where the helper raises `ValueError` or `PlaywrightTimeoutError` to assert the unified exception handler mapping.
5. **Reporting** – leverage `pytest -q` output and integrate into CI (GitHub Actions or local pre-commit hook).

## Manual Smoke Tests
- Launch service with `uvicorn boss_service:app --reload`.
- Navigate through `/web` routes to confirm HTMX interactions and SSE streams function end-to-end with real browser + Playwright.
- During manual run, tail logs/Sentry to ensure instrumentation triggers.

## Exit Criteria
- All automated tests in `test/test_boss_service_api.py` pass.
- Coverage reports (optional `pytest --cov`) show execution through each FastAPI route handler.
- Known limitations (e.g., automation SSE integration) documented and tracked for follow-up.
