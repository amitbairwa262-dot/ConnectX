# ConnectX — Stay Connected, Always

A full-stack, WhatsApp-style messaging app: **FastAPI + SQLAlchemy + WebSockets** on the backend and a
**single-file vanilla JavaScript** frontend. Real-time chat, media sharing, status/stories, groups &
communities, **WebRTC voice/video calls**, and optional Claude-powered AI features.

> Built as a learning project to practise real-time backend design (auth, WebSockets, WebRTC signaling,
> file uploads, relational modelling). It runs locally; see [Limitations](#known-limitations--roadmap) for what is intentionally simple.

## Features

| Area | What works |
|---|---|
| **Auth** | OTP login with **phone or Gmail**, JWT sessions, 6-box OTP input with resend timer |
| **Chat** | 1-to-1 chat in real time (WebSocket), typing events, read receipts (✓ / ✓✓), date separators, link detection |
| **Message actions** | Reply (quoted), edit, delete for me / for everyone, emoji reactions (double-click = 👍), star, pin, forward, copy |
| **Media** | Photos, videos, documents, **voice messages** (recorded in the browser), location, contact cards |
| **Groups** | Create group, member list with admin roles, description & photo, invite code, leave group |
| **Communities** | Communities with an auto-created *Announcements* group and sub-groups |
| **Status** | Text / photo / video stories that expire after 24 h, with a viewers list |
| **Calls** | 1-to-1 **voice & video calls over WebRTC** (signaling over WebSocket), ringtone, call history with filters and call-back |
| **AI** *(optional)* | Assistant chat in the UI; translate, rewrite, chat summary and reply-suggestion endpoints (Claude API) |
| **Profile & settings** | Profile photo, unique username, contact/group info screen with shared-media stats, dark/light theme + accent colours, app-lock PIN, desktop notifications |

Design reference: [`docs/design-mockup.png`](docs/design-mockup.png).

## Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic v2, python-jose (JWT), Uvicorn, SQLite (PostgreSQL-ready URL)
- **Realtime:** native WebSockets (chat rooms + per-user call signaling), WebRTC for audio/video media
- **Frontend:** HTML + CSS + vanilla JavaScript (no build step)
- **AI:** Anthropic Claude via REST (`httpx`)

## Architecture

```
 ┌────────────────────────────┐        REST (JSON)         ┌───────────────────────────┐
 │  Browser — frontend/       │ ─────────────────────────▶ │  FastAPI  (backend/app)   │
 │  index.html (vanilla JS)   │ ◀───────────────────────── │  routers: auth · users ·  │
 │                            │      WebSocket events      │  chats · messages · media │
 │  WebRTC  ◀──── P2P media ──┼──▶ other browser           │  status · communities ·   │
 └────────────────────────────┘   (signaling via the API)  │  calls · ai               │
                                                           └──────┬──────────┬─────────┘
                                                                  │          │ HTTPS
                                                       SQLAlchemy │          ▼
                                                                  ▼     Claude API (optional)
                                                          SQLite  +  uploads/
```

## Quick start

### 1. Backend

**Windows (PowerShell)**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

**macOS / Linux**
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is now at <http://127.0.0.1:8000> (Swagger UI at `/docs`). The SQLite database and the `uploads/`
folder are created automatically on first start, and missing columns are added by a tiny built-in migration.

### 2. Frontend

Open `frontend/index.html` in Chrome or Edge (double-click it — no server needed).
The backend address is the `API` constant at the top of the `<script>` block (`http://127.0.0.1:8000`).

### 3. Log in

OTP delivery is **not wired to an SMS/e-mail provider** — the code is printed in the backend terminal:

```
[OTP] Sending code 123456 to +919876543210
```

Enter it in the app. To try chat/calls you need two users: open the app in two browser tabs (or a normal and an
incognito window) and log in with two different numbers.

### Optional: AI features

Copy `backend/.env.example` to `backend/.env` and set `ANTHROPIC_API_KEY` (get one at
[console.anthropic.com](https://console.anthropic.com)). Without it everything else works; AI endpoints answer `503`.

## Configuration

Set as environment variables or in `backend/.env` (see [`.env.example`](backend/.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | auto-generated into `.secret_key` | JWT signing key — set your own for any real deployment |
| `DATABASE_URL` | `sqlite:///./connectx.db` | Database (for PostgreSQL also `pip install psycopg2-binary`) |
| `UPLOAD_DIR` | `uploads` | Where media files are stored |
| `ANTHROPIC_API_KEY` | *(empty)* | Enables the AI endpoints |
| `AI_MODEL` | `claude-haiku-4-5-20251001` | Claude model used by the AI endpoints |

## Project structure

```
ConnectX/
├── backend/
│   ├── app/
│   │   ├── main.py            # app setup, CORS, static uploads, router registration
│   │   ├── config.py          # settings (env / .env)
│   │   ├── database.py        # SQLAlchemy engine + session
│   │   ├── models.py          # User, Chat, Message, Status, Community, Call, ...
│   │   ├── schemas.py         # Pydantic request / response models
│   │   ├── migrate.py         # adds new columns to an existing SQLite DB
│   │   ├── auth/ users/ chats/ messages/ status/ communities/ calls/ ai/
│   ├── tools/smoke_test.py    # end-to-end API smoke test
│   ├── requirements.txt
│   └── .env.example
├── frontend/index.html        # the whole UI (HTML + CSS + JS)
└── docs/                      # API reference + design mockup
```

## API

56 endpoints — full table in [`docs/API.md`](docs/API.md), or open `/docs` while the backend runs.

## Testing

With the backend running, an automated smoke test exercises the whole API (auth, chats, messaging actions,
media, status, communities, calls, WebSockets):

```bash
cd backend
python tools/smoke_test.py
```

A manual UI checklist lives in [`docs/TESTING.md`](docs/TESTING.md).

## Known limitations & roadmap

- **OTP is printed to the server console** — plug an SMS/e-mail provider into `send_otp()` in `backend/app/auth/utils.py`.
- **WebRTC uses public STUN only (no TURN server)**, so calls can fail between users behind strict NATs/firewalls.
- SQLite + local-disk uploads: fine for a demo, not for multi-instance deployment.
- CORS is open (`*`) for local development — restrict it before deploying.
- Message notifications are delivered for the chat that is currently open; incoming-call alerts always work.
- App-lock PIN, read-receipt and sound settings are stored in the browser only.
- Not built yet: QR-code scanning, block/report, disappearing messages, group video calls, end-to-end encryption.
- Test coverage is an end-to-end smoke script (no unit tests / CI yet).

## License

[MIT](LICENSE) © Amit Kumar Bairwa
