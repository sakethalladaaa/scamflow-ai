# Incident and rollback notes

- Disable new writes at the Railway edge or scale the application to zero only
  when necessary to protect data. Preserve the database for investigation.
- Rotate `SCAMFLOW_REVIEWER_TOKEN` only for local/demo environments; production
  reviewer access is role-backed account access.
- If a provider is failing, set the extractor to `rules` and keep the UI's
  rules-only disclosure visible. Never silently substitute a fake provider.
- Capture request IDs, deployment IDs, status codes, and timestamps. Do not
  capture raw conversations, cookies, passwords, OTPs, tokens, or reviewer notes.
- Restore the last known-good image, verify `/ready`, then run the synthetic
  registration/case/assessment/delete smoke flow before reopening traffic.
