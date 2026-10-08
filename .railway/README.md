# ScamFlow AI Railway configuration

`railway.ts` records the deployed development MVP infrastructure:

- one `scamflow-ai` replica in `sfo`;
- `/health` as the deployment health check;
- a 500 MB persistent volume mounted at `/data`;
- volume-usage alerts; and
- preserved environment variables, so secret/runtime values are not committed.

The hosted application intentionally runs the disclosed deterministic development
extractor. It is not a production AI service.

From an authenticated and linked repository checkout:

```bash
cd .railway
npm ci
cd ..
railway config plan
```

Review the plan before applying it. To deploy the current source after review:

```bash
railway up --service scamflow-ai --ci
```

Do not increase the replica count while SQLite is the datastore. Check current
Railway pricing and usage before changing infrastructure.
