# ScamFlow AI beta deployment runbook

## Railway resources

Use one Railway project with a PostgreSQL service and an application service.
The application serves the built React bundle from FastAPI so browser cookies
remain same-origin. Set `DATABASE_URL` from the Railway PostgreSQL reference and
set `SCAMFLOW_TRUSTED_ORIGIN` to the exact HTTPS application domain.

Required variable names are listed in `.env.example`. Secret values belong only
in Railway variables. Generate reviewer/admin credentials out of band and never
paste them into logs, tickets, URLs, or the frontend.

## Release sequence

1. Run the backend and frontend quality gates from the README.
2. Build the Docker image locally or in CI.
3. Apply the checked-in Alembic head against the target PostgreSQL database.
4. Deploy the application service from the reviewed commit.
5. Verify `/health` and `/ready`, then run a synthetic browser flow: register,
   log in, submit a Digital Arrest or Fake Refund example, inspect exact evidence,
   and delete the synthetic case.
6. Record the deployment ID, commit SHA, migration revision, and smoke results.

## Rollback

Rollback by redeploying the last known-good application image or commit. Do not
run destructive database commands during an application rollback. Database
migrations must be backward-compatible with the previous application until the
roll-forward is complete; use a separate reviewed migration to remove obsolete
columns later.
