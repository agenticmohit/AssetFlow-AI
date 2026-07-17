# Make It Pop

### Clear feedback. Faster revisions. Confident approvals.

Make It Pop is a focused project and feedback workspace for freelance designers. It brings design previews, client conversations, revision tasks, versions, and approvals into one calm place—without asking clients to learn another project-management tool.

Designers keep their original working files in the tools and drives they already use. Make It Pop holds the active review conversation around lightweight previews, so creative work can move forward without scattered messages or ambiguous decisions.

## Why Make It Pop

Creative feedback often arrives through a mix of chat messages, email threads, calls, screenshots, and voice notes. Important changes get buried, reviewers lose track of the latest version, and “approved” can still feel unclear.

Make It Pop creates a simple feedback loop:

1. Upload a design preview to a project.
2. Share a private review link with the client.
3. Discuss feedback in a color-coded, threaded conversation.
4. Turn requested changes into a practical revision checklist.
5. Upload the next version and keep the context together.
6. Record a clear approval or complete the design.

## What it includes

- A colorful designer dashboard for projects, active reviews, and approvals
- Project spaces that keep related designs and conversations together
- Client review links that work without requiring a client account
- Threaded comments, replies, role labels, filters, and expressive reactions
- Clear states for review, requested changes, approval, and completion
- Revision checklists generated from real feedback
- On-demand AI summaries that surface themes and next actions
- Version history for active design reviews
- Project and design management with deliberate confirmation for destructive actions
- Responsive light and dark themes across designer and client experiences

## Designed around the freelancer–client relationship

The designer owns the workspace and manages projects, designs, revisions, and delivery progress. Clients receive a focused review surface where they can view the current design, comment, reply, request changes, or approve.

There is no heavy client onboarding and no expectation that Make It Pop replaces the designer’s local folders or cloud drive. Original files stay with the designer; Make It Pop keeps the review process clear while the work is active.

## AI with a purpose

AI features are optional and run only when the designer requests them. They summarize written feedback and help turn it into actionable revision tasks. The goal is to reduce interpretation work—not to replace the designer’s judgment or invent feedback.

## Beta

Make It Pop is currently an early beta focused on the complete freelance design-review workflow. The product is being refined around clarity, speed, client simplicity, and a visually expressive experience for modern creative teams.

## Run locally

Local development requires Python 3.12 or newer.

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
uvicorn assetflow.main:app --reload
```

Open `http://127.0.0.1:8000`.

The local demo account is:

```text
Email: designer@makeitpop.demo
Password: MakeItPop123!
```

An OpenAI API key is optional for local development. Add it to `.env` to enable live AI feedback summaries and task suggestions; the rest of the product works without it.

## Deploy to Railway (SQLite)

The repository ships with a `Dockerfile` and `railway.json`, so Railway builds and runs it without extra configuration files.

1. Create a Railway service from this GitHub repository.
2. Add a **volume** to the service and mount it at `/data`. This is where the SQLite database, uploads, and the auto-generated secret key live; without it, data is lost on every deploy.
3. Under **Settings → Networking**, generate a public domain.
4. Deploy. No environment variables are required for a first launch.

The container configures itself for production:

- `ASSETFLOW_ENVIRONMENT` defaults to `production`.
- The database defaults to `sqlite:////data/assetflow.db` (WAL mode, single worker).
- Uploads default to `/data/uploads`.
- A secret key is generated once and persisted at `/data/.secret_key`.
- Railway's domains (`RAILWAY_PUBLIC_DOMAIN`, `RAILWAY_PRIVATE_DOMAIN`) and the
  `healthcheck.railway.app` probe host are trusted automatically.
- Database migrations run automatically before the server starts.

Optional environment variables to override the defaults:

| Variable | Purpose |
| --- | --- |
| `ASSETFLOW_SECRET_KEY` | Explicit session-signing secret (32+ characters). |
| `ASSETFLOW_ALLOWED_HOSTS` | Extra hostnames, e.g. a custom domain. Railway domains are appended automatically. |
| `OPENAI_API_KEY` | Enables live AI summaries and task suggestions. |
| `ASSETFLOW_DATABASE_URL` / `DATABASE_URL` | Point at Postgres later (`postgres://…` URLs are normalized automatically). |

## Feedback

Make It Pop is being built for designers who want a sharper, friendlier alternative to collecting creative feedback in scattered messages. Product feedback, workflow ideas, and thoughtful bug reports are welcome through GitHub Issues.
