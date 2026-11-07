# One-shot job: team audit pipeline (if its outputs are missing) + cockpit tables. Run: docker compose run --rm analytics
FROM python:3.12-slim
WORKDIR /work
COPY analytics/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY analytics ./analytics
CMD ["python", "analytics/run_all.py"]
