# Mailpit email testing (critical path)

Use this for local/dev validation of SMTP + invite/onboarding emails without sending real mail.

---

## 1) Start Mailpit

If using this repo's Compose file:

```bash
docker compose up -d mailpit
```

Mailpit endpoints:

- SMTP: `1025`
- UI inbox: [http://localhost:8025](http://localhost:8025)

---

## 2) Configure platform SMTP (required fields only)

Set via `PATCH /api/v1/platform-settings`:

```json
{
  "general": {},
  "smtp": {
    "enabled": true,
    "host": "mailpit",
    "port": 1025,
    "encryption": "none",
    "fromAddress": "noreply@local.test",
    "fromName": "Audit Portal Dev",
    "authRequired": false,
    "verifyTls": false
  }
}
```

Important:

- If API runs **in Docker Compose**: `host = "mailpit"`
- If API runs **on host machine**: `host = "localhost"`

---

## 3) Verify SMTP first

Call:

- `POST /api/v1/platform-settings/smtp/send-test`

Example body:

```json
{
  "to": "dev.user@local.test",
  "subject": "SMTP test",
  "text": "Mailpit test message"
}
```

Expected:

- API response: `ok: true`
- Message appears in Mailpit UI at `localhost:8025`

Do this before testing invite/onboarding flows.

---

## 4) Verify auth-driven emails

Then test flows such as:

- `POST /api/v1/auth/resend-invite`
- `POST /api/v1/auth/invite`
- `POST /api/v1/auth/onboard-firm`
- `POST /api/v1/auth/onboard-individual`
- `POST /api/v1/auth/onboard-firm-client`

Check response flags:

- `email_sent: true` → delivery attempted successfully
- `email_sent: false` + `email_error` → onboarding/invite succeeded, email failed (share `invite_url` manually)

---

## 5) Fast troubleshooting

- **`SMTP_CONFIG_INVALID: From address is required.`**
  - Set `smtp.fromAddress` to a plain email (example: `noreply@local.test`).

- **`SMTP_SEND_FAILED ... 553 ... not a valid RFC 5321 address`**
  - `to` is invalid (often `"string"` from Swagger default), or
  - `fromAddress` is not a plain email.

- **No email in Mailpit UI**
  - Wrong SMTP host for runtime context (`mailpit` vs `localhost`),
  - Mailpit container not running,
  - SMTP test endpoint fails.
