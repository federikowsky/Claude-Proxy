from __future__ import annotations

import uvicorn

from llm_proxy.infrastructure.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "llm_proxy.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level=settings.server.log_level,
    )


if __name__ == "__main__":
    main()
