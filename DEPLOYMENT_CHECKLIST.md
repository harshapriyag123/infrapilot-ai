# Zerops deployment checklist

## Before import
- Push this project to GitHub.
- Replace `YOUR_GITHUB_REPOSITORY_URL` in `zerops-import.yaml`.
- Import the project into Zerops or create services manually:
  - `frontend` — Static
  - `api` — Python 3.12
  - `worker` — Python 3.12
  - `db` — PostgreSQL single-node
- Make sure the repository root contains `zerops.yaml`.

## Database
Set `DATABASE_URL` for both `api` and `worker` to the Zerops PostgreSQL connection URL.
If Zerops exposes generated DB variables under a different name, map them into this variable.

## API secrets
Set on `api` and `worker`:
- `GITHUB_TOKEN` (recommended)
- `OPENAI_API_KEY` (optional)
- `OPENAI_MODEL` (required only if using OpenAI diagnosis)

## CORS
On `api`, set:
- `CORS_ORIGINS=https://<your-frontend-public-url>`

## Frontend build variable
On `frontend`, set:
- `VITE_API_BASE_URL=https://<your-api-public-url>`

Because Vite injects `VITE_*` values during build, redeploy the frontend after setting/changing it.

## Verify
- Open `https://<api>/health` → should return status ok.
- Open `https://<api>/docs` → Swagger UI.
- Open frontend.
- Analyze a public GitHub repository.
- Confirm the worker changes job status queued → running → completed.
- Confirm refresh still preserves the result in PostgreSQL.
- Test Deployment Doctor.
- Open the live URL in incognito before submission.
