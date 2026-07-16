# Beta production readiness

## Application release gate

- Run `alembic upgrade head` before starting the new release.
- Run `pytest --cov=assetflow --cov-report=term-missing`; the configured gate is 80% branch coverage.
- Run `ruff check assetflow tests` and `pip check`.
- Run `pip-audit -r requirements.txt --ignore-vuln PYSEC-2026-1325`.
- Build from the pinned packages in `requirements.txt` and `requirements-dev.txt`.
- Never copy `.env`, SQLite databases, logs, or `var/uploads` into the image or repository.

## Security already enforced by the app

- Passwords are bcrypt-hashed; browser and API sessions use expiring signed JWTs.
- JWT signing is restricted to HS256. The sole audit exclusion is the transitive `python-ecdsa` Minerva advisory, which affects ECDSA signing and is unreachable with the enforced algorithm.
- Production startup rejects weak secrets, debug mode, SQLite, wildcard/local hosts, and public upload directories.
- Interactive API documentation is disabled in production.
- Cookie-authenticated writes require a matching `Origin` or `Referer` in production.
- Session and review cookies are HTTP-only, SameSite=Lax, and Secure in production.
- Uploaded previews are served through authorization checks, never from the public static mount.
- Review links are stored as hashes, expire after 30 days, and a replacement link revokes the previous one.
- Review, invitation, and media tokens are redacted from application and Uvicorn access logs.
- Browser responses set CSP, anti-framing, MIME-sniffing, referrer, permissions, cache, and HSTS headers.
- Uploaded file types and sizes are allow-listed. Approved preview deletion is scheduled after the configured grace period.
- AI actions have a database-backed per-user hourly allowance and per-action cooldown, so limits remain effective across web workers.
- Unexpected production errors return a safe error identifier; secrets are not included in application logs.

## Deployment environment

Use a managed HTTPS host or container platform with:

- Supabase pooled Postgres and a dedicated least-privilege database user.
- A strong random `ASSETFLOW_SECRET_KEY` supplied through the host's secret manager.
- `ASSETFLOW_ENVIRONMENT=production`, `ASSETFLOW_DEBUG=false`, and the exact public hostname in `ASSETFLOW_ALLOWED_HOSTS`.
- A private, ephemeral preview volume or private object bucket. Local disk is acceptable for a single-instance beta, but not for multiple disposable instances.
- A daily `python -m assetflow.jobs.cleanup_previews` scheduled job.
- TLS termination, request-body limits, login/review-write rate limiting, access-log retention, backups, error monitoring, and uptime alerts at the platform or reverse-proxy layer.
- At least two application instances when the beta needs zero-downtime rolling deployments.

## OpenAI key and data boundary

`OPENAI_API_KEY` is optional. When it is blank, the product remains fully usable and task extraction can run locally. When configured, only explicit summary and revision-task actions send the current asset's feedback text to `gpt-4o-mini`; file bytes, passwords, API keys, and authentication tokens are never included. Responses use `store=False`, capped output tokens, a 10-second timeout, at most one SDK retry, a 30-second cooldown, and a five-request hourly user allowance. Failed summaries are shown as unavailable and are never replaced by text presented as AI-generated.

Do not place the key in source code, templates, browser JavaScript, build arguments, screenshots, or logs. Rotate it immediately if it is ever exposed.

## Final external checks before inviting beta users

1. Verify migrations and rollback on a staging database.
2. Confirm HTTPS cookies, allowed hosts, and origin checks on the real domain.
3. Upload and retrieve a preview as its owner; confirm a different workspace receives 404.
4. Create a client link; confirm the old link stops working after generating a replacement.
5. Approve a test design, run cleanup with an expired timestamp, and confirm only the preview is removed.
6. Restore the database from backup once before launch.
7. Trigger an application error and confirm the monitoring alert contains an error ID but no credentials or review tokens.
