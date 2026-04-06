"""Celery application for background pipeline tasks.

What this is for
    The FastAPI app enqueues long work here so HTTP handlers return quickly.
    Tasks live in ``app.pipeline.tasks`` (e.g. gap analysis after submit,
    derived-audit placeholder writes).

Redis (CELERY_BROKER_URL)
    Same URL is used as *broker* (task queue) and *result backend* (task
    state for ``AsyncResult`` / status checks from ``app.pipeline.router``).
    Not a general app cache—only Celery infrastructure.

Run a worker
    ``celery -A app.pipeline.celery_app worker --loglevel=info``

See also
    ``app/pipeline/README.md`` for compose, ops, and failure modes.
"""

import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Broker + result backend: both point at Redis (see module docstring).
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

celery_app = Celery(
    # App name: namespace for tasks in Redis keys and ``celery inspect`` output.
    "pipeline",
    # Broker: where producers (FastAPI) publish messages; workers consume from here.
    broker=REDIS_URL,
    # Backend: stores task return values and state (PENDING/STARTED/SUCCESS/…)
    # so ``AsyncResult(task_id).status`` in the API can read gap-analysis progress.
    backend=REDIS_URL,
    # Eagerly import this module so task names register when the worker starts.
    include=["app.pipeline.tasks"],
)

celery_app.conf.update(
    # JSON only: avoids pickle (remote code execution risk if broker is compromised).
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Workers and result timestamps use UTC; keeps logs and ``result.date_done`` consistent.
    timezone="UTC",
    enable_utc=True,
    # Records STARTED in the result backend so UIs can tell "queued" from "worker running"
    # (gap analysis runs long enough for that to matter).
    task_track_started=True,
    # Ack *after* the task finishes: if the worker crashes mid-task, the message is
    # redelivered (at-least-once). Trade-off: possible duplicate runs—gap task should
    # stay idempotent where it matters (per-question S3 writes, progress counters).
    task_acks_late=True,
    # Prefetch 1 task per worker process: fair distribution when tasks vary in length
    # (LLM calls). Higher prefetch can starve other workers if one task runs for minutes.
    worker_prefetch_multiplier=1,
    # Drop result metadata from Redis after 24h; S3 remains source of truth for outputs.
    result_expires=3600 * 24,
)
