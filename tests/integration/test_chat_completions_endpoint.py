"""Integration tests for the OpenAI Chat Completions endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from llm_proxy.infrastructure.config import load_settings
from llm_proxy.main import create_app
from tests.conftest import MockAsyncByteStream, base_config


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, sort_keys=False)
    return load_settings(config_path)


def _upstream_anthropic_response(*, model: str = "openai/gpt-4.1-mini") -> bytes:
    """Upstream provider returns Anthropic canonical format (as openrouter does)."""
    resp = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "Hello from upstream"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return json.dumps(resp).encode("utf-8")


def _upstream_anthropic_stream(*, model: str = "openai/gpt-4.1-mini") -> bytes:
    """Upstream provider returns Anthropic canonical SSE stream."""
    return (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"msg_s","role":"assistant","model":"'
        + model.encode("utf-8")
        + b'","usage":{"input_tokens":10,"output_tokens":0}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello from stream"}}\n\n'
        b'event: content_block_stop\n'
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b'event: message_delta\n'
        b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )


class TestChatCompletionsNonStreaming:
    @pytest.mark.asyncio
    async def test_basic_completion(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)

        mock_response = httpx.Response(
            200,
            content=_upstream_anthropic_response(),
            headers={"content-type": "application/json"},
        )
        transport = httpx.MockTransport(lambda req: mock_response)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert "Hello from upstream" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["usage"]["prompt_tokens"] == 10
        assert data["usage"]["completion_tokens"] == 5
        assert data["usage"]["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_with_system_message(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)

        mock_response = httpx.Response(
            200,
            content=_upstream_anthropic_response(),
            headers={"content-type": "application/json"},
        )
        transport = httpx.MockTransport(lambda req: mock_response)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"


class TestChatCompletionsStreaming:
    @pytest.mark.asyncio
    async def test_basic_stream(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)

        stream_data = _upstream_anthropic_stream()

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                stream=MockAsyncByteStream([stream_data]),
                headers={"content-type": "text/event-stream"},
            )

        transport = httpx.MockTransport(handle)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        body = resp.text
        lines = [line for line in body.split("\n") if line.startswith("data: ")]

        # Parse all data frames
        frames = []
        for line in lines:
            payload = line[len("data: "):]
            if payload == "[DONE]":
                frames.append("[DONE]")
            else:
                frames.append(json.loads(payload))

        # Should have role chunk, text delta, finish reason, [DONE]
        assert any(
            isinstance(f, dict) and f.get("choices", [{}])[0].get("delta", {}).get("role") == "assistant"
            for f in frames
        ), "Expected role chunk"

        assert any(
            isinstance(f, dict) and f.get("choices", [{}])[0].get("delta", {}).get("content") == "Hello from stream"
            for f in frames
        ), "Expected text delta"

        assert frames[-1] == "[DONE]", "Expected [DONE] as last frame"

        # All dict frames should have chat.completion.chunk
        for f in frames:
            if isinstance(f, dict) and "object" in f:
                assert f["object"] == "chat.completion.chunk"


class TestChatCompletionsValidation:
    @pytest.mark.asyncio
    async def test_empty_messages_rejected(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)

        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [],
            },
        )
        assert resp.status_code == 400  # Custom error handler returns 400

    @pytest.mark.asyncio
    async def test_missing_model_rejected(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)

        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 400
