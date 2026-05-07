import asyncio
import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nanoclaw.api.app import create_app


class MockAgentApp:
    async def ainvoke(self, inputs, config=None):
        return {
            "messages": [
                *inputs["messages"],
                AIMessage(content="mock reply"),
            ]
        }

    async def astream(self, inputs, config=None, stream_mode=None):
        yield {"agent": {"messages": [AIMessage(content="stream reply")]}}


@pytest.fixture
def app():
    app = create_app()
    app.router.lifespan_context = None
    app.state.agent_app = MockAgentApp()
    app.state.provider = "mock-provider"
    app.state.model = "mock-model"
    return app


async def _request(app, method, url, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def test_health_returns_200(app):
    response = asyncio.run(_request(app, "GET", "/health"))
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider": "mock-provider",
        "model": "mock-model",
    }


def test_index_returns_runtime_ui(app):
    response = asyncio.run(_request(app, "GET", "/"))
    assert response.status_code == 200
    assert "NanoClaw Runtime" in response.text
    assert "/sessions/" in response.text


def test_create_session_generates_thread_id(app):
    response = asyncio.run(_request(app, "POST", "/sessions", json={}))
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"]


def test_create_message_returns_final_ai_text(app):
    response = asyncio.run(_request(app, "POST", "/sessions/test-thread/messages", json={"content": "hello"}))
    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "test-thread",
        "content": "mock reply",
        "messages_count": 2,
    }


def test_stream_message_returns_sse_done_event(app):
    response = asyncio.run(_request(app, "POST", "/sessions/test-thread/messages/stream", json={"content": "hello"}))
    assert response.status_code == 200
    body = response.text
    assert "event: agent" in body
    assert "event: done" in body


def test_empty_content_returns_400(app):
    response = asyncio.run(_request(app, "POST", "/sessions/test-thread/messages", json={"content": "   "}))
    assert response.status_code == 400
    assert response.json()["error_code"] == "bad_request"
