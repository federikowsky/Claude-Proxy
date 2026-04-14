from __future__ import annotations

from typing import Any

try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None

import json


def json_dumps(value: Any) -> bytes:
    if orjson is not None:
        return orjson.dumps(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def json_loads(value: str | bytes) -> Any:
    if orjson is not None:
        return orjson.loads(value)
    return json.loads(value)

