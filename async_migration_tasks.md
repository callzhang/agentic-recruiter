# Async Migration Plan for `boss_service`

## 1. Purpose & Scope
- Replace the synchronous Playwright/FastAPI implementation in `boss_service.py` with an async-first architecture that eliminates `greenlet.error` and aligns with the wider async stack.
- Cover all server-side modules that directly or indirectly depend on Playwright-driven browser automation (`boss_service.py`, `src/chat_actions.py`, `src/recommendation_actions.py`, `src/boss_utils.py`, `src/assistant_actions.py`, related helpers).
- Preserve REST API contracts that are consumed by Streamlit pages, schedulers, and external tooling (`start_service.py`, pages/`*.py`, `src/scheduler.py`).

## 2. Current Architecture Snapshot
- `boss_service.BossService` (singleton) exposes FastAPI routes; uses `run_in_threadpool` to bootstrap sync Playwright and keeps global state: `playwright`, `context`, `page`, `is_logged_in`, `browser_lock` (`threading.Lock`), `startup_complete` (`threading.Event`).
- Route families (chat, recommendation, resume, assistant, scheduler, QA store) invoke synchronous `src/*_actions.py` helpers that manipulate the shared `page`.
- Long-lived Chrome session is attached via CDP (persistent profile stored under temp dir, storage state saved to `settings.STORAGE_STATE`).
- Background scheduler and assistant APIs live in `src/assistant_actions.py` and `src/scheduler.py`, invoked synchronously inside route handlers.

## 3. Design Principles for the Async Rewrite
- **Single event loop ownership**: run Playwright via `async_playwright()` and ensure FastAPI handlers stay fully async (no `run_in_threadpool`, no blocking locks).
- **Explicit concurrency control**: replace `threading.Lock/Event` with `asyncio.Lock/Event`; guard shared browser state with `async with self.browser_lock` and keep mutations atomic.
- **Await every Playwright interaction**: enforce `await page.goto(...)`, `await locator.click(...)`, etc.; forbid `.wait_for_timeout` or `.inner_text` without `await`.
- **Non-blocking waits**: substitute `time.sleep`, busy polling, or synchronous loops with `await asyncio.sleep` and `asyncio.wait_for`.
- **Graceful degradation**: if the async migration introduces partial functionality, keep an escape hatch (`boss_service_async.py`) and feature flag the deployment.
- **Observable operations**: preserve structured logging via `src.global_logger.get_logger`, annotate async paths with contextual info (current chat/job/assistant) for easier debugging.
- **Parity-first**: maintain existing response schemas, error semantics, and scheduler side-effects so downstream clients remain untouched.

## 4. Migration Inventory (Functions & Shared State)

### 4.1 `boss_service.BossService`
- Lifecycle & session: `_startup_sync`, `_shutdown_sync`, `_graceful_shutdown`, `start_browser`, `_ensure_page`, `_ensure_browser_session`, `_ensure_browser_session_locked`, `_shutdown_thread` → async counterparts (`_startup_async`, `_shutdown_async`, etc.).
- State fields: `self.playwright`, `self.context`, `self.page`, `self.browser_lock`, `self.startup_complete`, `self.is_logged_in`, `self.shutdown_requested` → transition to async types (`asyncio.Lock`, `asyncio.Event`, explicit `Browser`/`Page` typing) and ensure thread affinity.
- Route handlers (all functions defined inside `setup_routes`) → convert to `async def` and update helper calls (`await get_chat_list_action_async(...)`).
- Utility constants/values: `DEFAULT_GREET_MESSAGE`, `settings.CDP_URL`, `settings.STORAGE_STATE` remain reused; ensure any direct file I/O (storage state persistence) is awaited or offloaded with `run_in_executor` if necessary.

### 4.2 `src/chat_actions.py`
- Functions to port: `_prepare_chat_page`, `_go_to_chat_dialog`, `select_chat_job_action`, `get_chat_stats_action`, `request_resume_action`, `send_message_action`, `check_full_resume_available`, `view_full_resume_action`, `discard_candidate_action`, `get_chat_list_action`, `get_chat_history_action`, `accept_resume_action`, `view_online_resume_action`.
- Replace sync Playwright imports (`from playwright.sync_api`) with async equivalents and update all locator interactions to awaited calls.
- Replace blocking waits (`time.sleep`, `.count()`, `.inner_text()`) with awaited versions or asynchronous polling loops.

### 4.3 `src/recommendation_actions.py`
- Convert `_prepare_recommendation_page`, `select_recommend_job_action`, `list_recommended_candidates_action`, `view_recommend_candidate_resume_action`, `greet_recommend_candidate_action` to async; adapt iframe handling (`await frame.wait_for_selector`).
- Replace `time.sleep` loops and `.all()` patterns with `await locator.all()` or asynchronous iteration wrappers; consider streaming large candidate lists to avoid long blocking operations.

### 4.4 `src/boss_utils.py`
- Migrate `ensure_on_chat_page`, `find_chat_item`, `close_overlay_dialogs` to async; provide thin sync wrappers if other modules (e.g., Streamlit scripts) still rely on synchronous behaviour during transition.

### 4.5 `src/assistant_actions.py`
- Identify Playwright usage (none directly) but note that several FastAPI routes (`analyze_candidate_api`, `generate_followup_api`, etc.) synchronously call into OpenAI APIs and scheduler logic. Decide whether to:
  - a) wrap blocking OpenAI SDK calls in `asyncio.to_thread`, or
  - b) defer full async rewrite until SDK migration is feasible.
- Ensure scheduler hooks (`assistant_actions.start_scheduler/stop_scheduler`) remain thread-safe within the new async context (may need `asyncio.create_task` wrappers).

### 4.6 Other touch points
- `start_service.py`: update service entrypoint to launch `boss_service_async.app` (or feature flag to choose between sync/async).
- `src/scheduler.py`: verify background jobs interacting with FastAPI endpoints remain compatible; adjust any direct service imports.
- Streamlit pages under `pages/`: no code changes expected but run regression checks once the async service is live.

## 5. Additional Helpers & Refactors
- Introduce `src/playwright_async_utils.py` (optional) to house shared async wrappers (e.g., `async wait_for_visible(locator, timeout)`), reducing duplication.
- Provide transitional adapters (e.g., `chat_actions_async.py`) and toggle via dependency injection so we can stage the rollout per endpoint.
- Implement an async-aware login monitor (e.g., `await ensure_logged_in(page, timeout)` using `asyncio.wait_for`) to consolidate login checks scattered across modules.
- Add a helper to safely restart the async browser session (`await service.reset_browser(reason: str)`) invoked from routes detecting corruption.

## 6. Coding Style & Conventions
- Follow existing project guidelines: minimal but meaningful comments, ASCII encoding, logging via `logger.info/debug/error` with structured context.
- Adopt `async def` naming parity (keep function names the same where possible; suffix with `_async` only for interim coexistence).
- Prefer `asyncio.create_task` over `ensure_future`; cancel tasks explicitly during shutdown.
- Reuse type hints (`Optional[Page]`, `Dict[str, Any]`) and extend where beneficial to surface async semantics (`-> Awaitable[Dict[str, Any]]`).
- Keep public API signatures unchanged for route handlers; only internal implementation shifts to async awaited calls.

## 7. Testing Strategy
- **Unit tests**: add coverage for async utility functions (e.g., chat actions) using `pytest.mark.asyncio` and Playwright’s async fixtures with mocked pages.
- **Integration tests**: spin up the async FastAPI app with `httpx.AsyncClient` to exercise key endpoints (status, chat list, resume actions) against a mocked CDP server or Playwright’s `BrowserType.launch` in headed/CI mode.
- **Regression scripts**: reuse `examples/` workflows to verify candidate greeting, resume viewing, and scheduler interactions end-to-end.
- **Load & concurrency**: simulate concurrent requests (`/chat/dialogs`, `/resume/view_full`, `/assistant/*`) to ensure the async lock prevents race conditions without deadlocking.
- **Manual checks**: document QA scripts for real browser sessions (login persistence, soft restart, shutdown) before production switch.

## 8. Execution Phases
1. **Preparation**
   - Freeze the current sync behaviour behind a feature flag (`BOSS_SERVICE_ASYNC=0/1`).
   - Land shared async helpers and unit tests; keep `boss_service.py` untouched.
2. **Async helpers rollout**
   - Convert `src/boss_utils.py`, `src/chat_actions.py`, `src/recommendation_actions.py` to expose async variants while optionally retaining sync wrappers.
   - Add parity tests to guarantee response structure equivalence.
3. **Service migration**
   - Rewrite `BossService` into async form (use `BossServiceAsync` prototype as reference), update FastAPI routes, and adjust lifecycle/shutdown logic.
   - Update `start_service.py` and deployment scripts (systemd, PM2, etc.) to import the new module.
4. **Stabilisation**
   - Run full regression test suite, manual QA, and monitor for browser-session edge cases (login timeout, CDP disconnect).
   - Remove deprecated sync code once confidence is high, including sync wrappers and `run_in_threadpool` usage.

## 9. Operational & Other Considerations
- **Error handling**: convert bare `except Exception` blocks into context-aware handlers that re-raise or surface HTTP errors; ensure unawaited tasks are logged.
- **Resource cleanup**: confirm shutdown persists storage state and closes CDP connections; guard against lingering Chrome processes.
- **Configuration**: evaluate whether timeouts (`timeout=1000`) need tuning under async to avoid cancellations; centralise in settings if necessary.
- **Observability**: extend `docs/status.md` (see documentation task) with monitoring checkpoints for async service (startup duration, login health, scheduler state).
- **Training & handoff**: brief contributors on async Playwright patterns, update onboarding docs (coding conventions, test harness usage).

## 10. Deliverables Checklist
- [ ] Async helpers committed with tests
- [ ] `BossService` async rewrite merged
- [ ] Feature flag toggles available for rollback
- [ ] Documentation updated (`docs/status.md`, README/CHANGELOG)
- [ ] Deployment scripts aligned (`start_service.py`, CI jobs)
- [ ] Sync implementation deprecated and removed post-rollout
