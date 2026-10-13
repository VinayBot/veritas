"""One process-wide lock around local torch inference (embedder, reranker, Docling, the
prompt-injection classifier).

On Apple Silicon these models run on the Metal (MPS) backend, which aborts the whole process
if two threads submit work at once ("failed assertion _status <
MTLCommandBufferStatusCommitted"). The codebase offloads inference to worker threads
(`asyncio.to_thread`) so the event loop stays responsive, which is exactly what makes two
calls overlap: startup warm-up, an upload during a chat turn, a strategy comparison.

So "parallel" in this project means concurrent LLM calls to Ollama (a separate process);
local model inference is always one call at a time. A plain threading.Lock is enough: no
call site here re-enters another locked call while holding it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_lock = threading.Lock()


def run_exclusive(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    with _lock:
        return fn(*args, **kwargs)
