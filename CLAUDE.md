# fastapi-react: agent instructions

Notes app: FastAPI + stdlib `sqlite3` in `backend/`, Vite + React in `frontend/`. Vite proxies `/api` to the backend.

## Definition of done

A change is done when, in this order:

1. `scripts/smoke.sh` passes, with the dev servers running so the live API check is not skipped.
2. You have used the change in the real app in the browser (see Testing).
3. It is committed on a feature branch and pushed.
4. A PR is open against `main` with a screenshot in the description (see Pull requests).

Do all four without asking for each step. **Never merge.** The user reviews and merges every PR. Never push to `main`.

## Running the app

- Ports are fixed: backend on `8000`, frontend on `5173` (`--strictPort`). If a port is taken, find out what holds it. Do not pick another port.
- Start servers in the background with absolute paths. A `cd` carries over within one Bash call, so relative paths break:
  ```sh
  R=<repo root>
  (cd $R/backend && nohup .venv/bin/fastapi dev main.py --port 8000 > /tmp/be.log 2>&1 &)
  (cd $R/frontend && nohup npx vite --port 5173 --strictPort > /tmp/fe.log 2>&1 &)
  ```
- First-time setup: `cd backend && uv venv && uv pip install -r requirements-dev.txt`, then `cd frontend && npm install`.
- When you finish, tell the user what is still running, where the logs are, and how to stop it (`pkill -f "fastapi dev main.py"; pkill -f "vite --port 5173"`).

## Testing

- **Automated:** `scripts/smoke.sh` runs `pytest` (temp DB through `APP_DB`), `vite build`, and a create/list/delete round trip through the proxy on `:5173`. New or changed endpoints get a test in `backend/tests/`.
- **Browser:** use the user's existing Chrome. Follow the global browser rule; never launch a new browser. Do the change through the page itself, then confirm the effect in SQLite or through the API. Close every tab you opened.
- **Report results honestly:** give the actual commands and results. If a step was skipped or failed, say so with the output. Never write just "tested locally".

## Commits

- Work on a feature branch. Make one logical change per commit, with a short summary line and a body that explains *why*.
- Run `git status` before `git add -A`. Never commit `backend/app.db`, `.venv/`, `node_modules/`, `dist/` or `.pytest_cache/`.
- Commit and push only after `scripts/smoke.sh` passes.

## Screenshots

Any PR that touches `frontend/` needs a screenshot. A hook enforces this (see below).

1. Fill the app with realistic data first. An empty list shows nothing.
2. Capture it in the user's Chrome: `chrome-devtools-axi open http://localhost:5173`, then `chrome-devtools-axi screenshot <path>`. Do not resize the user's window.
3. Crop out empty space (`sips -c <h> <w> --cropOffset <y> <x> file.png`), then open the image and check it.
4. **Upload it as a GitHub-native attachment.** There is no API for this, so use the PR page in the user's signed-in Chrome:
   - Open `https://github.com/adrianliu/fastapi-react/pull/<n>`, snapshot, find the `button "Attach files"` in the comment box, and run `chrome-devtools-axi upload @<uid> <png>`.
   - Read the generated `<img ... src="https://github.com/user-attachments/assets/...">` from the comment `textarea` with `chrome-devtools-axi eval`.
   - **Clear the textarea and never submit the comment.** Close the tab.
   - Put that `<img>` tag in the PR body with `gh-axi pr edit <n> --body-file`.
   - For a new PR, create it first with a placeholder `<img>` (the hook needs one), then swap in the real attachment URL.
   - User-attachment URLs return 404 to logged-out clients. Check that the image renders by loading the PR page in Chrome and confirming `img.naturalWidth > 0`, not with `curl`.
5. If the change modifies an existing screen, include both **before** and **after** screenshots.
6. Do not commit PR-only screenshots to the repo. `docs/screenshot.png` exists only for the README.

## Pull requests

Use `gh-axi`. Body template:

```markdown
## Summary
<img width="600" alt="..." src="https://github.com/user-attachments/assets/..." />

What changed and why, as short bullets naming files.

## Testing
- `scripts/smoke.sh`: <result>
- Browser: <what you did in the page and what you saw>

## Run
<commands a reviewer needs>
```

After creating or editing the PR, run `gh-axi pr view <n> --full` and confirm the body is right.

## Enforcement

`.claude/settings.json` registers a `PreToolUse` hook, `.claude/hooks/require-pr-screenshot.sh`. It denies `gh`/`gh-axi pr create|edit` with a `--body`/`--body-file` that has no `![..](..)` or `<img` when the branch changes `frontend/`. Do not bypass it. Add the screenshot instead.
