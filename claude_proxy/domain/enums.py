from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class StreamPolicyName(StrEnum):
    STRICT = "strict"
    PROMOTE_IF_EMPTY = "promote_if_empty"


class ReasoningMode(StrEnum):
    DROP = "drop"
    PROMOTE_IF_EMPTY = "promote_if_empty"

