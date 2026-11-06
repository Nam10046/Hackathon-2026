# How to contribute (step by step)

## One-time setup
```bash
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
git config user.name "Your Name"
git config user.email "you@example.com"
```

## Every time you start a task
```bash
git checkout main
git pull                                  # get everyone's latest work
git checkout -b feature/short-name        # e.g. feature/login-page, fix/predict-crash
```

Branch prefixes: `feature/` new stuff · `fix/` bug fix · `docs/` text only.

## While working (commit often)
```bash
git status                                # see what changed
git add .
git commit -m "add result card to UI"     # short, present tense
```

## When the task works (or every few hours)
```bash
git pull origin main                      # bring in others' work FIRST
# fix any conflicts, run the app + tests again
git push -u origin feature/short-name
```
Then on GitHub: **Compare & pull request** → fill the template → ask the keeper to review.

## After your PR is merged
```bash
git checkout main
git pull
git branch -d feature/short-name
```

## Merge conflict? Don't panic
1. `git pull origin main` shows the conflicted files.
2. Open each file, look for `<<<<<<<`, `=======`, `>>>>>>>`.
3. Keep the right code, delete the markers.
4. `git add .` → `git commit` → `git push`.
5. Unsure? Call the person who wrote the other side. Never delete their code blindly.

## Definition of done
- [ ] App starts (`docker compose up` or uvicorn)
- [ ] `pytest` passes
- [ ] Follows `CONTRACT.md`
- [ ] No secrets / API keys in the code (use `.env`)
