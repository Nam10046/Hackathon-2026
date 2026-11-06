# Plan & judging

## Challenge (Europress Group)
Measure waste weight **at the compactor**, early and cheaply, and build smart decisions on top:
material value · efficient operations · anomaly detection · new data-based services.
Judges want **engineering feasibility AND commercial usefulness** — "go beyond an algorithm".

## Our story for the judges
1. **Problem:** weight is known only after the truck reaches the recycler → no control, wasted trips, surprises.
2. **Solution:** cheap load cell + ESP32 at the compactor → live weight, value, alerts, pickup forecast.
3. **Live demo:** press on the demo scale → number moves in Grafana → add "contamination" → alert appears.
4. **Business:** who pays? (subscription per compactor / % of savings / service for waste companies)
5. **Next steps:** real pilot with Europress compactors.

## Business numbers to prepare (business person)
- [ ] Cost of our sensor kit (load cell + HX711 + ESP32 + box) — aim < €100
- [ ] Cost of one truck trip — how much do we save by avoiding half-empty pickups?
- [ ] Real material prices (cardboard, plastic) → replace placeholders in `backend/app/db.py`
- [ ] Price model: e.g. €X / compactor / month

## Timeline
| When | Goal |
|---|---|
| Kick-off (first 2 h) | Roles filled in README, everyone runs `docker compose --profile sim up` |
| By hour ~4 | First PR merged by each person |
| Middle | Real sensor sending data; improve one AI part; dashboard polish |
| Feature freeze (−6 h) | No new features. Fix bugs, rehearse demo |
| Final 3 h | Slides, **record a backup demo video**, rehearse pitch twice |

## Demo checklist
- [ ] Demo box with load cell works on the venue Wi-Fi (bring a phone hotspot!)
- [ ] Grafana opens on the presentation laptop, time range set
- [ ] One prepared anomaly to show live
- [ ] Backup video in case anything fails
