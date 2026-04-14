"""Cross-protocol integration tests.

End-to-end: OpenAI ingress → proxy → Anthropic egress, and vice versa.
Also covers cross-provider model routing through different ingress protocols.
"""

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


def _anthropic_json_response(*, model: str = "openai/gpt-4.1-mini") -> bytes:
    """Upstream provider returns Anthropic canonical JSON."""
    return json.dumps({
        "id": "msg_cross",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "Cross-protocol response"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 8, "output_tokens": 4},
    }).encode("utf-8")


def _anthropic_stream_response(*, model: str = "anthropic/claude-sonnet-4") -> bytes:
    """Upstream provider returns Anthropic canonical SSE stream."""
    return (
        b'data: {"type":"message_start","message":{"id":"msg_cs","role":"assistant","model":"'
        + model.encode("utf-8")
        + b'","usage":{"input_tokens":8,"output_tokens":0}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Cross stream"}}\n\n'
        b'event: content_block_stop\n'
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b'event: message_delta\n'
        b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )


def _tool_json_response(*, model: str = "openai/gpt-4.1-mini") -> bytes:
    """Upstream provider returns Anthropic canonical JSON with tool_use."""
    return json.dumps({
        "id": "msg_tool_cross",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [
            {"type": "text", "text": "Let me look that up."},
            {"type": "tool_use", "id": "toolu_abc", "name": "search", "input": {"query": "test"}},
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }).encode("utf-8")


# ---------------------------------------------------------------------------
# OpenAI ingress → proxy → OpenAI egress (non-streaming)
# ---------------------------------------------------------------------------


class TestOpenAIIngressToOpenAIEgress:
    """OpenAI Chat Completions request → proxy → OpenAI Chat Completions response."""

    @pytest.mark.asyncio
    async def test_text_completion(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)
        mock_resp = httpx.Response(200, content=_anthropic_json_response(), headers={"content-type": "application/json"})
        transport = httpx.MockTransport(lambda req: mock_resp)
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
        assert data["choices"][0]["message"]["content"] == "Cross-protocol response"
        assert data["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_tool_call_completion(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)
        mock_resp = httpx.Response(200, content=_tool_json_response(), headers={"content-type": "application/json"})
        transport = httpx.MockTransport(lambda req: mock_resp)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Search something"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "search",
                            "description": "Search for info",
                            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                        },
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["finish_reason"] == "tool_calls"
        tc = data["choices"][0]["message"]["tool_calls"]
        assert len(tc) == 1
        assert tc[0]["function"]["name"] == "search"
        assert json.loads(tc[0]["function"]["arguments"]) == {"query": "test"}


# ---------------------------------------------------------------------------
# OpenAI ingress → proxy → streaming OpenAI egress
# ---------------------------------------------------------------------------


class TestOpenAIIngressStreamingEgress:
    @pytest.mark.asyncio
    async def test_streaming_text(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)
        stream_data = _anthropic_stream_response(model="openai/gpt-4.1-mini")
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                stream=MockAsyncByteStream([stream_data]),
                headers={"content-type": "text/event-stream"},
            )
        )
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Stream test"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200

        frames = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                payload = line[len("data: "):]
                if payload == "[DONE]":
                    frames.append("[DONE]")
                else:
                    frames.append(json.loads(payload))

        # Should end with [DONE]
        assert frames[-1] == "[DONE]"

        # Verify text content is present
        text_content = "".join(
            f["choices"][0]["delta"]["content"]
            for f in frames
            if isinstance(f, dict)
            and f.get("choices", [{}])[0].get("delta", {}).get("content")
        )
        assert "Cross stream" in text_content


# ---------------------------------------------------------------------------
# Anthropic ingress → proxy → Anthropic egress (existing path, regression)
# ---------------------------------------------------------------------------


class TestAnthropicIngressToAnthropicEgress:
    """Anthropic Messages request → proxy → Anthropic Messages response (regression)."""

    @pytest.mark.asyncio
    async def test_text_completion(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)
        mock_resp = httpx.Response(
            200,
            content=_anthropic_json_response(model="anthropic/claude-sonnet-4"),
            headers={"content-type": "application/json"},
        )
        transport = httpx.MockTransport(lambda req: mock_resp)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "message"
        assert data["content"][0]["text"] == "Cross-protocol response"
        assert data["stop_reason"] == "end_turn"

    @pytest.mark.asyncio
    async def test_streaming(self, tmp_path, monkeypatch):
        settings = _make_settings(tmp_path, monkeypatch)
        stream_data = _anthropic_stream_response(model="anthropic/claude-sonnet-4")
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                stream=MockAsyncByteStream([stream_data]),
                headers={"content-type": "text/event-stream"},
            )
        )
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "Stream test"}],
                "max_tokens": 100,
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Parse Anthropic SSE frames
        frames = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                frames.append(json.loads(line[len("data: "):]))

        # Should have message_start, blocks, message_stop
        types = [f.get("type") for f in frames]
        assert "message_start" in types
        assert "message_stop" in types


# ---------------------------------------------------------------------------
# Cross-provider model routing
# ---------------------------------------------------------------------------


class TestCrossProviderRouting:
    """Verify different models route to different providers through same ingress."""

    @pytest.mark.asyncio
    async def test_openai_ingress_routes_anthropic_model(self, tmp_path, monkeypatch):
        """OpenAI Chat Completions ingress with Anthropic model routes correctly."""
        settings = _make_settings(tmp_path, monkeypatch)
        mock_resp = httpx.Response(
            200,
            content=_anthropic_json_response(model="anthropic/claude-sonnet-4"),
            headers={"content-type": "application/json"},
        )
        transport = httpx.MockTransport(lambda req: mock_resp)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Egress is OpenAI format regardless of provider
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_anthropic_ingress_routes_openai_model(self, tmp_path, monkeypatch):
        """Anthropic Messages ingress with OpenAI model routes correctly."""
        settings = _make_settings(tmp_path, monkeypatch)
        mock_resp = httpx.Response(
            200,
            content=_anthropic_json_response(model="openai/gpt-4.1-mini"),
            headers={"content-type": "application/json"},
        )
        transport = httpx.MockTransport(lambda req: mock_resp)
        app = create_app(settings, transport=transport)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

        resp = await client.post(
            "http://test/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Egress is Anthropic format
        assert data["type"] == "message"
        assert data["stop_reason"] == "end_turn"
