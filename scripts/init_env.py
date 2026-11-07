#!/usr/bin/env python3
"""Creates or completes .env with strong secrets. Existing values stay, except the known-weak GRAFANA_PASS=admin.
    python scripts/init_env.py
Never prints a secret. If Grafana already ran with the old password, see docs/MULTI_TENANT.md (Upgrade)."""
import pathlib
import secrets
import shutil

root = pathlib.Path(__file__).resolve().parent.parent
env = root / ".env"
if not env.exists():
    shutil.copy(root / ".env.example", env)
text = env.read_text(encoding="utf-8")
values = dict(l.split("=", 1) for l in text.splitlines() if "=" in l and not l.lstrip().startswith("#"))
wanted = {"GRAFANA_PASS": "admin", "INGEST_API_KEY": "", "PLATFORM_ADMIN_PASSWORD": "",     # name -> value that must be replaced
          "DEMO_CUSTOMER1_PASSWORD": "", "DEMO_CUSTOMER2_PASSWORD": ""}
lines, done = text.splitlines(), []
for name, weak in wanted.items():
    if values.get(name, "").strip() not in (weak, ""):
        continue
    new = f"{name}={secrets.token_urlsafe(24)}"
    lines = [new if l.startswith(name + "=") else l for l in lines]
    if new not in lines:
        lines.append(new)
    done.append(name)
env.write_text("\n".join(lines) + "\n", encoding="utf-8")
env.chmod(0o600)
print("set: " + (", ".join(done) or "nothing, all values were already strong") + "  (values are in .env)")
