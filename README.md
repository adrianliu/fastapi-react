# fastapi-react

Minimal notes app: React (Vite) + FastAPI + SQLite.

```
backend/   FastAPI app (main.py), SQLite file created at backend/app.db
frontend/  React app; Vite proxies /api -> http://127.0.0.1:8000
```

## Run

Backend (terminal 1):

```sh
cd backend
uv venv && uv pip install -r requirements.txt   # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/fastapi dev main.py                   # http://127.0.0.1:8000  (docs at /docs)
```

Frontend (terminal 2):

```sh
cd frontend
npm install
npm run dev                                     # http://localhost:5173
```
