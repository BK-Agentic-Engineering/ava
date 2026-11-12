"""Existing trace/session events shared by the smolagents deployment."""

import time
from .store import RecoveryRequired


def observe(state, trace, event, **data):
    try:
        trace.write(event, **data)
    except OSError as exc:
        state["trace_error"] = f"{event}: {type(exc).__name__}: {exc}"
        raise OSError("Trace write failed at " + state["trace_error"]) from exc


def emit(state, trace, event, **data):
    data["active_seconds"] = state["elapsed_base"] + time.monotonic() - state["started"]
    state["events"].append({"event": event, **data})
    if state.get("store"):
        try:
            state["store"].append(event, **data)
        except OSError as exc:
            raise RecoveryRequired(f"Journal write failed at {event}: {exc}") from exc
    observe(state, trace, event, **data)


def context():
    return {"pairs": [], "messages": [], "query_messages": [], "pending": None,
            "resume_pairs": [], "elapsed_base": 0, "started": time.monotonic(),
            "store": None, "run_id": "session", "events": [], "trace_error": None}


