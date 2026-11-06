"""Compactor data simulator. Owner: AI / data person.

Creates realistic readings for C1–C3 so everyone can work before the real sensor is ready.

  1. Backfill: sends N days of history straight to the backend (fast, via HTTP bulk)
  2. Live:     publishes a new reading every few seconds via MQTT -> Node-RED -> backend

Random problems are injected so anomaly detection has something to find:
  spike (big dump), glitch (sensor reads nonsense), contamination (wet / wrong material).

Run:  python simulate.py                 (backfill 7 days + live)
      python simulate.py --no-live       (only history)
      python simulate.py --no-backfill   (only live)
"""
import argparse
import json
import os
import random
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# compactor id -> volume m3, capacity kg, normal density kg/m3, fill speed m3 per hour
COMPACTORS = {
    "C1": {"volume": 8, "capacity": 2000, "density": 300, "rate": 0.17},  # cardboard
    "C2": {"volume": 8, "capacity": 1500, "density": 220, "rate": 0.12},  # plastic
    "C3": {"volume": 8, "capacity": 4000, "density": 450, "rate": 0.25},  # mixed
}


class Compactor:
    def __init__(self, cid, cfg, anomaly_rate):
        self.cid, self.cfg, self.anomaly_rate = cid, cfg, anomaly_rate
        self.fill_m3 = random.uniform(0, cfg["volume"] * 0.5)
        self.extra_kg = 0.0          # dumped heavy stuff (spike)
        self.density_factor = 1.0    # >1 = contaminated cycle

    def step(self, ts: datetime, hours: float) -> dict:
        cfg = self.cfg
        busy = 1.5 if 7 <= ts.hour <= 18 else 0.3          # more waste during work hours
        self.fill_m3 += cfg["rate"] * busy * hours * random.uniform(0.6, 1.4)

        # random problems
        r = random.random()
        if r < self.anomaly_rate:
            self.extra_kg += random.uniform(250, 500)        # spike
        elif r < self.anomaly_rate * 1.5 and self.density_factor == 1.0:
            self.density_factor = random.uniform(1.6, 2.0)   # contamination until emptied

        weight = self.fill_m3 * cfg["density"] * self.density_factor + self.extra_kg
        fill_pct = min(self.fill_m3 / cfg["volume"] * 100, 100)

        # truck empties it when ~90% full (by volume or weight)
        if fill_pct >= 90 or weight >= cfg["capacity"] * 0.9:
            self.fill_m3, self.extra_kg, self.density_factor = 0.0, 0.0, 1.0
            weight, fill_pct = 0.0, 0.0

        reading_w = weight + random.gauss(0, 5)              # sensor noise
        if random.random() < self.anomaly_rate * 0.5:
            reading_w = random.choice([-400, cfg["capacity"] * 2])  # sensor glitch

        return {"compactor_id": self.cid, "weight_kg": round(reading_w, 1),
                "fill_pct": round(fill_pct, 1), "ts": ts.isoformat().replace("+00:00", "Z")}


def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def wait_for_api(api):
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{api}/health", timeout=3)
            return
        except Exception:
            print("waiting for backend…")
            time.sleep(2)
    raise SystemExit("backend not reachable")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default=os.getenv("API_URL", "http://localhost:8000/api"))
    p.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", "localhost"))
    p.add_argument("--days", type=float, default=7)
    p.add_argument("--step-min", type=float, default=15, help="minutes between history readings")
    p.add_argument("--interval", type=float, default=5, help="live: seconds between readings")
    p.add_argument("--speed", type=float, default=30, help="live: fill speed multiplier for demos")
    p.add_argument("--anomaly-rate", type=float, default=0.01)
    p.add_argument("--no-backfill", action="store_true")
    p.add_argument("--no-live", action="store_true")
    args = p.parse_args()

    sims = [Compactor(cid, cfg, args.anomaly_rate) for cid, cfg in COMPACTORS.items()]

    if not args.no_backfill:
        wait_for_api(args.api)
        now = datetime.now(timezone.utc)
        ts = now - timedelta(days=args.days)
        batch = []
        while ts < now:
            batch += [s.step(ts, args.step_min / 60) for s in sims]
            ts += timedelta(minutes=args.step_min)
            if len(batch) >= 300:
                post_json(f"{args.api}/readings/bulk", {"readings": batch})
                batch = []
        if batch:
            post_json(f"{args.api}/readings/bulk", {"readings": batch})
        print(f"backfill done: {args.days} days of history")

    if args.no_live:
        return

    import paho.mqtt.client as mqtt  # only needed for live mode
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.mqtt_host, 1883)
    client.loop_start()
    print(f"live: publishing to mqtt://{args.mqtt_host} every {args.interval}s (Ctrl+C to stop)")
    while True:
        ts = datetime.now(timezone.utc)
        for s in sims:
            reading = s.step(ts, args.interval / 3600 * args.speed)
            client.publish(f"compactor/{s.cid}/reading", json.dumps(reading))
            print(reading)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
