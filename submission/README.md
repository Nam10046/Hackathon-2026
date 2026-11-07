# Submission — Europress "SMART Material Value Engine — Weigh at Source, Create Value"

| # | Deliverable (brief §07) | File |
|---|---|---|
| 1 | Illustrated weighing concept: principle, placement, BOM + cost, installation, calibration, error sources, validation plan | [`01_weighing_concept.md`](01_weighing_concept.md) |
| 2 | Working software demo on synthetic data: setup notes, traceable economics, SMART integration | [`02_software_demo.md`](02_software_demo.md) + the repo + demo video |
| 3 | Customer value and business case: use case, measurable benefit, commercial model, productisation | [`03_business_case.md`](03_business_case.md) |
| — | Every third-party library/service/dataset with licence; assumptions; what remains untested | [`04_licences_and_assumptions.md`](04_licences_and_assumptions.md) |
| — | Model accuracy on unseen months, live-data replay test, monitoring after go-live | [`06_model_accuracy_and_live_data.md`](06_model_accuracy_and_live_data.md) |
| (team) | Questions the judges may ask, with honest answers — **read before the pitch** | [`05_judge_QA.md`](05_judge_QA.md) |

Reproduce the business-case numbers (inside the unzipped Europress engine folder):
```bash
python baselines/business_case.py competition --params ../../submission/business_case_params.yaml --out business_case_out
```
Our output is in [`business_case_out/`](business_case_out/).

Judging weights (brief §06) → where we answer them: weighing concept 25 % → file 1 · customer/business value 25 % →
file 3 · data-driven value & analytics 20 % → file 2 §5–6 + file 3 §3 + file 6 · software workflow & SMART integration 15 % →
file 2 · productisation 10 % → file 3 §5–6 · clarity, uncertainty, limitations 5 % → all files ("what remains unproven").
