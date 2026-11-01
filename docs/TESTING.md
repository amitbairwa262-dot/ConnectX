# Testing ConnectX

## 1. Automated API smoke test

Covers auth, profile, chats, groups, messaging (reply / edit / delete / reactions / star / pin / seen), media,
status, communities, calls, WebSockets and AI access rules (~37 checks).

```bash
# terminal 1 — backend
cd backend
python -m uvicorn app.main:app --reload

# terminal 2 — test (same folder, so it can read OTPs from connectx.db)
cd backend
python tools/smoke_test.py            # Windows: .\venv\Scripts\python.exe tools\smoke_test.py
python tools/smoke_test.py --manual-otp   # type the OTPs from the server console yourself
```

Every check prints `PASS`, `FAIL` or `SKIP`; the exit code is non-zero if anything failed.
`SKIP` for the AI check just means no `ANTHROPIC_API_KEY` is configured.
The script creates a few throw-away "Smoke" users in the database.

## 2. Manual UI checklist

Open `frontend/index.html` in **two** browser tabs (or one normal + one incognito) and log in as two different users
(**A** and **B**). Tick each item:

**Login**
- [ ] Phone tab: OTP boxes appear, pasting the 6 digits auto-verifies; wrong OTP shows an error; resend timer counts down
- [ ] Gmail tab works the same way
- [ ] Refreshing the page keeps you logged in

**Home & chat**
- [ ] A starts a chat with B (`+` → search). Messages arrive in B's tab instantly
- [ ] B's home screen shows last-message preview, time and an unread badge; opening the chat clears it
- [ ] Date separators (Today / Yesterday), ✓ becomes ✓✓ after B opens the chat
- [ ] Emoji panel inserts emoji; links in messages are clickable

**Message actions** (use `⌄` next to the time, right-click, or long-press)
- [ ] Reply → quoted preview appears; tapping it jumps to the original
- [ ] Reactions (👍 ❤️ …) show under the bubble on both sides; double-click = 👍; same emoji again removes it
- [ ] Edit own message → shows "edited" on both sides
- [ ] Delete for me → only disappears for you; Delete for everyone → other side shows "This message was deleted" (within ~4 s)
- [ ] Star → ⭐ marker; contact info → *Starred messages* lists it
- [ ] Pin → 📌 banner at the top of the chat
- [ ] Forward to another chat; Copy puts text on the clipboard

**Media**
- [ ] 📎 → Gallery / Camera / Video / Document / Location / Contact each send something
- [ ] Voice message: tap 🎙 to record, tap again to send; the other side can play it
- [ ] Images open full-size when clicked

**Contact / group info**
- [ ] Tap the chat header → contact info with photo, username, phone, shared-media counts, Voice/Video buttons
- [ ] Group: create, member list shows *Admin*, invite code copies, "Invite code se group join karo" works, leave group works

**Status & communities**
- [ ] Post a text and a photo status; B sees it, opens it; A sees B in the viewers list; delete works
- [ ] Create a community → *Announcements* group exists; create a sub-group; message inside it

**Calls**
- [ ] A voice-calls B: B's tab rings (ringtone), accept → timer runs, mute works, end closes on both sides
- [ ] Video call: browser asks for camera/mic permission, **both** tabs show video
- [ ] Decline works; Calls tab shows history; filters (Missed / Incoming / Outgoing) and call-back button work

**Settings**
- [ ] Profile photo upload and username (shows "available / taken") work
- [ ] Light / dark theme + accent colour persist after refresh
- [ ] Privacy: read-receipts toggle; App Lock PIN → refresh asks for the PIN
- [ ] Notifications: test button beeps / shows a desktop notification
- [ ] Storage & Data shows counts; Help → *Server connection check* says the server is running
- [ ] AI Assistant answers (needs `ANTHROPIC_API_KEY`)
