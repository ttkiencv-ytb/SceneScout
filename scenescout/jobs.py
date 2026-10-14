"""Tiny background job runner with pollable progress."""
import threading
import traceback
import uuid

_jobs = {}
_lock = threading.Lock()


def start(fn, *args, **kwargs):
    jid = uuid.uuid4().hex[:12]
    state = {"id": jid, "status": "running", "done": 0, "total": 0, "stage": "", "message": "", "result": None}
    with _lock:
        _jobs[jid] = state

    def progress(stage, done, total, message=""):
        state.update(stage=stage, done=done, total=total, message=message)

    def run():
        try:
            state["result"] = fn(*args, progress=progress, **kwargs)
            state["status"] = "done"
        except Exception as e:  # surface the error to the UI instead of dying silently
            state.update(status="error", message=str(e), trace=traceback.format_exc()[-1500:])

    threading.Thread(target=run, daemon=True).start()
    return jid


def get(jid):
    with _lock:
        return dict(_jobs.get(jid) or {"status": "missing"})
