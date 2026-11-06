# Context for AI assistants (Claude, Copilot, ChatGPT…)

Paste or attach this file when asking an AI for help, so its code fits the team's project.

## Project
- Hackathon 2026 team project. Idea: _TODO one line_.
- Team are beginners: prefer simple, readable code over clever code. Explain non-obvious lines with short comments.

## Stack
- **Backend:** Python 3.11+, FastAPI, Pydantic v2, pytest. Entry: `backend/app/main.py`.
- **AI:** `backend/app/ai/service.py` — function `predict(text: str) -> dict`. Keep this signature.
- **Frontend:** plain HTML + CSS + vanilla JS in `frontend/` (no build step). Calls the API with `fetch`.
- **Run:** `docker compose up --build`. Ports: frontend 8080, backend 8000.

## Rules for generated code
1. Follow `CONTRACT.md` exactly — field names, types, URLs. Do not invent new endpoints without saying so.
2. Only touch the files for the current task. Don't reformat other people's files.
3. Secrets come from environment variables (`os.getenv`), never hard-coded. Add new ones to `.env.example`.
4. Add or update a test in `backend/tests/` for any backend change.
5. New Python packages → add to `backend/requirements.txt` with a version.
