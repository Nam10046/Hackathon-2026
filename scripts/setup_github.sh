#!/usr/bin/env bash
# One-time: create the GitHub repo and push this code. Run from the repo root.
# Needs GitHub CLI: https://cli.github.com  →  gh auth login
set -euo pipefail

REPO_NAME="${1:-hackathon-2026}"

git init -b main
git add .
git commit -m "Initial project skeleton"

gh repo create "$REPO_NAME" --private --source=. --push

# Labels for the issue board
for l in firmware nodered backend ai grafana pitch bug task; do
  gh label create "$l" --force >/dev/null
done

echo "Done. Next: Settings → Collaborators → invite teammates."
echo "Then: Settings → Branches → protect 'main' (require PR + CI passing)."
