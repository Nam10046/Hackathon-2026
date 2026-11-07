"""Is the live model still right? Owner: backend / AI person.

Two signals, both from live use (no dataset labels needed):
  1. FEEDBACK  — someone who checked an alert on site marks it CORRECT or FALSE_ALARM -> live precision.
  2. ALERT RATE — share of real lifts the model flags, compared with the share it flagged on the validation
                  months (model.json "validation_alert_rate"). Far higher or lower = the live data changed (drift),
                  a sensor is off, or the customer's routine changed -> check, then retrain.
Endpoints: POST /api/alerts/{id}/feedback · GET /api/models/performance
"""
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, insert, select

from app.ai import ml
from app.db import alert_feedback, alerts, get_engine
from app.auth import key_or_admin, require_admin

router = APIRouter()
MIN_LIFTS = 20          # fewer lifts than this -> too early to judge
MIN_FEEDBACK = 20


class FeedbackIn(BaseModel):
    verdict: Literal["CORRECT", "FALSE_ALARM"]
    decided_by: str
    note: Optional[str] = None


@router.post("/api/alerts/{alert_id}/feedback", dependencies=[Depends(key_or_admin)])
def give_feedback(alert_id: int, body: FeedbackIn):
    with get_engine().begin() as conn:
        if conn.execute(select(alerts.c.id).where(alerts.c.id == alert_id)).first() is None:
            raise HTTPException(404, f"Alert {alert_id} not found")
        conn.execute(insert(alert_feedback).values(alert_id=alert_id, verdict=body.verdict, decided_by=body.decided_by,
                                                   note=body.note, decided_at=datetime.now(timezone.utc)))
    return {"alert_id": alert_id, "verdict": body.verdict}


@router.get("/api/models/performance", dependencies=[Depends(require_admin)])
def performance(days: int = 30):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # expected alert rate per alert type, from the models the live path uses (feed esp32 first)
    expected = {}
    for m in sorted(ml.list_models(), key=lambda m: m.get("feed", "full") != "esp32"):
        if m.get("type") == "lift_classifier":
            expected.setdefault("ml_" + m["family"].lower(), {"model": m["name"], "feed": m.get("feed", "full"),
                                                              "rate": m.get("validation_alert_rate")})
    with get_engine().connect() as conn:
        lifts = conn.execute(select(func.count()).where(alerts.c.type == "emptied", alerts.c.ts >= since)).scalar()
        out = []
        for atype, exp in expected.items():
            n = conn.execute(select(func.count()).where(alerts.c.type == atype, alerts.c.ts >= since)).scalar()
            fb = dict(conn.execute(
                select(alert_feedback.c.verdict, func.count()).join(alerts, alerts.c.id == alert_feedback.c.alert_id)
                .where(alerts.c.type == atype, alerts.c.ts >= since).group_by(alert_feedback.c.verdict)).all())
            correct, wrong = fb.get("CORRECT", 0), fb.get("FALSE_ALARM", 0)
            rate = n / lifts if lifts else None
            precision = correct / (correct + wrong) if correct + wrong else None
            if lifts < MIN_LIFTS:
                status = f"too early to judge (only {lifts} lifts in {days} days)"
            elif exp["rate"] and (rate > 2 * exp["rate"] or rate < 0.5 * exp["rate"]):
                status = (f"CHECK: flags {rate:.0%} of lifts, in testing it flagged {exp['rate']:.0%} "
                          "— the live data may have changed (sensor, routine, season). Review, then retrain.")
            elif precision is not None and correct + wrong >= MIN_FEEDBACK and precision < 0.6:
                status = f"CHECK: only {precision:.0%} of checked alerts were right — retrain or raise the threshold"
            else:
                status = "ok"
            out.append({"alert_type": atype, "model": exp["model"], "feed": exp["feed"], "lifts": lifts, "alerts": n,
                        "alert_rate": round(rate, 3) if rate is not None else None,
                        "expected_alert_rate": exp["rate"], "feedback_correct": correct, "feedback_false_alarm": wrong,
                        "live_precision": round(precision, 3) if precision is not None else None, "status": status})
    return {"days": days, "models": out}
