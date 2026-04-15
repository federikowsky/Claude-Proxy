from __future__ import annotations

import json
import logging

from llm_proxy.infrastructure.logging import bind_log_context, clear_log_context, setup_logging


def test_setup_logging_renders_extra_fields_and_contextvars(capsys) -> None:
    setup_logging("INFO")
    bind_log_context(request_id="req-123", session_id="sess-456")
    try:
        logging.getLogger("llm_proxy.test").info(
            "request_completed",
            extra={"extra_fields": {"path": "/v1/models", "status": 200}},
        )
    finally:
        clear_log_context()

    captured = capsys.readouterr().err.strip()
    payload = json.loads(captured)
    assert payload["event"] == "request_completed"
    assert payload["path"] == "/v1/models"
    assert payload["status"] == 200
    assert payload["request_id"] == "req-123"
    assert payload["session_id"] == "sess-456"


def test_setup_logging_quiets_httpx_info(capsys) -> None:
    setup_logging("INFO")
    logging.getLogger("httpx").info("noise")
    assert capsys.readouterr().err == ""