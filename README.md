# Hackathon 2026 — Team Project

> **One-line pitch:** _TODO — what problem we solve, for whom._

A working skeleton: **frontend → backend → AI → back to the screen**, already connected.
Everyone replaces their own *fake* part with the real one. Nobody has to "combine everything at the end".

```
frontend/  (HTML/JS, served by nginx)  ──/api──►  backend/ (FastAPI, Python)
                                                     └── app/ai/service.py  ◄── AI person works here
```

## Quick start (run the whole app)

**Option A — Docker (recommended, same for everyone):**
```bash
cp .env.example .env
docker compose up --build
```
Open http://localhost:8080 · API docs: http://localhost:8000/docs

**Option B — without Docker:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Then open `frontend/index.html` directly in the browser (it falls back to `http://localhost:8000`).

**Run tests:**
```bash
cd backend && pytest
```

## Who owns what

| Area | Folder | Owner |
|---|---|---|
| Frontend / UI | `frontend/` | _name_ |
| Backend / API | `backend/app/main.py`, `schemas.py` | _name_ |
| AI / model | `backend/app/ai/` | _name_ |
| Pitch, slides, demo script | `docs/` | _name_ |
| **`main` branch keeper** (reviews & merges PRs) | — | _name_ |

## The 5 team rules

1. **`CONTRACT.md` is law.** Change the API only by PR to `CONTRACT.md` first, and tell the team.
2. **Never push to `main`.** Branch → Pull Request → keeper merges.
3. **Merge small and often** — at least twice a day. Small PRs never break things badly.
4. **`main` must always run.** If you break it, fixing it is everyone's #1 task.
5. **Ask after 30 minutes stuck.** Post in the team chat.

More: [`CONTRIBUTING.md`](CONTRIBUTING.md) (git step by step) · [`CONTRACT.md`](CONTRACT.md) (API) · [`CLAUDE.md`](CLAUDE.md) (context for AI assistants) · [`docs/PLAN.md`](docs/PLAN.md) (timeline & judging).
