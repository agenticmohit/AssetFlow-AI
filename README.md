# AssetFlow AI

Creative feedback, revision, and approval workspace for designers and remote creative teams. AssetFlow is deliberately not a source-file or final-delivery drive.

## Architecture

The application uses a layered structure:

- `assetflow/api/routes`: versionable JSON API endpoints
- `assetflow/web`: HTMX/Jinja browser interface
- `assetflow/services`: business rules and transactional workflows
- `assetflow/db`: SQLAlchemy models, sessions, and deterministic demo seed
- `assetflow/schemas`: validated request/response contracts
- `assetflow/core`: configuration, security, and structured errors
- `tests`: isolated API and domain integration tests
- `migrations`: Alembic database migrations

SQLite is the development database. Production can use Supabase Postgres by changing `ASSETFLOW_DATABASE_URL`; the application and service layers require no rewrite.

## Local setup

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
# Paste your key after OPENAI_API_KEY= in .env (optional)
alembic upgrade head
uvicorn assetflow.main:app --reload
```

Open `http://127.0.0.1:8000`. API documentation is at `/docs`.

Demo login: `designer@assetflow.demo` / `AssetFlow123!`

The local `.env` file is already ignored by Git. Leave `OPENAI_API_KEY` blank to run without API calls. With a key, `gpt-4o-mini` is called only when a designer asks for a feedback summary or task list. Requests use small output limits, one SDK retry, a 30-second action cooldown, and a five-request hourly allowance per user. Only feedback text is sent; design files are never sent to the model. Failed task generation can fall back to a local checklist, while summaries clearly report that AI is unavailable instead of imitating an AI result.

## Beta workflow

1. Create a project and upload a lightweight design preview.
2. Collect color-coded team feedback and threaded client replies.
3. Convert revisions into persistent tasks and upload the next version.
4. Share a secure client link; clients comment or approve without an account.
5. Approval starts a 10-day preview grace period. The preview is then deleted while the project, comments, tasks, version notes, and decision remain.

Run the idempotent cleanup job daily:

```powershell
python -m assetflow.jobs.cleanup_previews
```

See `docs/STORAGE_LIFECYCLE.md` for the exact boundary between temporary previews and persistent collaboration history.

## Quality checks

```powershell
pytest --cov=assetflow --cov-report=term-missing
ruff check assetflow tests
pip check
```

The coverage threshold is enforced at 80% with branch coverage enabled.

## Operational endpoints

- `/health/live`: process liveness
- `/health/ready`: database readiness

Responses contain `x-request-id` and `x-response-time-ms` headers. Unhandled production errors return a safe error ID while full details are written to server logs.

## Production notes

- Set a strong `ASSETFLOW_SECRET_KEY` and disable debug.
- Set `ASSETFLOW_DATABASE_URL` to the Supabase pooled Postgres connection string.
- Set `ASSETFLOW_ALLOWED_HOSTS` to the deployed hostname only.
- Run Alembic migrations as a release step, before starting new application instances.
- Store temporary review previews in a private object bucket; local disk is development-only. This is not a user-facing storage product.
- Schedule `python -m assetflow.jobs.cleanup_previews` at least daily.
- Run multiple Uvicorn workers behind a reverse proxy/load balancer.
- Keep `/health/ready` connected to deployment readiness probes.
- Use rolling deployments so old instances remain available until new instances pass readiness.

## Railway deployment

The root `Dockerfile` is detected automatically. `railway.json` runs Alembic before release, checks `/health/ready`, and applies bounded restart and drain settings.

Create a Railway Postgres service and set:

```text
ASSETFLOW_ENVIRONMENT=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
ASSETFLOW_SECRET_KEY=<at-least-32-random-characters>
ASSETFLOW_ALLOWED_HOSTS=<your-public-domain>,healthcheck.railway.app
ASSETFLOW_UPLOAD_DIR=/app/var/uploads
OPENAI_API_KEY=<optional-secret>
ASSETFLOW_OPENAI_MODEL=gpt-4o-mini
```

Attach a small Railway volume at `/app/var/uploads` while active previews use local media. Keep one replica with that volume. Move previews to private object storage before scaling horizontally; the collaboration history already remains in Postgres.

See `docs/PRODUCTION_READINESS.md` for the release gate, security controls, and infrastructure still required outside the repository.
