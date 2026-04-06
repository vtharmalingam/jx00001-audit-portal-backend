# Auth module

This folder implements cookie-based JWT authentication backed by S3. User records (including password hashes, role, and derived **tier**) live in **`platform/auth_users.json`**, managed by **`AuthUserService`**. The FastAPI **`/auth`** router issues HttpOnly cookies; **`dependencies.py`** resolves the current user from the access-token cookie for protected routes.

For how **tier** relates to roles and how this differs from **`platform/aict_users.json`**, see the main ETL/data docs or ask the team—AICT’s separate user roster is not used for login.

---

## Architecture

```mermaid
flowchart LR
  subgraph Client
    B[Browser / API client]
  end

  subgraph API["FastAPI /auth router"]
    R[auth/router.py]
    D[auth/dependencies.py]
    T[auth/tokens.py]
  end

  subgraph Service["AuthUserService"]
    A[Load / save users]
    P[Password verify + hash]
    RT[Refresh token hash in user row]
  end

  S3[("S3: platform/auth_users.json")]

  B <-->|HttpOnly cookies: access_token, refresh_token| R
  R --> T
  R --> A
  A --> P
  A --> RT
  A <--> S3
  D --> T
  D -->|JWT claims → id, email, role, tier| R
```

---

## Login, refresh, and logout

```mermaid
sequenceDiagram
  participant C as Client
  participant L as POST /auth/login
  participant S as AuthUserService
  participant J as JWT helpers
  participant K as S3 auth_users.json

  C->>L: email + password
  L->>S: find_by_email, authenticate
  S->>K: read users
  S-->>L: safe user or null
  alt invalid or pending
    L-->>C: 401 / 403
  else ok
    L->>J: create_access_token + create_refresh_token(claims)
    L->>S: store_refresh_token(user_id, SHA256(refresh))
    S->>K: write users
    L-->>C: Set-Cookie + AuthResponse
  end

  Note over C,K: Later: POST /auth/refresh

  C->>L: refresh cookie
  L->>J: decode_token(refresh)
  L->>S: validate_refresh_token(user_id, SHA256(refresh))
  S->>K: read user row
  L->>J: new access + refresh JWTs
  L->>S: store_refresh_token (rotation)
  L-->>C: new cookies

  Note over C,K: POST /auth/logout

  C->>L: access cookie
  L->>S: clear_refresh_token(user_id)
  S->>K: write users
  L-->>C: clear auth cookies
```

---

## Resolving the current user on each request

`get_current_user` and `get_optional_user` read the **`access_token`** cookie, decode the JWT, and require `type == "access"`. They do **not** load S3 on every request; claims carry `sub`, `email`, `role`, and `tier`. **`GET /auth/me`** reloads the user from S3 by `sub` so the response matches the latest stored profile.

```mermaid
flowchart TD
  REQ[Incoming request]

  REQ --> COOKIE{access_token cookie present?}

  COOKIE -->|no| OPT{Depends: optional or required?}
  OPT -->|get_optional_user| NULL[Return None — dev/mock or public behaviour]
  OPT -->|get_current_user| U401[401 NOT_AUTHENTICATED]

  COOKIE -->|yes| DEC[decode_token — type must be access]
  DEC --> BAD{valid JWT?}
  BAD -->|no| INV[401 INVALID_TOKEN or None for optional]
  BAD -->|yes| U["User dict: id, email, role, tier from claims"]

  U --> HANDLER[Route handler / permission checks]
```

---

## User lifecycle (register, invite, onboard)

```mermaid
flowchart TB
  REG["POST /auth/register\n(self-serve: *_admin roles only)"] --> CREATE["create_user → password_hash, tier from role"]
  INV["POST /auth/invite\n(admin creates pending user)"] --> PEND["create_pending_user + invite_token_hash"]
  PEND --> ACT["POST /auth/activate\nverify invite JWT + hash → activate_user"]
  ONB["Onboard firm / individual / firm-client"] --> PEND

  CREATE --> S3[(auth_users.json)]
  PEND --> S3
  ACT --> S3
```

---

## Key files

| File | Role |
|------|------|
| `service.py` | `AuthUserService` — CRUD, `authenticate`, refresh-token hash storage, `tier` derived from `role` |
| `router.py` | `/auth` routes: login, refresh, logout, register, invite, activate, onboarding, user admin |
| `dependencies.py` | `get_current_user`, `get_optional_user`, `require_roles` |
| `tokens.py` | Create/decode JWTs; cookie helpers |
| `passwords.py` | Hashing and verification |
| `permissions.py` | Role → permission checks for route guards |
| `role_service.py` | Canonical role definitions (tier, level, permissions metadata) |
