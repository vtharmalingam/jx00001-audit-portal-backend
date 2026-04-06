# S3 storage architecture

This document is the **canonical specification** for bucket layout, identifiers, parsing rules, and operational constraints.  
**Implementation note:** `app/etl/s3/utils/s3_paths.py` and services may still reflect an older layout until migration is complete; this file describes the **target** contract they should converge to.

Optional prefix: `BASE_PREFIX` in `s3_paths.py` (e.g. for tests) prepends to all keys.

---

## 1. Core principles

| Principle | Meaning |
|-----------|---------|
| **Deterministic paths** | No search to find an audit. Path = function of `org_id`, `project_id`, `ai_system_id`, `audit_id` (and global roots for platform data). |
| **`current/` = source of truth** | Authoritative operational state for the live audit. Fine-grained per-object updates. |
| **`derived/` = rebuildable** | Computed layer only. Safe to drop and regenerate; never the sole source of truth for core facts. |
| **Globally unique `audit_id`** | `audit_id` is a **ULID** (time-ordered, collision-resistant). The S3 folder under `audits/` is **only** this ULID—not a composite of org/project/system. |
| **S3 is not a query engine** | Hot reads use known keys and **`_index.json`**; avoid listing large prefixes in request paths. |

---

## 2. Identifiers

| Name | Format | Example |
|------|--------|---------|
| **`org_id`** | 26-character **Crockford Base32 ULID** | `01KND1XJAXQ7P7Q3G846ZN80ZN` |
| **`project_id`** | Exactly **3 digits** | `001` |
| **`ai_system_id`** | Exactly **4 digits** | `0001` |
| **`audit_id`** | 26-character **Crockford Base32 ULID** | `01HZX3K8M9A2F7KX8YQWERTY12` |

### 2.1 `system_key` (composite, APIs / logging)

```text
system_key = {org_id}-{project_id}-{ai_system_id}
```

Example: `01KND1XJAXQ7P7Q3G846ZN80ZN-001-0001`

- Used in APIs, logs, correlation, external systems.
- **Not** an S3 path segment by itself; path repeats the three parts under `organizations/.../projects/.../systems/...`.

### 2.2 `audit_key` (composite, logical only)

```text
audit_key = {system_key}-{audit_id}
```

Example: `01KND1XJAXQ7P7Q3G846ZN80ZN-001-0001-01HZX3K8M9A2F7KX8YQWERTY12`

- **Never** used as an S3 prefix. S3 uses **`audits/{audit_id}/`** only; parent path already scopes org/project/system.

---

## 3. Normalization and validation

### 3.1 Case

All of **`system_key`**, **`audit_id`**, **`audit_key`** (and standalone **`org_id`** when validated) **MUST** be normalized to **uppercase** before length, structure, and regex checks.

Order: **`upper()` → length/structure → field validation.**

### 3.2 Crockford ULID (single segment)

Regex for one ULID:

```regex
^[0-9A-HJKMNP-TV-Z]{26}$
```

Characters **I, L, O, U** are invalid in strict ULID form.

### 3.3 Full `audit_key` (after normalize)

```regex
^[0-9A-HJKMNP-TV-Z]{26}-\d{3}-\d{4}-[0-9A-HJKMNP-TV-Z]{26}$
```

---

## 4. Parsing rules (mandatory)

**Delimiter-based parsing (`split`, `find`) is not allowed** for `system_key` or `audit_key`. Only **fixed-position** parsing.

### 4.1 `system_key` (35 characters)

```text
Positions 0–25   : org_id
Position 26      : '-'
Positions 27–29  : project_id (3 digits)
Position 30      : '-'
Positions 31–34  : ai_system_id (4 digits)
```

```python
system_key = system_key.upper()
assert len(system_key) == 35
assert system_key[26] == "-" and system_key[30] == "-"
org_id       = system_key[0:26]
project_id   = system_key[27:30]
ai_system_id = system_key[31:35]
```

**Mandatory checks:**

- `len(system_key) == 35`
- Hyphens at indices **26** and **30**
- `project_id`: `len == 3` and all digits
- `ai_system_id`: `len == 4` and all digits
- `org_id`: matches Crockford ULID regex

**Assumption:** `org_id` is always exactly **26** characters. If that ever changes, this parsing contract must be replaced (not “fixed” with naive splitting).

### 4.2 `audit_key` (62 characters)

```text
Positions 0–34   : system_key (35 chars)
Position 35      : '-'
Positions 36–61  : audit_id (26 chars)
```

```python
audit_key = audit_key.upper()
assert len(audit_key) == 62
assert audit_key[35] == "-"
system_key = audit_key[0:35]
audit_id   = audit_key[36:62]
```

Then validate **`system_key`** as above and **`audit_id`** with the ULID regex.

---

## 5. Bucket layout: global vs org-scoped

### 5.1 Bucket root (global / platform)

```text
/
├── platform/                 # e.g. aict_users.json
├── lookups/                  # domains, organizations, ai_systems, auditor_master, …
├── exports/                  # e.g. blockchain exports
└── organizations/            # tenant tree
```

| Path | Scope |
|------|--------|
| `/platform/…` | Global |
| `/lookups/…` | Global |
| `/exports/…` | Global |
| `/organizations/{org_id}/…` | Tenant-scoped |

### 5.2 Organization (tenant)

```text
organizations/{org_id}/
├── org_profile.json
└── projects/
    └── {project_id}/
        ├── project.json
        └── systems/
            ├── {ai_system_id}/
            │   ├── system.json
            │   └── audits/
            │       └── {audit_id}/
            │           ├── metadata.json
            │           ├── audit_summary.json
            │           ├── timeline.json
            │           ├── current/
            │           └── derived/
            └── …
```

**Single canonical place for systems:** under **`projects/{project_id}/systems/{ai_system_id}/`**. Do not duplicate an org-level `organizations/{org_id}/systems/` tree for the same meaning.

---

## 6. Audit folder: roles by layer

| Layer | Role |
|-------|------|
| **Audit root** (`audits/{audit_id}/`) | Control plane + **cached** operational summary |
| **`current/`** | **Source of truth** for live answers, feedback, evidence pointers, operational JSON |
| **`derived/`** | **Rebuildable** metrics, risk, insights, embeddings |
| **`timeline.json`** | **Authoritative append-style event trace** (not under `derived/`) |

---

## 7. Files at audit root

| Object | Role |
|--------|------|
| **`metadata.json`** | Audit control plane: ids, status, **`total_questions`** (authoritative denominator), timestamps, etc. |
| **`audit_summary.json`** | **Recomputable** dashboard-style counters; stored at root for **fast API/UI access**—**not** source of truth for raw answers. |
| **`timeline.json`** | **Authoritative** event log; append-oriented; **not** in `derived/`. |

---

## 8. `current/` (source of truth)

### 8.1 Per-question JSON

```text
current/answers/{question_id}.json
current/ai_analysis/{question_id}.json
current/auditor_feedback/{question_id}.json
current/evidence/{question_id}/…   # optional files under question folder
```

Each `{question_id}.json` **SHOULD** include at least **`version`** and **`last_updated`** (ISO8601). Updates: read → increment version → write; optional **ETag** / conditional writes for concurrency.

### 8.2 Indexes (mandatory for hot reads)

```text
current/answers/_index.json
current/ai_analysis/_index.json
current/auditor_feedback/_index.json
```

**Shape (canonical):**

```json
{
  "items": [
    {
      "question_id": "q1",
      "version": 3,
      "last_updated": "ISO8601",
      "state": "draft | submitted | …"
    }
  ],
  "last_updated": "ISO8601"
}
```

- **`_index.json` MUST exist** during normal operation. Readers **SHOULD NOT** rely on listing S3 prefixes in the hot path.
- The API (or writer) that updates `{question_id}.json` **MUST** update the matching **`_index.json`** (same section).
- **Recovery only:** rebuild index from listing if corrupt/missing—**not** part of normal read flows.
- Optional: background jobs MAY validate/repair indexes.

**`answered` and the index:** For metrics, **`answered`** counts only documents where **`state == submitted`**. If `_index.json` is used to compute counts, each row **MUST** carry **`state`** (or equivalent), or the index **MUST** only list submitted questions—otherwise **`progress`** and **`audit_summary`** drift.

### 8.3 Other `current/` artifacts (operational, not analytics)

```text
current/gap_report.json      # derived-from-current, operational
current/pipeline.json        # workflow state
current/review.json          # auditor / CSAP-style review state
current/evidence_index.json  # authoritative evidence map (source of truth)
current/progress.json        # bounded operational progress (see §10)
```

Optional non-authoritative copy: **`derived/evidence_index.json`** if needed for caching (must be clearly rebuildable from `current/`).

---

## 9. `derived/` (computed, async by default)

```text
derived/metrics.json
derived/risk_scores.json
derived/insights.json
derived/embeddings/{question_id}.vec
```

**Principles:**

- Fully rebuildable.
- Updated via **application-managed** flows (not S3-native triggers): e.g. API emits event → queue/worker → recompute.
- All derived writers **MUST** be **idempotent** and **overwrite-safe**.

### 9.1 Sync vs async (no double ownership)

| Artifact | Update mode |
|----------|-------------|
| **`audit_summary.json`** (root) | **Synchronous** (small recompute after mutations, as today’s product requires) |
| **`current/**/_index.json`** | **Synchronous** with the write that touches the section |
| **`current/progress.json`** | **Synchronous** (must stay bounded—see §10) |
| **`derived/*`**, **`derived/embeddings/*`** | **Asynchronous** (heavy / LLM / batch) |

**Rule:** No derived artifact is updated both sync and async; one owner per file class.

---

## 10. `progress.json` (strict bounds)

**MUST:**

- Contain **O(1) scalar fields only** (no per-question arrays or large embedded structures).
- Stay **under 4 KB** serialized.
- Be computable **without** a full scan of all question objects (use incremental counters and/or `_index.json` + authoritative **`total_questions`** from **`metadata.json`**).

**Example (valid):**

```json
{
  "answered": 18,
  "pending": 7,
  "completion": 0.72,
  "last_updated": "ISO8601"
}
```

**Not allowed:** per-question lists, unbounded blobs, recomputation that lists every object under `answers/` on each request.

**Future-proofing:** If progress ever becomes expensive, move rich aggregates to **`derived/metrics.json`** and update them asynchronously; keep **`progress.json`** minimal.

---

## 11. `total_questions`, `answered`, and `completion`

### 11.1 Definitions

- **`total_questions`:** **Authoritative** positive integer. **MUST NOT** be inferred by counting S3 objects, guessing from partial data, or using **`len(_index.items)`** as the denominator unless the spec explicitly equates index length to total assessment size (default: **do not**).

**Authoritative sources (pick one per product, document in metadata schema):**

- **`metadata.json`** (preferred), and/or  
- An **immutable assessment configuration** referenced by the audit (e.g. template id + version).

- **`answered`:** Count of questions whose answer record has **`state == submitted`** (not merely “has a file” or “draft”).

- **`completion`:**

```text
completion = answered / total_questions
```

(with safe handling when `total_questions == 0`—define product behavior, e.g. `0` or `null`).

### 11.2 Changing `total_questions` mid-course

**Allowed but controlled:**

1. The new value **MUST** be written to the **authoritative source** (`metadata.json` and/or linked config).
2. **`completion` MUST be recomputed immediately** from the new denominator.
3. **`progress.json`** and **`audit_summary.json` MUST** be updated to stay consistent.

**Consistency:**

- Treat **`total_questions`** as a **single source of truth** for the denominator.
- Avoid stale caches: re-read authoritative source when recomputing, or invalidate when metadata version/ETag changes.

**Product recommendation:** Prefer **`total_questions` immutable after audit start** when possible to avoid UX and compliance confusion. If the assessment template can change, version the template and record which version the audit uses.

### 11.3 Implementation hints (no full scan)

- On answer submit/withdraw: adjust **`answered`** / **`pending`** incrementally, or  
- Derive **`answered`** from **`_index.json`** only if each row includes **`state`** and you count **`submitted`** only.

**`total_questions`:** always from **`metadata.json`** (or fixed assessment config), never from S3 list length.

---

## 12. Historical data / rounds

**`rounds/` snapshots are intentionally not part of this layout.**  
History is represented by:

- **`timeline.json`** events, and  
- **Per-object `version` / `last_updated`** on `current/*` JSON.

If a future product requires point-in-time snapshots, use explicit exports (e.g. under **`exports/`**) or a separate versioning strategy—do not reintroduce ad-hoc `rounds/` without updating this spec.

---

## 13. Lookups and exports (summary)

Unchanged intent at bucket root:

- **`lookups/domains/{domain}.json`** → `{ "org_id" }`
- **`lookups/organizations/{org_id}.json`** — lightweight org index
- **`lookups/ai_systems/{ai_system_id}.json`** — routing metadata (may need alignment with project-scoped paths after migration)
- **`lookups/auditor_master.json`**
- **`exports/…`** — e.g. blockchain export payloads

**`org_profile.json`:** On write, domain/org lookups are synced per **`LookupService`** (existing behavior).

---

## 14. Service modules (reference)

| Area | Module |
|------|--------|
| Path helpers | `app/etl/s3/utils/s3_paths.py` |
| Org / projects / systems registry | `operational_service.py` |
| Audit lifecycle, metadata, timeline, summary | `audit_lifecycle_service.py` |
| Answers / AI / auditor / report | `answer_service.py`, `ai_service.py`, `auditor_service.py`, `report_service.py` |
| Evidence + index | `evidence_service.py` |
| Blockchain export file | `export_service.py` |
| Lookup writes | `lookup_service.py` |

---

## 15. Limitations and explicit non-goals

| Topic | Rule |
|-------|------|
| **ULID charset** | Invalid letters (I, L, O, U) rejected under strict validation. |
| **`system_key` length** | Fixed at **35**; `org_id` fixed at **26**. Any future format change requires a new spec version. |
| **S3 listing in hot paths** | Avoid; use keys + `_index.json`. |
| **Embeddings in S3** | Many small objects can get expensive; at scale consider external vector store or batched objects. |
| **Derived vs truth** | Never treat **`derived/*`** as authoritative for compliance without a defined rebuild and audit procedure. |

---

## 16. Migration note (codebase vs this spec)

Until migration completes, the repository may still use:

- Segment name **`ai_systems/`** instead of **`systems/`**
- **`audit_id`** equal to `{org_id}-{project_id}-{ai_system_id}` with a single audit per combo
- **`rounds/`** and paths generated by older **`s3_paths.py`**

Treat **this README** as the **target contract**.

---

## 17. Backend migration checklist (clean bucket — no S3 data migration)

When the bucket is **empty**, you only migrate **code**: paths, services, APIs, tests, and tooling. Work in phases so nothing is orphaned.

**Repo status:** Phase A–E largely done: `systems/` segment, **only** Crockford ULIDs for `org_id` and `audit_id` on APIs, **3-digit** `project_id` and **4-digit** `ai_system_id` (no legacy `0` default scope), `_index.json` maintained via `current_index.py`, `recompute_audit_summary` prefers `answers/_index.json` when present, `derived/*` stub + Celery `recompute_derived_audit_task`. Enforcement: `app/rest/strict_audit_ids.py` (always on for audit-scoped routes). Legacy one-off script `migrate_legacy_to_v2.py` copies into `systems/` using project `001` / system `0001` as the fixed migration target.

### Phase A — Path layer (single source of truth)

| Task | Where |
|------|--------|
| Rename **`ai_systems/` → `systems/`** in URL builders | `app/etl/s3/utils/s3_paths.py` (`ai_systems_prefix` → `systems_prefix`, `system_root`, comments) |
| **`audit_id` = ULID** only under `audits/`; stop using `make_audit_id()` as folder name | `s3_paths.py`, callers |
| Add **`derived/`** key helpers (`metrics_key`, `insights_key`, embeddings prefix, …) | `s3_paths.py` |
| Add **`current/.../_index.json`** key helpers per section | `s3_paths.py` |
| Remove or no-op **`round_prefix` / `rounds/`** | `s3_paths.py` |
| Update path unit tests | `app/etl/s3/tests/test_s3_paths.py` |

Introduce a small **`app/etl/s3/utils/ids.py`** (or similar) for: **`normalize_ulid`**, **`parse_system_key`**, **`parse_audit_key`**, **`validate_audit_key_regex`** — then call from REST and services.

### Phase B — Lifecycle and writes

| Task | Where |
|------|--------|
| **`create_audit`**: generate **ULID** `audit_id`; persist in **`metadata.json`**; set authoritative **`total_questions`** | `audit_lifecycle_service.py` |
| Write **`timeline.json`** / **`audit_summary`** / **`progress`** consistent with §9–§11 | `audit_lifecycle_service.py`, `answer_service.py`, `evidence_service.py`, … |
| **`_index.json`**: update on every answer / AI / feedback write (sync) | `answer_service.py`, `ai_service.py`, `auditor_service.py` (shared helper) |
| **`derived/`** updates only via async worker (stub OK initially) | new module or `pipeline/` |
| Remove **`RoundService`** usage from org flow | `organizations.py` |
| Delete or deprecate **`round_service.py`** | `app/etl/s3/services/round_service.py` |

### Phase C — Read paths and aggregates

| Task | Where |
|------|--------|
| **`AnswerService` / `ReportService` / `AuditorService` / `AIService` / `EvidenceService`**: use new prefixes only | respective `services/*.py` |
| **`export_service`**, **`review_service`** path strings in docstrings + keys | `export_service.py`, `review_service.py` |
| **`operational_service`**: default audit creation must use **ULID** audit ids (remove `make_audit_id` default for new audits) | `operational_service.py` |
| **`lookup_service`** / **`lookups/ai_systems/`**: ensure index shape still matches routing (may need `audit_id` + ULID semantics) | `lookup_service.py` |

### Phase D — REST, admin, pipeline, auth

| Task | Where |
|------|--------|
| Assessment + org routes: **`audit_id` path/query = ULID**; validate on entry | `app/rest/v1/assessment.py`, `organizations.py`, schemas |
| **`admin_s3.py`**: drop **`rounds`** route; align keys with `s3_paths` | `app/rest/v1/admin_s3.py` |
| **`admin_tests`**, **`pipeline/*`** (`service.py`, `tasks.py`, `router.py`, `migrate_s3.py`, `id_generator.py`): replace hardcoded `ai_systems` segments and old audit id rules | `app/pipeline/` |
| **`role_service` / `service`**: if they build keys via `_prefix`, re-scan | `app/auth/` |

### Phase E — Scripts and tests

| Task | Where |
|------|--------|
| **`migrate_legacy_to_v2.py`**: update or mark legacy-only | `app/etl/s3/scripts/` |
| **Lifecycle / answer / report / operational tests** | `app/etl/s3/tests/*.py` |
| **Grep** for `ai_systems/`, `make_audit_id`, `round_prefix`, `RoundService` until clean | repo |

### Phase F — Synthetic data & verification

| Task | Notes |
|------|--------|
| Seed **org → project → system → audit (ULID)** | Use strict ULIDs (Crockford) for `org_id` and `audit_id` |
| Exercise **answers + `_index.json` + progress + metadata `total_questions`** | Assert `completion` and `answered` with **`state == submitted`** |
| Hit **REST** and **`admin/s3`** readouts | Full path smoke |
| Optional: **async job** writes **`derived/metrics.json`** | After core path stable |

### Quick grep targets (before sign-off)

```bash
rg "ai_systems/" app --glob "*.py"
rg "make_audit_id" app --glob "*.py"
rg "round_prefix|RoundService|rounds/" app --glob "*.py"
```

---

**Order recommendation:** **A → B → C → D → E → F**. Do not change REST contract before `s3_paths` and lifecycle agree, or you will debug double layouts.
