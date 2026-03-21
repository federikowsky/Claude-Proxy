from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class CompatibilityMode(StrEnum):
    TRANSPARENT = "transparent"
    COMPAT = "compat"
    DEBUG = "debug"
