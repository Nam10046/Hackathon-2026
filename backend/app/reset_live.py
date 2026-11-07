"""Start the live product clean: delete all readings, alerts, statuses and pickups (the Europress analysis tables
used by the cockpit pages 1-5 are NOT touched).   docker compose exec backend python -m app.reset_live"""
from sqlalchemy import delete, text

from app.db import SEED_COMPACTORS, alert_feedback, alerts, compactor_status, compactors, get_engine, init_db, pickups, readings

if __name__ == "__main__":
    init_db()
    with get_engine().begin() as conn:
        for t in (alert_feedback, alerts, pickups, compactor_status, readings):
            n = conn.execute(delete(t)).rowcount
            print(f"deleted {n:>7} rows from {t.name}")
        keep = [c["id"] for c in SEED_COMPACTORS]
        n = conn.execute(delete(compactors).where(compactors.c.id.not_in(keep))).rowcount
        print(f"deleted {n:>7} extra compactors (kept {', '.join(keep)})")
    print("live data is clean - the ESP32 is now the only source")
