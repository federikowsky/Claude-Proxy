from __future__ import annotations

import codecs
from collections.abc import AsyncIterator
from dataclasses import dataclass

from claude_proxy.domain.errors import ProviderProtocolError


@dataclass(slots=True, frozen=True)
class SseMessage:
    event: str | None
    data: str


class IncrementalSseParser:
    async def parse(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[SseMessage]:
        decoder = codecs.getincrementaldecoder("utf-8")()
        pending = ""
        event_name: str | None = None
        data_lines: list[str] = []

        async for chunk in chunks:
            pending += decoder.decode(chunk)
            while True:
                newline_index = pending.find("\n")
                if newline_index < 0:
                    break
                line = pending[:newline_index]
                pending = pending[newline_index + 1 :]
                if line.endswith("\r"):
                    line = line[:-1]
                if not line:
                    if data_lines:
                        yield SseMessage(event=event_name, data="\n".join(data_lines))
                    event_name = None
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:]
                    if event_name.startswith(" "):
                        event_name = event_name[1:]
                    continue
                if line.startswith("data:"):
                    data = line[5:]
                    if data.startswith(" "):
                        data = data[1:]
                    data_lines.append(data)

        pending += decoder.decode(b"", final=True)
        if pending or data_lines or event_name:
            raise ProviderProtocolError("truncated SSE stream")
