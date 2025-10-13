"""End-to-end style flow test covering candidate management APIs."""

from __future__ import annotations

import types
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import boss_service
from src import assistant_actions, chat_actions


def _make_dummy_page() -> Any:
    class DummyLocator:
        async def wait_for(self, state: str | None = None, timeout: int | None = None) -> None:
            return None

        async def count(self) -> int:
            return 0

        async def get_attribute(self, name: str) -> str:
            return ""
        
        async def click(self, timeout: int | None = None) -> None:
            return None
        
        async def inner_text(self) -> str:
            return ""

        @property
        def first(self) -> "DummyLocator":
            return self

    class DummyPage:
        url = "https://www.zhipin.com/web/chat/index"

        def __init__(self) -> None:
            self.context = types.SimpleNamespace()

        def locator(self, selector: str) -> DummyLocator:
            return DummyLocator()

        async def wait_for_load_state(self, state: str, timeout: int = 30000) -> None:
            return None

        async def content(self) -> str:
            return "<html><body>dummy</body></html>"

        async def title(self) -> str:
            return "Dummy Page"
        
        async def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
            self.url = url
            return None

    return DummyPage()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    boss_service.service.startup_complete.set()

    async def fake_ensure_browser_session(*_: Any, **__: Any) -> Any:
        return _make_dummy_page()

    async def fake_soft_restart() -> None:
        return None

    async def fake_startup_async() -> None:
        boss_service.service.startup_complete.set()

    async def fake_shutdown_async() -> None:
        return None

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
    monkeypatch.setattr("src.chat_actions.close_overlay_dialogs", fake_close_overlay_dialogs)
    monkeypatch.setattr("src.chat_actions.ensure_on_chat_page", fake_ensure_on_chat_page)

    with TestClient(boss_service.app) as test_client:
        yield test_client


def make_async_stub(result: Any, record: List[str], name: str):
    async def _inner(*_: Any, **__: Any) -> Any:
        record.append(name)
        return result

    return _inner


def test_candidate_flow_end_to_end(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    call_sequence: List[str] = []

    dialogs = [{"id": "chat-1", "name": "候选人A", "text": "你好"}]
    history = [
        {"type": "candidate", "message": "您好", "timestamp": "2024-01-01 10:00:00"},
        {"type": "recruiter", "message": "欢迎", "timestamp": "2024-01-01 10:05:00"},
    ]
    resume_payload = {"text": "简历内容"}

    # Patch in boss_service module namespace where functions are imported
    monkeypatch.setattr(boss_service, "get_chat_list_action", make_async_stub(dialogs, call_sequence, "list_dialogs"))
    monkeypatch.setattr(boss_service, "get_chat_history_action", make_async_stub(history, call_sequence, "history"))
    monkeypatch.setattr(boss_service, "view_full_resume_action", make_async_stub(resume_payload, call_sequence, "full_resume"))
    monkeypatch.setattr(boss_service, "send_message_action", make_async_stub(True, call_sequence, "send"))
    monkeypatch.setattr(boss_service, "request_full_resume_action", make_async_stub(True, call_sequence, "request_resume"))
    monkeypatch.setattr(boss_service, "discard_candidate_action", make_async_stub(True, call_sequence, "discard"))

    def fake_generate_message(**payload: Any) -> Dict[str, Any]:
        call_sequence.append("generate_message")
        assert payload["chat_id"] == "chat-1"
        return {"message": "自动化回复"}

    monkeypatch.setattr(assistant_actions, "generate_message", fake_generate_message)

    boss_service.service.is_logged_in = True

    resp_dialogs = client.get("/chat/dialogs?limit=1")
    assert resp_dialogs.status_code == 200
    assert resp_dialogs.json() == dialogs

    resp_history = client.get("/chat/chat-1/messages")
    assert resp_history.status_code == 200
    assert resp_history.json() == history

    resp_analysis = client.post(
        "/assistant/generate-message",
        json={"chat_id": "chat-1", "assistant_id": "asst_1", "purpose": "chat", "chat_history": history},
    )
    assert resp_analysis.status_code == 200
    assert resp_analysis.json() == {"message": "自动化回复"}

    resp_send = client.post("/chat/chat-1/send", json={"message": "自动化回复"})
    assert resp_send.status_code == 200
    assert resp_send.json() is True

    resp_request_resume = client.post("/resume/request", json={"chat_id": "chat-1"})
    assert resp_request_resume.status_code == 200
    assert resp_request_resume.json() is True

    resp_view_resume = client.post("/resume/view_full", json={"chat_id": "chat-1"})
    assert resp_view_resume.status_code == 200
    assert resp_view_resume.json() == resume_payload

    resp_discard = client.post("/candidate/discard", json={"chat_id": "chat-1"})
    assert resp_discard.status_code == 200
    assert resp_discard.json() is True

    assert call_sequence == [
        "list_dialogs",
        "history",
        "generate_message",
        "send",
        "request_resume",
        "full_resume",
        "discard",
    ]
