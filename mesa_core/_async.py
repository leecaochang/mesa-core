"""Policy workers isolated from the event loop executor used by host bridges."""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

_WORKERS = ThreadPoolExecutor(thread_name_prefix="mesa-policy")


async def run_sync[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        _WORKERS, partial(context.run, fn, *args, **kwargs)
    )
