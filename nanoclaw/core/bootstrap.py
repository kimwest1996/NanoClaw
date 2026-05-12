"""Core runtime bootstrap — unified initialization of all module-level singletons.

Usage
-----
    from nanoclaw.core.bootstrap import init_core, shutdown_core

    await init_core(provider="openai", model="gpt-4o", loop=asyncio.get_event_loop())
    # ... run app ...
    shutdown_core()

Call at each entry point before any core module is used. Idempotent.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .config import ensure_workspace
from .subagent import configure_subagent_manager

_initialized = False


async def init_core(
    provider: str,
    model: str,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Initialize all core singletons in dependency order.

    1. Workspace directories (ensure_workspace)
    2. Subagent manager (configure_subagent_manager)
    3. Future singletons go here.
    """
    global _initialized
    if _initialized:
        return

    ensure_workspace()
    configure_subagent_manager(provider, model, loop)
    _initialized = True


def shutdown_core() -> None:
    """Gracefully stop all core singletons."""
    global _initialized
    if not _initialized:
        return

    try:
        from .subagent import get_subagent_manager
        get_subagent_manager().cancel_all()
    except (AssertionError, RuntimeError):
        pass

    _initialized = False
