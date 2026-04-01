# REST API (`/api/v1`)

All traffic is HTTP. OpenAPI: **`/docs`**, **`/redoc`**.

## Organizations — `/api/v1/organizations`

| Method | Path | Summary |
|--------|------|---------|
| GET | `/organizations` | List orgs (query filters + `page` / `page_size`). |
| PUT, PATCH | `/organizations/{org_id}` | Merge org profile (`domains`, `org_type`, …). |
| POST | `/organizations/{org_id}/onboarding-decision` | Approve / reject. |
| POST | `/organizations/{org_id}/projects` | Create `project.json` (v2). |
| GET | `/organizations/{org_id}/projects` | List project ids. |
| GET | `/organizations/{org_id}/projects/{project_id}` | Get project. |
| POST | `/organizations/{org_id}/audits` | Create audit (metadata, summary, timeline, AI-system lookup). |
| GET | `/organizations/{org_id}/audits/{audit_id}/metadata` | Query `project_id`, `ai_system_id` (default `0`). |
| GET | `/organizations/{org_id}/audits/{audit_id}/summary` | `audit_summary.json`; optional `recompute=true`. |
| POST | `/organizations/{org_id}/audits/{audit_id}/rounds` | Immutable round snapshot. |
| POST | `/organizations/{org_id}/audits/{audit_id}/blockchain-export` | Write `exports/blockchain/{audit_id}.json`. |
| POST | `/organizations/{org_id}/ai-systems` | Create AI system (`project_id` optional → `default`). |
| GET | `/organizations/{org_id}/ai-systems` | List systems (`status`, `stage` query). |

Schemas: `app/rest/v1/organizations_schemas.py`.

## Assessment — `/api/v1/assessment`

| Method | Path | Summary |
|--------|------|---------|
| GET | `/assessment/categories` | List categories. |
| GET | `/assessment/questions?category=` | Questions for category. |
| POST | `/assessment/evaluate-answer` | Body: `q_id`, `user_answer`, optional `category`. |
| POST | `/assessment/answers` | Upsert answer; body: `audit_id`, `project_id`, `ai_system_id` (defaults `0`, still v2 nested path). |
| GET | `/assessment/answers` | Query: `org_id`, `audit_id`, `project_id`, `ai_system_id`. |
| GET | `/assessment/orgs/{org_id}/audit-view` | Full audit / gap snapshot; query scope as above. |
| POST | `/assessment/reviews` | Auditor feedback; optional `recommendations`, `auditor_name`. |
| POST | `/assessment/evidence` | Register file (`content_base64` and/or `s3_key_override`). |

Schemas: `app/rest/v1/assessment_schemas.py`.

## Knowledge — `/api/v1/knowledge`

| Method | Path | Summary |
|--------|------|---------|
| POST | `/knowledge/semantic-search` | Body: `context`, `count`. |
| POST | `/knowledge/gap-analysis` | Body: `index_name`, `question`, `user_answer`, optional ids. |

Schemas: `app/rest/v1/knowledge_schemas.py`.

## Shared dependencies

`app/rest/deps.py` — `data_dir`, `s3_client`, `llm_client`, `semantic_engine`.

## S3 layout

See `app/etl/s3/README-datastruct.md`.

## Errors

Use `HTTPException` with `detail` as `{"code", "message"}` where applicable.
