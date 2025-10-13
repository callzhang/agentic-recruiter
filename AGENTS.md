# Repository Guidelines

## Project Structure & Module Organization
- `boss_service.py` exposes the FastAPI endpoints and orchestrates automation flows implemented in `src/`.
- `src/` holds domain modules (`chat_actions.py`, `assistant_actions.py`, `candidate_store.py`, etc.); keep new flows modular and reuse shared helpers.
- `boss_app.py` drives the Streamlit UI, with page components in `pages/` and reusable widgets in `streamlit_shared.py`.
- Configuration lives in `config/`, runtime artifacts in `data/`, documentation in `docs/`, and supportive tooling in `scripts/`, `examples/`, and `web/`. Tests belong in `test/`.

## Build, Test, and Development Commands
- Prepare a Python 3.11+ virtual environment, then install dependencies and browser drivers:
```bash
pip install -r requirements.txt
playwright install chromium
```
- Start services locally for manual verification:
```bash
python start_service.py
streamlit run boss_app.py
```
- Run formatting and linting before pushing:
```bash
black .
ruff check .
```

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation, descriptive snake_case for functions and variables, and PascalCase for classes.
- Annotate public functions with type hints, add concise docstrings, and prefer dataclasses when modeling structured payloads.
- For Playwright steps, rely on `wait_for_selector`, avoid fixed sleeps, and guard shared state (locks or async primitives) to keep automation reliable.

## Testing Guidelines
- Place tests in `test/`, mirroring module names (e.g., `test_chat_actions.py` for `chat_actions.py`) and using pytest fixtures for browser contexts.
- Execute the suite with `pytest test/ -v`; extend coverage for new API routes, automation routines, and Streamlit logic smoke paths.
- Provide deterministic mocks for external services (OpenAI, Zilliz, Sentry) to keep tests self-contained.

## Commit & Pull Request Guidelines
- Use conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`); keep messages imperative and scoped to a single change set.
- Branch from `main` with `feature/<topic>` or `fix/<issue-id>`, and update related docs (`docs/`, `README.md`, `ARCHITECTURE.md`) when behavior changes.
- Pull requests must summarize intent, call out config impacts, link issues or Sentry events, and include screenshots/GIFs for UI updates.
- Confirm linting, tests, and migration notes are complete before requesting review.

## Security & Configuration Tips
- Never commit `config/secrets.yaml`, generated `data/state.json`, or `/tmp/chrome_debug`; use the example templates in `config/` for onboarding.
- Keep API keys in environment variables referenced by `config/config.yaml`; redact sensitive values in logs or PRs.
- When resetting CDP sessions, remove `/tmp/chrome_debug` before relaunching Chrome to prevent credential leakage.
