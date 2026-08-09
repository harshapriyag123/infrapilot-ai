# InfraPilot Runbook

Quick troubleshooting steps for local development and common failures.

## 1) Backend won't respond / Network errors
- Ensure the backend is running:
```
uvicorn backend.app.main:app --reload --port 8000
```
- Check the backend logs for errors printed on startup (DB checks, CORS allow_origins).

## 2) Database connection failures
Symptoms: worker or API prints `OperationalError`, `connection refused`, or startup shows "WARNING: Database connectivity check failed".

Steps:
- Verify `DATABASE_URL` in `.env` or environment. For local SQLite (development), use:
```
set DATABASE_URL=sqlite:///./infrapilot.db
```
- For PostgreSQL ensure the service is running and accessible from your machine. Test with `psql` or use a simple Python script:
```
python - <<'PY'
from sqlalchemy import create_engine
print(create_engine("${DATABASE_URL}").connect())
PY
```
- If you migrated the DB, ensure the `error_hint` column exists (see `migrations/0001_add_error_hint.sql`).

## 3) CORS errors in browser (blocked preflight)
Symptoms: browser DevTools shows CORS preflight (OPTIONS) failing or missing `Access-Control-Allow-*` headers.

Steps:
- Confirm `VITE_API_BASE_URL` in frontend matches the backend base (including port). Example for dev:
  - Frontend runs on `http://localhost:5173` and backend on `http://localhost:8000`.
- Check backend startup line `CORS allow_origins:` printed by the server. Ensure `http://localhost:5173` is listed.
- Manually test preflight:
```
curl -i -X OPTIONS 'http://localhost:8000/api/jobs' \
  -H 'Origin: http://localhost:5173' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```
- If the response lacks `Access-Control-Allow-Origin`, set `CORS_ORIGINS` in `.env`:
```
CORS_ORIGINS=http://localhost:5173
```
- Restart backend after changes.

## 4) GitHub API rate limits
Symptoms: job fails with rate limit message or `403`.

Steps:
- Set `GITHUB_TOKEN` in `.env` or environment and restart backend. For example:
```
set GITHUB_TOKEN=ghp_xxx
```
- For local debugging you can also shorten analysis scope by editing the worker to limit files fetched.

## 5) Frontend configuration
- Ensure `.env` in frontend (or `VITE_API_BASE_URL` in your shell) points to the backend. The frontend defaults to `http://localhost:8000`.
- Rebuild or run the frontend dev server after env changes:
```
cd frontend
npm install
npm run dev
```

## 6) Getting logs
- The API exposes `/api/logs` for recent error entries from failed jobs.

## Contact
If you still have issues, capture the backend console output and the browser Network preflight response and share them for further debugging.
