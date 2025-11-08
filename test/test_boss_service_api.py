"""Automated tests for FastAPI endpoints exposed by boss_service."""

from __future__ import annotations

import types
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import boss_service
from src import assistant_actions, chat_actions, recommendation_actions
from src.candidate_store import candidate_store


def make_dummy_page() -> Any:
    """Return a minimal Playwright page stub used across tests."""

    class DummyLocator:
        async def wait_for(self, state: str | None = None, timeout: int | None = None) -> None:  # noqa: D401
            return None

        async def count(self) -> int:
            return 0

        async def click(self, timeout: int | None = None) -> None:
            return None

        def first(self) -> "DummyLocator":
            return self
        
        async def get_attribute(self, name: str) -> str:
            return ""
        
        async def inner_text(self) -> str:
            return ""

    class DummyPage:
        url = "https://www.zhipin.com/web/chat/index"

        def __init__(self) -> None:
            self.context = types.SimpleNamespace()

        def locator(self, selector: str) -> DummyLocator:  # noqa: D401
            return DummyLocator()

        async def wait_for_load_state(self, state: str, timeout: int = 30000) -> None:
            return None

        async def content(self) -> str:
            return "<html><body>ok</body></html>"

        async def title(self) -> str:
            return "Dummy Page"

        async def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
            self.url = url
            return None
        
        async def evaluate(self, script: str) -> Any:
            return None

    return DummyPage()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a TestClient with Playwright interactions stubbed out."""

    boss_service.service.startup_complete.set()

    async def fake_ensure_browser_session(*_: Any, **__: Any) -> Any:
        return make_dummy_page()

    async def fake_soft_restart() -> None:
        return None

    async def fake_startup_async() -> None:  # avoid real playwright startup
        boss_service.service.startup_complete.set()

    async def fake_shutdown_async() -> None:
        return None

    # Mock page preparation functions
    async def fake_prepare_chat_page(page: Any, *args: Any, **kwargs: Any) -> Any:
        return page

    class DummyFrame:
        def locator(self, selector: str) -> Any:
            return make_dummy_page().locator(selector)
        
        async def wait_for_load_state(self, state: str, timeout: int = 30000) -> None:
            return None

    async def fake_prepare_recommendation_page(page: Any, *args: Any, **kwargs: Any) -> DummyFrame:
        return DummyFrame()

    # Mock helper functions that don't need real browser
    async def fake_close_overlay_dialogs(page: Any) -> None:
        return None

    async def fake_ensure_on_chat_page(page: Any, settings: Any, logger: Any) -> None:
        return None

    monkeypatch.setattr(boss_service.service, "_ensure_browser_session", fake_ensure_browser_session)
    monkeypatch.setattr(boss_service.service, "soft_restart", fake_soft_restart)
    monkeypatch.setattr(boss_service.service, "_startup_async", fake_startup_async)
    monkeypatch.setattr(boss_service.service, "_shutdown_async", fake_shutdown_async)
    
    # Patch helper functions
    monkeypatch.setattr(chat_actions, "_prepare_chat_page", fake_prepare_chat_page)
    monkeypatch.setattr(recommendation_actions, "_prepare_recommendation_page", fake_prepare_recommendation_page)
    monkeypatch.setattr("src.chat_actions.close_overlay_dialogs", fake_close_overlay_dialogs)
    monkeypatch.setattr("src.chat_actions.ensure_on_chat_page", fake_ensure_on_chat_page)
    monkeypatch.setattr("src.recommendation_actions.close_overlay_dialogs", fake_close_overlay_dialogs)

    with TestClient(boss_service.app) as test_client:
        yield test_client


def make_async_return(value: Any):
    async def _inner(*_: Any, **__: Any) -> Any:
        return value

    return _inner


def test_status_endpoint_returns_stats(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chat_actions,
        "get_chat_stats_action",
        make_async_return({"new_message_count": 3, "new_greet_count": 1}),
    )
    boss_service.service.is_logged_in = True

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["logged_in"] is True
    assert payload["new_message_count"] == 3
    assert payload["new_greet_count"] == 1


def test_login_endpoint_returns_flag(client: TestClient) -> None:
    boss_service.service.is_logged_in = False
    response = client.post("/login")
    assert response.status_code == 200
    assert response.json() is False


def test_chat_dialogs_endpoint_returns_data(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [{"chat_id": "chat-1", "name": "候选人A"}]
    monkeypatch.setattr(chat_actions, "get_chat_list_action", make_async_return(expected))

    response = client.get("/chat/dialogs?limit=5&tab=新招呼&status=未读&job_title=全部")

    assert response.status_code == 200
    assert response.json() == expected


def test_chat_dialogs_value_error_maps_to_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def raise_value_error(*_: Any, **__: Any) -> None:
        raise ValueError("invalid tab")

    monkeypatch.setattr(chat_actions, "get_chat_list_action", raise_value_error)

    response = client.get("/chat/dialogs")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid tab"}


def test_chat_messages_endpoint_returns_history(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    history = [{"type": "candidate", "message": "你好"}]
    monkeypatch.setattr(chat_actions, "get_chat_history_action", make_async_return(history))

    response = client.get("/chat/abc/messages")

    assert response.status_code == 200
    assert response.json() == history


def test_chat_send_endpoint_returns_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_send(_: Any, chat_id: str, message: str) -> bool:
        captured["chat_id"] = chat_id
        captured["message"] = message
        return True

    monkeypatch.setattr(chat_actions, "send_message_action", fake_send)

    response = client.post("/chat/abc/send", json={"message": "Hello world"})

    assert response.status_code == 200
    assert response.json() is True
    assert captured == {"chat_id": "abc", "message": "Hello world"}


def test_chat_greet_endpoint_trims_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_send(_: Any, chat_id: str, message: str) -> bool:
        captured["chat_id"] = chat_id
        captured["message"] = message
        return True

    monkeypatch.setattr(chat_actions, "send_message_action", fake_send)

    response = client.post("/chat/greet", json={"chat_id": "abc", "message": " hi "})

    assert response.status_code == 200
    assert response.json() is True
    assert captured == {"chat_id": "abc", "message": "hi"}


def test_chat_stats_endpoint_returns_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stats = {"new_message_count": 5, "new_greet_count": 2}
    monkeypatch.setattr(chat_actions, "get_chat_stats_action", make_async_return(stats))

    response = client.get("/chat/stats")

    assert response.status_code == 200
    assert response.json() == stats


def test_resume_request_endpoint_handles_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def raise_timeout(*_: Any, **__: Any) -> None:
        raise PlaywrightTimeoutError("timeout")

    monkeypatch.setattr(chat_actions, "request_full_resume_action", raise_timeout)

    response = client.post("/resume/request", json={"chat_id": "abc"})

    assert response.status_code == 408
    assert response.json() == {"error": "操作超时: timeout"}


def test_resume_request_endpoint_returns_bool(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_actions, "request_full_resume_action", make_async_return(True))

    response = client.post("/resume/request", json={"chat_id": "abc"})

    assert response.status_code == 200
    assert response.json() is True


def test_resume_view_full_endpoint_returns_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"text": "full resume"}
    monkeypatch.setattr(chat_actions, "view_full_resume_action", make_async_return(payload))

    response = client.post("/resume/view_full", json={"chat_id": "abc"})

    assert response.status_code == 200
    assert response.json() == payload


def test_resume_check_full_resume_available_false(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_actions, "check_full_resume_available", make_async_return(None))

    response = client.post("/resume/check_full_resume_available", json={"chat_id": "abc"})

    assert response.status_code == 200
    assert response.json() is False


def test_resume_online_endpoint_returns_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"text": "online resume"}
    monkeypatch.setattr(chat_actions, "view_online_resume_action", make_async_return(payload))

    response = client.post("/resume/online", json={"chat_id": "abc"})

    assert response.status_code == 200
    assert response.json() == payload


def test_resume_accept_endpoint_returns_bool(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_actions, "accept_full_resume_action", make_async_return(True))

    response = client.post("/resume/accept", json={"chat_id": "abc"})

    assert response.status_code == 200
    assert response.json() is True


def test_candidate_discard_endpoint_returns_bool(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_actions, "discard_candidate_action", make_async_return(True))

    response = client.post("/candidate/discard", json={"chat_id": "abc"})

    assert response.status_code == 200
    assert response.json() is True


def test_recommend_candidates_endpoint_returns_list(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cards = [{"text": "Candidate summary"}]
    monkeypatch.setattr(recommendation_actions, "list_recommended_candidates_action", make_async_return(cards))

    response = client.get("/recommend/candidates?limit=2")

    assert response.status_code == 200
    assert response.json() == cards


def test_recommend_candidate_resume_endpoint_returns_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"text": "Recommended resume"}
    monkeypatch.setattr(recommendation_actions, "view_recommend_candidate_resume_action", make_async_return(payload))

    response = client.get("/recommend/candidate/1/resume")

    assert response.status_code == 200
    assert response.json() == payload


def test_recommend_candidate_greet_endpoint_returns_bool(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recommendation_actions, "greet_recommend_candidate_action", make_async_return(True))

    response = client.post("/recommend/candidate/1/greet", json={"message": "Hi"})

    assert response.status_code == 200
    assert response.json() is True


def test_recommend_select_job_endpoint_returns_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"selected_job": "AI Engineer", "available_jobs": ["AI Engineer", "ML Engineer"]}
    monkeypatch.setattr(recommendation_actions, "select_recommend_job_action", make_async_return(payload))

    response = client.post("/recommend/select-job", json={"job_title": "AI"})

    assert response.status_code == 200
    assert response.json() == payload


def test_assistant_generate_message_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assistant_actions,
        "generate_message",
        lambda **_: {"message": "Hello"},
    )

    response = client.post(
        "/assistant/generate-message",
        json={"chat_id": "abc", "assistant_id": "asst_1", "purpose": "chat", "chat_history": []},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Hello"}


def test_candidate_lookup_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        candidate_store,
        "get_candidates",
        lambda identifiers=None, names=None, job_applied=None, limit=None, fields=None: [{"chat_id": identifiers[0] if identifiers else None, "name": "Alice"}] if identifiers else [],
    )

    response = client.get("/candidate/chat-42")

    assert response.status_code == 200
    assert response.json() == {"chat_id": "chat-42", "name": "Alice"}


def test_thread_init_chat_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assistant_actions,
        "init_chat",
        lambda **_: {"thread_id": "thread-1", "success": True},
    )

    payload = {
        "name": "Alice",
        "job_info": {"position": "AI"},
        "resume_text": "Resume",
        "chat_history": [],
    }
    response = client.post("/thread/init-chat", json=payload)

    assert response.status_code == 200
    assert response.json() == {"thread_id": "thread-1", "success": True}


def test_thread_messages_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from src import assistant_utils
    monkeypatch.setattr(
        assistant_utils,
        "get_conversation_messages",
        lambda conversation_id: {
            "messages": [{"id": "msg-1", "role": "user", "content": "test"}],
            "has_more": False,
            "analysis": None,
            "action": None
        },
    )

    response = client.get("/assistant/thread-1/messages")

    assert response.status_code == 200
    data = response.json()
    assert "messages" in data
    assert data["messages"] == [{"id": "msg-1", "role": "user", "content": "test"}]
    assert data["has_more"] is False


def test_assistant_list_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyAssistant:
        def model_dump(self) -> Dict[str, Any]:
            return {"id": "asst_1", "name": "Test Assistant"}

    class DummyAssistantList:
        data = [DummyAssistant()]

    def fake_get_assistants() -> DummyAssistantList:
        return DummyAssistantList()

    fake_get_assistants.cache_clear = lambda: None  # type: ignore[attr-defined]

    monkeypatch.setattr(assistant_actions, "get_assistants", fake_get_assistants)

    response = client.get("/assistant/list")

    assert response.status_code == 200
    assert response.json() == [{"id": "asst_1", "name": "Test Assistant"}]


def test_assistant_create_update_delete_endpoints(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created_payloads: List[Dict[str, Any]] = []
    updated_payloads: List[Dict[str, Any]] = []
    deleted_ids: List[str] = []

    class DummyAssistantObject:
        def __init__(self, data: Dict[str, Any]) -> None:
            self.data = data

        def model_dump(self) -> Dict[str, Any]:
            return self.data

    class DummyAssistantsAPI:
        def create(self, **payload: Any) -> DummyAssistantObject:
            created_payloads.append(payload)
            return DummyAssistantObject({"id": "asst_new", **payload})

        def update(self, assistant_id: str, **payload: Any) -> DummyAssistantObject:
            updated_payloads.append({"assistant_id": assistant_id, **payload})
            return DummyAssistantObject({"id": assistant_id, **payload})

        def delete(self, assistant_id: str) -> None:
            deleted_ids.append(assistant_id)

    class DummyThreadsAPI:
        def create(self, metadata: Dict[str, Any] | None = None) -> Any:
            return types.SimpleNamespace(id="thread-1", metadata=metadata)

    dummy_client = types.SimpleNamespace()
    dummy_client.beta = types.SimpleNamespace(
        assistants=DummyAssistantsAPI(),
        threads=DummyThreadsAPI(),
    )

    def fake_get_assistants() -> Any:
        return types.SimpleNamespace(data=[DummyAssistantObject({"id": "asst_1", "name": "Existing"})])

    fake_get_assistants.cache_clear = lambda: None  # type: ignore[attr-defined]

    monkeypatch.setattr(assistant_actions, "get_openai_client", lambda: dummy_client)
    monkeypatch.setattr(assistant_actions, "get_assistants", fake_get_assistants)

    create_resp = client.post("/assistant/create", json={"name": "New Assistant"})
    assert create_resp.status_code == 200
    assert create_resp.json()["id"] == "asst_new"

    update_resp = client.post("/assistant/update/asst_1", json={"description": "Updated"})
    assert update_resp.status_code == 200
    assert update_resp.json()["id"] == "asst_1"

    delete_resp = client.delete("/assistant/delete/asst_1")
    assert delete_resp.status_code == 200
    assert delete_resp.json() is True

    assert created_payloads and created_payloads[0]["name"] == "New Assistant"
    assert updated_payloads and updated_payloads[0]["assistant_id"] == "asst_1"
    assert deleted_ids == ["asst_1"]


def test_restart_endpoint(client: TestClient) -> None:
    response = client.post("/restart")
    assert response.status_code == 200
    assert response.json() is True


def test_debug_page_endpoint(client: TestClient) -> None:
    response = client.get("/debug/page")
    assert response.status_code == 200
    payload = response.json()
    assert "url" in payload
    assert "content" in payload


def test_debug_cache_endpoint_with_event_manager(client: TestClient) -> None:
    class DummyEventManager:
        def get_cache_stats(self) -> Dict[str, Any]:
            return {"hits": 1, "misses": 0}

    previous_manager = boss_service.service.event_manager
    boss_service.service.event_manager = DummyEventManager()

    response = client.get("/debug/cache")

    assert response.status_code == 200
    assert response.json() == {"hits": 1, "misses": 0}

    boss_service.service.event_manager = previous_manager


def test_sentry_debug_endpoint_uses_exception_handler(client: TestClient) -> None:
    response = client.get("/sentry-debug")
    assert response.status_code == 500
    # Exception handler formats it as a generic error
    assert "error" in response.json()


def test_web_index_route_renders(client: TestClient) -> None:
    response = client.get("/web")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_web_stats_route_uses_service_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mock chat stats
    monkeypatch.setattr(
        chat_actions,
        "get_chat_stats_action",
        make_async_return({"new_message_count": 7, "new_greet_count": 4}),
    )
    
    # Mock candidate store
    original_collection = getattr(candidate_store, "collection", None)
    candidate_store.collection = types.SimpleNamespace(num_entities=42)

    response = client.get("/web/stats")

    assert response.status_code == 200
    assert "42" in response.text
    assert "7" in response.text
    assert "4" in response.text

    candidate_store.collection = original_collection


def test_web_recent_activity_route(client: TestClient) -> None:
    response = client.get("/web/recent-activity")
    assert response.status_code == 200
    assert "系统已启动" in response.text
