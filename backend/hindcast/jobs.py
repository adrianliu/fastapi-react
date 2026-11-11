"""Background jobs: one worker thread runs submitted functions in order (spec 7)."""

import json
import queue
import threading
import traceback
from collections.abc import Callable

from hindcast.store.db import utc_now
from hindcast.store.schema import core_db, ensure_core_schema
from hindcast.types import JsonObject

JobFn = Callable[[Callable[[str], None]], JsonObject]

_queue: "queue.Queue[tuple[int, JobFn]]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def _set(job_id: int, sql: str, *args: object) -> None:
    with core_db() as conn:
        conn.execute(f"UPDATE jobs SET {sql} WHERE id = ?", (*args, job_id))


def _run() -> None:
    while True:
        job_id, fn = _queue.get()
        _set(job_id, "status = 'running'")

        def progress(msg: str, job_id: int = job_id) -> None:
            _set(job_id, "progress = ?", msg)

        try:
            result = fn(progress)
            _set(
                job_id,
                "status = 'done', result = ?, finished_at = ?",
                json.dumps(result),
                utc_now(),
            )
        except Exception as exc:
            _set(
                job_id,
                "status = 'failed', error = ?, finished_at = ?",
                f"{exc}\n{traceback.format_exc()[-2000:]}",
                utc_now(),
            )
        finally:
            _queue.task_done()


def submit(kind: str, fn: JobFn) -> int:
    """Queue `fn(progress)` on the single worker thread. Returns the job id."""
    global _worker
    with core_db() as conn:
        ensure_core_schema(conn)
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, progress, created_at) VALUES (?, 'queued', '', ?)",
            (kind, utc_now()),
        )
        job_id = cur.lastrowid
    assert job_id is not None
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="hindcast-jobs", daemon=True)
            _worker.start()
    _queue.put((job_id, fn))
    return job_id


def wait_idle() -> None:
    """Block until every queued job has finished (tests)."""
    _queue.join()
