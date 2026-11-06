"""AI module. Owner: AI person.

Replace the FAKE logic below with the real model or API call.
KEEP the function name, argument and returned keys — they are in CONTRACT.md.
"""
import os

AI_API_KEY = os.getenv("AI_API_KEY", "")  # read secrets from .env, never hard-code


def predict(text: str) -> dict:
    # ---- FAKE placeholder: simple keyword rule so the whole app works today ----
    positive = any(w in text.lower() for w in ("good", "great", "love", "happy"))
    return {
        "label": "positive" if positive else "neutral",
        "score": 0.9 if positive else 0.5,
        "explanation": "Placeholder rule — replace with the real model.",
        "model": "fake-v0",
    }
    # ---- Real version idea: load model once at import time, call it here ----
