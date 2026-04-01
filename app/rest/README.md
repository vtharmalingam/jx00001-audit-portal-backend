# REST API (`/api/v1`)

All traffic is HTTP. OpenAPI: **`/docs`**, **`/redoc`**.

## Organizations — `/api/v1/organizations`

| Method | Path | Summary |
|--------|------|---------|
| GET | `/organizations` | List orgs (query filters + `page` / `page_size`). |
| PUT, PATCH | `/organizations/{org_id}` | Merge org profile. |
| POST | `/organizations/{org_id}/onboarding-decision` | Approve / reject. |
| POST | `/organizations/{org_id}/ai-systems` | Create AI system. |
| GET | `/organizations/{org_id}/ai-systems` | List systems (`status`, `stage` query). |

Schemas: `app/rest/v1/organizations_schemas.py`.

## Assessment — `/api/v1/assessment`

| Method | Path | Summary |
|--------|------|---------|
| GET | `/assessment/categories` | List categories. |
| GET | `/assessment/questions?category=` | Questions for category. |
| POST | `/assessment/evaluate-answer` | Body: `q_id`, `user_answer`, optional `category`. |
| POST | `/assessment/answers` | Upsert answer (`question_id`, `user_answer`, `org_id`, `state`, …). |
| GET | `/assessment/answers?org_id=&audit_id=` | Answers map (storage uses `audit_id=0`). |
| GET | `/assessment/orgs/{org_id}/audit-view?audit_id=` | Full audit / gap snapshot. |
| POST | `/assessment/reviews` | Auditor feedback (`auditor_id` optional; replaces old WS `client_id`). |

Schemas: `app/rest/v1/assessment_schemas.py`.

## Knowledge — `/api/v1/knowledge`

| Method | Path | Summary |
|--------|------|---------|
| POST | `/knowledge/semantic-search` | Body: `context`, `count`. |
| POST | `/knowledge/gap-analysis` | Body: `index_name`, `question`, `user_answer`, optional ids. |

Schemas: `app/rest/v1/knowledge_schemas.py`.

## Shared dependencies

`app/rest/deps.py` — `data_dir`, `s3_client`, `llm_client`, `semantic_engine`.

## Errors

Use `HTTPException` with `detail` as `{"code", "message"}` where applicable.
