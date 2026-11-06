"""Shared API-key check. Writes need X-API-Key when INGEST_API_KEY is set (always set it on Rahti)."""
import os

from fastapi import Header, HTTPException


def require_key(x_api_key: str | None = Header(default=None)):
    expected = os.getenv("INGEST_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Missing or wrong X-API-Key")
