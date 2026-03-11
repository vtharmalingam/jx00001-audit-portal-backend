
## S3 Structure

```json
audit-system-data/
│
├── organizations/
│   └── {org_id}/
│       ├── org_profile.json
│       │
│       └── audits/
│           └── {audit_id}/
│               ├── metadata.json
│               │
│               ├── current/                      ← ACTIVE WORKING STATE
│               │   ├── answers/
│               │   │   └── {question_id}.json
│               │   │
│               │   ├── ai_analysis/
│               │   │   └── {question_id}.json
│               │   │
│               │   ├── auditor_feedback/
│               │   │   └── {question_id}.json
│               │   │
│               │   └── progress.json            ← derived cache (optional)
│               │
│               ├── rounds/                      ← SNAPSHOTS (IMMUTABLE)
│               │   └── round_{n}/
│               │       ├── answers.json
│               │       ├── ai_analysis.json
│               │       ├── auditor_feedback.json
│               │       └── round_summary.json
│               │
│               └── timeline.json                ← full audit trace
│
├── lookups/
│   ├── domains/
│   │   └── {domain}.json                        ← maps → org_id
│   │
│   └── orgs/
│       └── {org_id}.json                        ← lightweight index (optional)
│
└── exports/
    └── blockchain/
        └── {audit_id}.json                      ← final exported payload

```

Question:
  A. Is this a good change?
    - org_id => domain?
  b. What's the purpose of `audit > metadata.json`?


### org_profile:

```json
{
  "org_id": "org_123",
  "name": "Acme Corp",
  "domains": ["acme.com"],
  "created_at": "..."
}
```

### metadata.json (Audit Control Plane)

```json
{
{
  "audit_id": "audit_001",
  "org_id": "org_123",

  "auditor_id": "aud_001",

  "status": "in_progress",
  "current_round": 2,

  "started_at": "...",
  "last_updated_at": "...",
  "completed_at": null
}
```

### timeline.json
Full trace of:

  - User actions
  - AI runs
  - Auditor actions

```json
{
  "events": [
    {
      "timestamp": "...",
      "actor": "user",
      "action": "updated_answer",
      "question_id": "Q4_4",
      "version": 3
    }
  ]
}

```





### answers > {question_id}.json 

```json
{
  "question_id": "Q4_4",
  "answer": "...",

  "state": "draft",  
  "version": 3,       -> This is required for "AI processing-trigger"

  "last_updated_at": "...",
  "last_updated_by": "..."
}

```
suggestion: 
  - status should be a static list


## ai_analysis/{question_id}.json

```json
{
  "question_id": "Q4_4",

  "last_analyzed_version": 3,
  "analyzed_at": "2026-02-21T02:00:00Z",

  "risk_level": "medium",

  "gap_report": {
    "synthesized_summary": "The organization claims 18 months runway but lacks supporting documentation.",

    "key_themes": [
      "financial stability",
      "documentation gap"
    ],

    "user_gap": [
      "No audited financial statements provided",
      "Runway not validated"
    ],

    "insights": [
      "Statement appears optimistic but unsupported",
      "Potential risk if funding assumptions fail"
    ],

    "match_score": 0.62
  }
}

```

Note:
- risk_level: low | medium | high | critical

Critical Note:
- Every AI run overwrites entire file (No partial updates)

#### TODO Suggestion:

Add `evaluation_basis` useful for: `transparency` and `enterprise audits`:

```json
"evaluation_basis": [
  "expected financial documentation",
  "risk disclosure standards"
]
```




## auditor_feedback/{question_id}.json

```json
{
  "question_id": "Q4_4",

  "reviewed_version": 3,
  "reviewed_at": "2026-02-21T12:00:00Z",
  "auditor_id": "aud_001",

  "review_state": "needs_revision",

  "summary": "Financial claims lack supporting documentation",

  "feedback": [
    {
      "type": "gap",
      "message": "Provide audited financial statements",
      "severity": "high"
    },
    {
      "type": "clarification",
      "message": "Explain assumptions behind runway calculation",
      "severity": "medium"
    }
  ]
}

```

suggestion: 
  - `review_state` : not_reviewed | in_review | needs_revision | compliant | non_compliant


## progress.json

```json
{
  "last_updated_at": "2026-02-21T12:05:00Z",

  "answers": {
    "draft": 20,
    "submitted": 25,
    "locked": 0
  },

  "ai": {
    "processed": 30,
    "pending": 15
  },

  "auditor": {
    "not_reviewed": 70,
    "in_review": 5,
    "needs_revision": 10,
    "approved": 10,
    "rejected": 5
  },

  "round_status": "in_progress"
}

```

Observations:
    
    Option A : instead of having a json, dynamically these can be calculated for better data integrity:
      a. Answered vs Draft
      b. Completed vs AI Processed
      c. AI Processed Vs Auditor reviewed
      d. Count by auditor::status
    
    Option B : Periodic recompute (fallback)


### org_lookup.json

`lookups/domains/acme.com.json`:

```json
{
  "org_id": "org_123"
}

```

## exports/blockchain/
Final immutable payload:

`exports/blockchain/audit_001.json`:

```json
{
  "by_domain": {
    "acme.com": "org_123",
    "acme.ai": "org_123"
  },

  "by_org_id": {
    "org_123": {
      "name": "Acme Corp",
      "domains": ["acme.com", "acme.ai"],
      "created_at": "2026-02-01T10:00:00Z"
    }
  }
}
```