Kingsly to Answer:
---

1. When I onboarded client (either for firm or individual), it gets into `auth_users.json`. But why is it not getting displayed under 'AICT Admin' login under 'Firms's client so that he can approve? The flow is broken?


1. When firm manager onboards a "client" (we call that as admin - refer to the redmine issue #67), you create "auth_users.json" the below entry:

```json

{
id: "e59a36b5-8255-49fe-8f64-e5fc071c8478",
name: "Admin of CDE",
email: "cde@gmail.com",
password_hash: null,
role: "individual_admin",
tier: "individual",
status: "pending",
invite_token_hash: "9d71d54e7863aaf226d1af3439f7d06e2ccc3c5019f07b537274df02fdde56fc",
refresh_token_hash: null,
created_at: "2026-04-06T03:21:41.566533",
updated_at: "2026-04-06T03:21:41.566533"
}
```
Question:

- I had updated my observations regarding the incorrect update of the JSON in the same issue (#67), besides that point
where are you linking the Firm (say, a firm XYZ that onboarded this client) is tracked in here?


---
1. I understand that  the "invite" is primarily for the respective TIER admins to add their team members.

Endpoint:
`http://localhost:3001/api/v1/auth/invite`

Payload:
```json
{name: "Tharma", email: "vtharmalingam@gmail.com", role: "aict_manager"}
```

It produces a link like this:

`http://localhost:3000/auth/set-password?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1ZDE4Nzc3ZC0yZGM3LTRkMzYtYWFiOS0wMDk2NWM1MmViNDciLCJlbWFpbCI6InZ0aGFybWFsaW5nYW1AZ21haWwuY29tIiwiZXhwIjoxNzc1NzA4Njg5LCJ0eXBlIjoiaW52aXRlIn0.yg4w0_010XXPcuVBKsJ9235y4hf1CYkuTeR0mLknof0`


Question:
- What if the user does not click on the link in 30 mins (the token lifetime)? Should not we provide an option to resend the invite?
- Please refer to issue #68.
---


1. Where do we use user "Registeration"? Please clarify the use case.