"""Engine warm-up endpoints.

The studio calls POST /engines/{engine}/warm the moment a user shows intent
(opens the studio, switches image/video). The backend boots the engine's
Modal container in a background thread so the GPU is ready before the user
finishes typing a prompt. Calling it repeatedly is safe and free when the
engine is already warm.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException

from app.services.engines import EngineError, get_engine, warm_states

router = APIRouter(prefix="/api/engines", tags=["engines"])

_WARM_LOCK = threading.Lock()
_WARM_STARTED: set[str] = set()


def _warm_engine(engine: str) -> None:
    try:
        eng = get_engine(engine)
    except (KeyError, ValueError) as exc:
        warm_states[engine] = {"state": "error", "detail": str(exc),
                               "ts": time.time()}
        return
    warm_states[engine] = {"state": "warming", "detail": None,
                           "ts": time.time()}
    try:
        eng.wait_ready()
        warm_states[engine] = {"state": "warm", "detail": None,
                               "ts": time.time()}
    except EngineError as exc:
        warm_states[engine] = {"state": "error", "detail": str(exc),
                               "ts": time.time()}


@router.post("/{engine}/warm")
def warm(engine: str) -> dict:
    if engine not in ("image", "video"):
        raise HTTPException(status_code=404, detail="unknown engine")
    with _WARM_LOCK:
        # only one warm thread per engine at a time; repeat calls while a
        # warm-up is running are ignored (and are no-ops when warm)
        first = engine not in _WARM_STARTED or warm_states.get(engine, {}).get(
            "state") in ("error",)
        if first:
            _WARM_STARTED.add(engine)
            threading.Thread(target=_warm_engine, args=(engine,),
                             daemon=True, name=f"warm-{engine}").start()
    state = warm_states.get(engine, {"state": "queued", "detail": None,
                                     "ts": time.time()})
    return {"engine": engine, **state}


@router.get("/{engine}/warm")
def warm_status(engine: str) -> dict:
    state = warm_states.get(engine)
    if state is None:
        return {"engine": engine, "state": "idle", "detail": None, "ts": None}
    return {"engine": engine, **state}
