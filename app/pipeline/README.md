# Pipeline, Celery, and Redis

This backend offloads **long-running assessment work** to a **Celery worker** so the FastAPI process stays responsive. **Redis** is the message broker and the **result backend** for those tasks.

---

## What Redis does here

Celery needs a broker to hold task messages until a worker picks them up, and (with this configuration) a place to store **task state** for status queries.

In `app/pipeline/celery_app.py`, both are the same URL:

- **`CELERY_BROKER_URL`** (default `redis://localhost:6379/0`) is used as **`broker`** and **`backend`**.

So Redis is **not** a general application cache for HTTP requests; it is **infrastructure for the Celery queue** (and task results / metadata Celery stores in the backend).

**Docker Compose** (`docker-compose.yaml` at repo root) runs:

- **`redis`** — `redis:7-alpine`, health-checked, optional volume `redis-data`.
- **`api`** and **`celery-worker`** both set `CELERY_BROKER_URL=redis://redis:6379/0`.
- Optional **`redis-ui`** (RedisInsight) for local inspection.

---

## What the Celery worker does

The worker process loads `app.pipeline.celery_app` and executes tasks defined in `app.pipeline.tasks`:

| Task name | Purpose |
|-----------|---------|
| **`pipeline.run_gap_analysis`** | After an assessment is submitted, loads answers from S3, runs per-question gap analysis (LLM / semantic pipeline), writes results and gap report to S3, updates pipeline progress, gap index, org stage, and review queue. |
| **`pipeline.recompute_derived_audit`** | Writes the **`derived/*`** placeholder bundle in S3 (metrics, risk scores, insights stub). Intended as the async hook for heavier derived analytics later. |

The worker uses the same **config and S3 bucket** as the API (`get_config()`, `S3Client`), so it must have valid **`.env`** (or environment) for AWS/S3 and any LLM keys the gap analyzer needs.

**Start locally (examples):**

```bash
# From project root, with Redis reachable at CELERY_BROKER_URL
celery -A app.pipeline.celery_app worker --loglevel=info --concurrency=2
```

Compose equivalent: the **`celery-worker`** service runs that command.

---

## How the API uses Celery (without blocking requests)

### Gap analysis

1. The client calls the pipeline **submit** flow (see `app/pipeline/router.py`).
2. The API transitions the pipeline to **AI gap analysis**, then calls **`run_gap_analysis.delay(...)`**.
3. The **task id** is stored on the pipeline record as **`gap_analysis_task_id`** so clients can correlate work.
4. If dispatch **raises** (e.g. Redis down, Celery misconfigured), the router marks **`gap_analysis_status`** as **failed** and persists that; the HTTP response still returns, but analysis does not run in the background.

### Progress and status

**`GET /pipeline/gap-progress`** (and related pipeline data) reads S3 for pipeline fields **and**, when `gap_analysis_task_id` is set, asks Celery for **`AsyncResult(task_id).status`** (exposed as **`celery_task_status`** in the JSON). That lookup uses the **Redis result backend**.

### Derived audit artifacts

`app/etl/s3/services/derived_service.py` **`schedule_derived_recompute`** tries **`recompute_derived_audit_task.delay(...)`**. If Celery is unavailable (import error, broker down, etc.), it **falls back** to writing the placeholder bundle **synchronously** so local dev without a worker still behaves.

`audit_lifecycle_service` triggers that schedule when appropriate so **`derived/*`** stays aligned with lifecycle events without blocking the API for long.

---

## Operational checklist

1. **Redis** must be running and reachable at **`CELERY_BROKER_URL`** for gap analysis to actually queue.
2. At least one **Celery worker** must be running with the same code and env as the API, or tasks sit in Redis unprocessed.
3. The **API** does not need to import the worker at startup for correctness; only **dispatch** and **status** paths touch Celery.
4. Task results expire after **24 hours** (`result_expires` in `celery_app.py`); old task ids may no longer show detailed results in Redis, while S3 remains the source of truth for gap outputs.

---

## Dependencies

Declared in `requirements.txt`: **`celery[redis]`** and **`redis`**.

---

## End-to-end assessment flow

For the full practitioner journey (per-question saves → one-time submit → gap analysis → review), see **[docs/ai-assessment-process.md](../../docs/ai-assessment-process.md)**.
