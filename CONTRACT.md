# API Contract

The agreement between frontend, backend and AI. **Code against this file.**
Changing it = a PR that edits this file + a message to the whole team.

Base URL: `/api` (via nginx at http://localhost:8080) or `http://localhost:8000/api` directly.

---

## `GET /api/health`
Check the server is alive.

**Response 200**
```json
{ "status": "ok", "version": "0.1.0" }
```

---

## `POST /api/predict`
Send user input, get the AI result.

**Request**
```json
{ "text": "string, 1–5000 chars" }
```

**Response 200**
```json
{
  "label": "string",
  "score": 0.87,
  "explanation": "string",
  "model": "fake-v0"
}
```
- `score` is between 0 and 1.
- `model` tells which AI version answered (`fake-v0` = placeholder).

**Response 422** — invalid input (empty text, too long). FastAPI returns details automatically.

---

## Data ownership
| Field | Produced by | Used by |
|---|---|---|
| `text` | frontend (user) | AI |
| `label`, `score`, `explanation` | AI (`app/ai/service.py`) | frontend result card |

## Change log
| Date | Change | By |
|---|---|---|
| 2026-11-06 | Initial contract (health, predict) | — |
