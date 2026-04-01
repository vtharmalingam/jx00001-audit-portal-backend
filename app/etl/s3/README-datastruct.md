# S3 data layout (v2)

Bucket root (example: `audit-system-data/`). Code uses optional `BASE_PREFIX` in `app/etl/s3/utils/s3_paths.py` for tests.

## Top level

```text
audit-system-data/
├── organizations/
├── lookups/
└── exports/
```

## Organization

```text
organizations/{org_id}/
├── org_profile.json
├── ai_systems.json              ← org-level systems registry (plus per-system system.json)
└── projects/
    └── {project_id}/
        ├── project.json
        └── ai_systems/
            └── {ai_system_id}/
                ├── system.json
                └── audits/
                    └── {audit_id}/
                        ├── metadata.json
                        ├── audit_summary.json
                        ├── timeline.json
                        ├── current/
                        │   ├── answers/{question_id}.json
                        │   ├── ai_analysis/{question_id}.json
                        │   ├── auditor_feedback/{question_id}.json
                        │   ├── evidence/{question_id}/…
                        │   ├── evidence_index.json
                        │   └── progress.json            (optional derived cache)
                        └── rounds/
                            └── round_{n}/
                                ├── answers.json
                                ├── ai_analysis.json
                                ├── auditor_feedback.json
                                ├── evidence/…
                                └── round_summary.json
```

## org_profile.json

- `org_id` (immutable), `name`, optional `domains[]`, `org_type`, `created_at`, `updated_at`, plus portal-specific fields merged by `OperationalService.merge_org_profile`.
- On write, **`lookups/organizations/{org_id}.json`** and **`lookups/domains/{domain}.json`** are updated when `domains` is present.

## metadata.json (audit control plane)

- `audit_id`, `org_id`, `project_id`, `ai_system_id`, `auditor_id`, `status`, `current_round`, `started_at`, `last_updated_at`, `completed_at`.

## audit_summary.json

Dashboard counters (`total_questions`, `answered`, `ai_processed`, `reviewed`, `compliant`, `non_compliant`, `needs_revision`, …). Recomputed on answer / AI / review / evidence mutations and via `GET .../summary?recompute=true`.

## current answers

- `attachments[]`: `{ file_name, s3_key, uploaded_at }` aligned with evidence index.

## Lookups

- `lookups/domains/{domain}.json` → `{ "org_id" }`
- `lookups/organizations/{org_id}.json` — lightweight org index
- `lookups/ai_systems/{ai_system_id}.json` — `{ org_id, project_id, audit_id?, status?, … }`
- `lookups/auditor_master.json` — existing auditor roster

## Exports

- `exports/blockchain/{audit_id}.json` — payload from `BlockchainExportService` (metadata + timeline + optional org profile).

## Services (reference)

| Area | Module |
|------|--------|
| Paths | `app/etl/s3/utils/s3_paths.py` |
| Org / projects / AI registry | `operational_service.py` |
| Audit create / metadata / timeline / summary | `audit_lifecycle_service.py` |
| Answers / AI / auditor / report | `answer_service.py`, `ai_service.py`, `auditor_service.py`, `report_service.py` |
| Evidence + index | `evidence_service.py` |
| Round snapshots | `round_service.py` |
| Blockchain file | `export_service.py` |
| Lookup writes | `lookup_service.py` |
