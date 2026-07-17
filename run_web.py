"""Run the Szponti web API (Windows-safe event loop)."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """Start uvicorn with a Proactor loop on Windows."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsProactorEventLoopPolicy())
    import uvicorn

    # bez --reload: SelectorEventLoop psuje Cursor bridge (subprocess)
    uvicorn.run(
        "web.backend.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False)


if __name__ == "__main__":
    main()
