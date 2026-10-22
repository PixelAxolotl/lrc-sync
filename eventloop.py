"""Event-loop factory for the lrc-sync server.

Why this exists
---------------
On Windows, uvicorn's default event loop is ``ProactorEventLoop``. Its accept
path has a long-standing CPython bug (python/cpython#93821): when a client
connects and then resets the connection before the pending ``AcceptEx``
completes, Windows completes the overlapped accept with
``ERROR_NETNAME_DELETED`` (WinError 64). ``BaseProactorEventLoop`` treats that
as fatal for the *listening* socket and closes it, so the process keeps
running but never accepts another connection (the server silently dies).

``SelectorEventLoop`` handles the same per-connection reset by logging it and
continuing to accept, so we use it instead.

Selected from ``server.py`` via ``loop="eventloop:selector_loop_factory"``.
"""
from __future__ import annotations

import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Create a fresh ``SelectorEventLoop`` (never ``ProactorEventLoop``)."""
    return asyncio.SelectorEventLoop()
