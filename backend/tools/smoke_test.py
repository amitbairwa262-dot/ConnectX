#!/usr/bin/env python3
"""
ConnectX end-to-end smoke test.

Start the backend first, then (from the `backend` folder, in a 2nd terminal):

    python tools/smoke_test.py                 # Windows: .\\venv\\Scripts\\python.exe tools\\smoke_test.py
    python tools/smoke_test.py --manual-otp    # type OTPs yourself instead of reading them from the DB

What it does: logs in 3 throw-away users (2 by phone, 1 by Gmail), then exercises auth, profile, chats,
groups, messaging (reply / edit / delete / reactions / star / pin / seen), media upload, status,
communities, calls, WebSockets and AI access rules, printing PASS / FAIL / SKIP for every check.

Notes
  * It creates a few test users + chats in the database (names start with "Smoke"). Delete connectx.db
    (with the server stopped) if you want a clean slate afterwards.
  * OTPs are read straight from the SQLite file (table `otps`), so run it on the machine that hosts the DB.
  * Needs `httpx` (already in requirements.txt) and, for the WebSocket checks, `websockets`
    (installed with uvicorn[standard]).
"""
import argparse
import base64
import json
import os
import sqlite3
import sys
import time

import warnings

import httpx

warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

parser = argparse.ArgumentParser(description="ConnectX smoke test")
parser.add_argument("--base", default="http://127.0.0.1:8000", help="backend URL")
parser.add_argument("--db", default="connectx.db", help="path to the SQLite file (used to read OTPs)")
parser.add_argument("--manual-otp", action="store_true", help="ask for OTPs instead of reading the DB")
args = parser.parse_args()

BASE = args.base.rstrip("/")
client = httpx.Client(base_url=BASE, timeout=20, limits=httpx.Limits(max_keepalive_connections=0))

# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

try:
    from websockets.sync.client import connect as ws_connect
    HAVE_WS = True
except Exception:  # noqa: BLE001
    ws_connect = None
    HAVE_WS = False

TS = int(time.time())
S = {}  # shared state between checks


class Skip(Exception):
    pass


rows = []


def run(name, fn):
    try:
        detail = fn()
        status = "PASS"
    except Skip as e:
        status, detail = "SKIP", str(e)
    except AssertionError as e:
        status, detail = "FAIL", str(e)
    except Exception as e:  # noqa: BLE001
        status, detail = "FAIL", f"{type(e).__name__}: {e}"
    rows.append((status, name, detail or ""))
    print(f"[{status}] {name}" + (f"  —  {detail}" if detail else ""), flush=True)


def need(*keys):
    missing = [k for k in keys if k not in S]
    if missing:
        raise Skip("pehle wala step fail hua, isliye skip (" + ", ".join(missing) + ")")


def call(method, path, token=None, expect=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.request(method, path, headers=headers, **kw)
    if expect is not None:
        allowed = tuple(expect) if isinstance(expect, (tuple, list, set)) else (expect,)
        assert r.status_code in allowed, f"{method} {path} -> {r.status_code} (expected {allowed}): {r.text[:250]}"
    return r


def get_otp(identifier):
    if not args.manual_otp and os.path.exists(args.db):
        try:
            con = sqlite3.connect(args.db)
            row = con.execute(
                "SELECT code FROM otps WHERE identifier=? ORDER BY id DESC LIMIT 1", (identifier,)
            ).fetchone()
            con.close()
            if row:
                return row[0]
        except Exception:  # noqa: BLE001
            pass
    return input(f"   OTP for {identifier} (server terminal me dekho): ").strip()


def login(body):
    call("POST", "/api/auth/send-otp", json=body, expect=200)
    ident = body.get("phone") or body["email"].lower()
    code = get_otp(ident)
    r = call("POST", "/api/auth/verify-otp", json={**body, "code": code}, expect=200).json()
    return {"token": r["access_token"], "id": r["user"]["id"], "new": r["is_new_user"], "ident": ident}


def A(): return S["A"]
def B(): return S["B"]
def C(): return S["C"]
def tok(u): return S[u]["token"]


def ws_url(path):
    return BASE.replace("http", "ws", 1) + path


def ws_recv(ws, want, timeout=6):
    end = time.time() + timeout
    seen = []
    while time.time() < end:
        try:
            msg = ws.recv(timeout=max(0.2, end - time.time()))
        except TimeoutError:
            break
        data = json.loads(msg)
        if data.get("event") == want:
            return data
        seen.append(data.get("event"))
    raise AssertionError(f"'{want}' event {timeout}s me nahi aaya (mile: {seen})")


def msgs(user, cid, **params):
    return call("GET", f"/api/chats/{cid}/messages", tok(user), params=params, expect=200).json()


def find(lst, mid):
    return next((m for m in lst if m["id"] == mid), None)


def send(user, cid, content, **extra):
    return call("POST", f"/api/chats/{cid}/messages", tok(user),
                json={"content": content, "message_type": "text", **extra}, expect=200).json()


# =========================================================== server / database
def t_server():
    r = call("GET", "/", expect=200)
    return r.json().get("message", "")

def t_openapi():
    paths = call("GET", "/openapi.json", expect=200).json()["paths"]
    return f"{len(paths)} paths"

def t_db():
    if not os.path.exists(args.db):
        raise Skip(f"'{args.db}' yahan nahi mili — script ko backend folder se chalao ya --db do")
    con = sqlite3.connect(args.db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    miss_cols = {"reply_to_id", "is_deleted", "edited_at", "is_pinned"} - cols
    miss_tabs = {"message_reactions", "message_stars", "message_hidden", "statuses", "calls", "communities"} - tables
    assert not miss_cols, f"messages table me columns missing: {sorted(miss_cols)} — Phase 10 backend install nahi hua / server restart karo"
    assert not miss_tabs, f"tables missing: {sorted(miss_tabs)}"
    return "all tables + Phase-10 columns present"

def t_cors():
    r = client.request("OPTIONS", "/api/auth/send-otp", headers={
        "Origin": "null", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200, f"preflight -> {r.status_code}"
    assert "access-control-allow-origin" in r.headers, "CORS header missing (file:// frontend block ho jayega)"


# =========================================================== auth
def t_unauth():
    r = call("GET", "/api/auth/me")
    assert r.status_code in (401, 403), f"token ke bina {r.status_code} mila"
    r = call("GET", "/api/auth/me", "garbage.token.value")
    assert r.status_code == 401, f"galat token pe {r.status_code} mila"

def t_login_a():
    phone = f"+9199{TS % 100000000:08d}"
    call("POST", "/api/auth/send-otp", json={"phone": phone}, expect=200)
    code = get_otp(phone)
    wrong = "000000" if code != "000000" else "111111"
    call("POST", "/api/auth/verify-otp", json={"phone": phone, "code": wrong}, expect=400)
    r = call("POST", "/api/auth/verify-otp", json={"phone": phone, "code": code}, expect=200).json()
    S["A"] = {"token": r["access_token"], "id": r["user"]["id"], "ident": phone}
    assert r["is_new_user"] is True
    # an OTP must not be reusable
    call("POST", "/api/auth/verify-otp", json={"phone": phone, "code": code}, expect=400)
    return f"user id {r['user']['id']} (wrong + reused OTP rejected)"

def t_login_b():
    S["B"] = login({"phone": f"+9198{TS % 100000000:08d}"})
    return f"user id {S['B']['id']}"

def t_login_c_email():
    S["C"] = login({"email": f"smoke.c.{TS}@example.com"})
    return f"user id {S['C']['id']} (Gmail/email OTP)"

def t_me():
    need("A")
    r = call("GET", "/api/auth/me", tok("A"), expect=200).json()
    assert r["id"] == A()["id"] and r["phone"] == A()["ident"]


# =========================================================== users / profile
def t_profile():
    need("A", "B")
    r = call("PUT", "/api/users/profile", tok("A"), json={"name": "Smoke A", "about": "testing"}, expect=200).json()
    assert r["name"] == "Smoke A" and r["about"] == "testing"
    call("PUT", "/api/users/profile", tok("B"), json={"name": "Smoke B"}, expect=200)

def t_username():
    need("A", "B")
    uname = f"smk{TS % 1000000}"
    assert call("GET", "/api/users/check-username", params={"username": uname}, expect=200).json()["available"] is True
    r = call("PUT", "/api/users/username", tok("A"), json={"username": uname}, expect=200).json()
    assert r["username"] == uname
    assert call("GET", "/api/users/check-username", params={"username": uname}, expect=200).json()["available"] is False
    call("PUT", "/api/users/username", tok("B"), json={"username": uname}, expect=400)   # already taken
    call("PUT", "/api/users/username", tok("B"), json={"username": "a!"}, expect=422)    # invalid
    S["uname"] = uname
    return uname

def t_search_and_get():
    need("A", "B")
    res = call("GET", "/api/users/search", tok("A"), params={"q": "Smoke"}, expect=200).json()
    assert any(u["id"] == B()["id"] for u in res), "search me user B nahi mila"
    assert all(u["id"] != A()["id"] for u in res), "search me khud ka user aa gaya"
    u = call("GET", f"/api/users/{B()['id']}", tok("A"), expect=200).json()
    assert u["phone"] == B()["ident"]
    call("GET", "/api/users/99999999", tok("A"), expect=404)

def t_profile_photo():
    need("A")
    r = call("POST", "/api/users/profile-photo", tok("A"), files={"file": ("a.png", PNG, "image/png")}, expect=200).json()
    url = r["profile_image"]
    assert url and url.startswith("/uploads/"), f"profile_image={url}"
    g = client.get(url)
    assert g.status_code == 200 and g.content[:8] == PNG[:8], f"photo serve nahi hui ({g.status_code})"
    call("POST", "/api/users/profile-photo", tok("A"), files={"file": ("a.txt", b"hi", "text/plain")}, expect=400)
    return url


# =========================================================== private chat + messaging
def t_private_chat():
    need("A", "B")
    r = call("POST", "/api/chats/private", tok("A"), json={"user_id": B()["id"]}, expect=200).json()
    assert r["type"] == "private" and len(r["members"]) == 2
    S["chat"] = r["id"]
    again = call("POST", "/api/chats/private", tok("B"), json={"user_id": A()["id"]}, expect=200).json()
    assert again["id"] == r["id"], "same pair ke liye naya chat ban gaya"
    call("POST", "/api/chats/private", tok("A"), json={"user_id": A()["id"]}, expect=400)
    lst = call("GET", "/api/chats", tok("A"), expect=200).json()
    assert any(c["id"] == r["id"] for c in lst)
    call("GET", f"/api/chats/{r['id']}", tok("C"), expect=403)
    return f"chat {r['id']}"

def t_send_and_list():
    need("chat")
    cid = S["chat"]
    m = send("A", cid, "hello from A")
    assert m["content"] == "hello from A" and m["sender_id"] == A()["id"]
    assert m["is_deleted"] in (False, None) and m["reactions"] == [] and m["reply"] is None
    S["m1"] = m["id"]
    lst = msgs("B", cid)
    assert find(lst, m["id"]), "B ko message list me nahi dikha"
    call("GET", f"/api/chats/{cid}/messages", tok("C"), expect=403)
    call("POST", f"/api/chats/{cid}/messages", tok("C"), json={"content": "x"}, expect=403)
    call("POST", f"/api/chats/{cid}/messages", tok("A"), json={"content": "   "}, expect=422)
    call("POST", f"/api/chats/{cid}/messages", tok("A"), json={"content": "x", "message_type": "bogus"}, expect=400)

def t_pagination():
    need("chat", "m1")
    cid = S["chat"]
    send("A", cid, "p2"); send("A", cid, "p3")
    assert len(msgs("A", cid, limit=2)) == 2
    all_ids = [m["id"] for m in msgs("A", cid, limit=50)]
    older = msgs("A", cid, before_id=all_ids[-1], limit=50)
    assert all(m["id"] < all_ids[-1] for m in older)
    call("GET", f"/api/chats/{cid}/messages", tok("A"), params={"limit": 0}, expect=422)

def t_reply():
    need("chat", "m1")
    cid, m1 = S["chat"], S["m1"]
    r = send("B", cid, "reply from B", reply_to_id=m1)
    assert r["reply_to_id"] == m1 and r["reply"] and r["reply"]["content"] == "hello from A", f"reply preview: {r['reply']}"
    S["m_reply"] = r["id"]
    call("POST", f"/api/chats/{cid}/messages", tok("B"), json={"content": "x", "reply_to_id": 99999999}, expect=400)

def t_edit():
    need("chat", "m1", "m_reply")
    cid, m1 = S["chat"], S["m1"]
    r = call("PUT", f"/api/messages/{m1}", tok("A"), json={"content": "hello (edited)"}, expect=200).json()
    assert r["content"] == "hello (edited)" and r["edited_at"], "edited_at set nahi hua"
    call("PUT", f"/api/messages/{m1}", tok("B"), json={"content": "hack"}, expect=403)
    call("PUT", f"/api/messages/{m1}", tok("A"), json={"content": "  "}, expect=422)
    reply = find(msgs("B", cid), S["m_reply"])
    assert reply["reply"]["content"] == "hello (edited)", "reply preview naye edited text se update nahi hua"

def t_reactions():
    need("chat", "m1")
    cid, m1 = S["chat"], S["m1"]
    r = call("POST", f"/api/messages/{m1}/reactions", tok("B"), json={"emoji": "👍"}, expect=200).json()
    assert [(x["user_id"], x["emoji"]) for x in r["reactions"]] == [(B()["id"], "👍")]
    r = call("POST", f"/api/messages/{m1}/reactions", tok("B"), json={"emoji": "👍"}, expect=200).json()
    assert r["reactions"] == [], "same emoji dobara dene par reaction hata nahi"
    call("POST", f"/api/messages/{m1}/reactions", tok("B"), json={"emoji": "👍"}, expect=200)
    r = call("POST", f"/api/messages/{m1}/reactions", tok("B"), json={"emoji": "❤️"}, expect=200).json()
    assert [x["emoji"] for x in r["reactions"]] == ["❤️"], "alag emoji se purana replace nahi hua"
    call("POST", f"/api/messages/{m1}/reactions", tok("A"), json={"emoji": "😂"}, expect=200)
    seen_by_a = find(msgs("A", cid), m1)
    assert len(seen_by_a["reactions"]) == 2, "A ko dono reactions nahi dikhe"
    call("POST", f"/api/messages/{m1}/reactions", tok("C"), json={"emoji": "👍"}, expect=403)
    call("POST", f"/api/messages/{m1}/reactions", tok("B"), json={"emoji": ""}, expect=422)

def t_star():
    need("m1")
    m1 = S["m1"]
    assert call("POST", f"/api/messages/{m1}/star", tok("A"), expect=200).json()["starred"] is True
    assert any(m["id"] == m1 for m in call("GET", "/api/messages/starred", tok("A"), expect=200).json())
    assert not any(m["id"] == m1 for m in call("GET", "/api/messages/starred", tok("B"), expect=200).json()), "star sirf apne liye hona chahiye"
    assert call("POST", f"/api/messages/{m1}/star", tok("A"), expect=200).json()["starred"] is False

def t_pin():
    need("chat", "m1")
    cid, m1 = S["chat"], S["m1"]
    r = call("PUT", f"/api/messages/{m1}/pin", tok("B"), json={"pinned": True}, expect=200).json()
    assert r["is_pinned"] is True
    assert find(msgs("A", cid), m1)["is_pinned"] is True
    call("PUT", f"/api/messages/{m1}/pin", tok("B"), json={"pinned": False}, expect=200)

def t_seen():
    need("chat", "m1")
    cid, m1 = S["chat"], S["m1"]
    assert find(msgs("A", cid), m1)["is_seen"] is False
    assert call("PUT", f"/api/messages/{m1}/seen", tok("B"), expect=200).json()["is_seen"] is True
    assert find(msgs("A", cid), m1)["is_seen"] is True, "A ko ✓✓ (seen) nahi dikha"

def t_delete_for_me():
    need("chat")
    cid = S["chat"]
    m = send("A", cid, "delete-for-me test")
    r = call("DELETE", f"/api/messages/{m['id']}", tok("B"), params={"for_everyone": "false"}, expect=200).json()
    assert r.get("deleted_for_me") is True
    assert find(msgs("B", cid), m["id"]) is None, "B ke liye hide nahi hua"
    assert find(msgs("A", cid), m["id"]) is not None, "A ke liye bhi gayab ho gaya (sirf B ke liye hona chahiye)"

def t_delete_for_everyone():
    need("chat")
    cid = S["chat"]
    m = send("A", cid, "secret text")
    call("DELETE", f"/api/messages/{m['id']}", tok("B"), params={"for_everyone": "true"}, expect=403)
    r = call("DELETE", f"/api/messages/{m['id']}", tok("A"), params={"for_everyone": "true"}, expect=200).json()
    assert r["is_deleted"] is True and r["content"] is None
    seen_b = find(msgs("B", cid), m["id"])
    assert seen_b and seen_b["is_deleted"] is True and seen_b["content"] is None, "B ko deleted placeholder nahi mila / content leak ho raha hai"
    call("POST", f"/api/messages/{m['id']}/reactions", tok("B"), json={"emoji": "👍"}, expect=400)
    call("PUT", f"/api/messages/{m['id']}/pin", tok("B"), json={"pinned": True}, expect=400)
    call("PUT", f"/api/messages/{m['id']}", tok("A"), json={"content": "again"}, expect=400)


# =========================================================== media
def t_media():
    need("chat")
    cid = S["chat"]
    r = call("POST", f"/api/chats/{cid}/media", tok("A"), data={"media_type": "image", "caption": "tiny"},
             files={"file": ("t.png", PNG, "image/png")}, expect=200).json()
    assert r["message_type"] == "image" and "|||" in r["content"]
    g = client.get(r["content"].split("|||")[0])
    assert g.status_code == 200 and g.content[:8] == PNG[:8], "uploaded image serve nahi hui"
    r = call("POST", f"/api/chats/{cid}/media", tok("A"), data={"media_type": "voice", "caption": ""},
             files={"file": ("v.webm", b"\x1aE\xdf\xa3fake-audio", "audio/webm")}, expect=200).json()
    assert r["message_type"] == "voice"
    r = call("POST", f"/api/chats/{cid}/media", tok("A"), data={"media_type": "document", "caption": ""},
             files={"file": ("d.pdf", b"%PDF-1.4 fake", "application/pdf")}, expect=200).json()
    assert r["message_type"] == "document"
    call("POST", f"/api/chats/{cid}/media", tok("A"), data={"media_type": "image", "caption": ""},
         files={"file": ("x.html", b"<html>", "text/html")}, expect=400)
    call("POST", f"/api/chats/{cid}/media", tok("C"), data={"media_type": "image", "caption": ""},
         files={"file": ("t.png", PNG, "image/png")}, expect=403)
    return "image + voice + document ok, bad type rejected"

def t_forward_media():
    need("chat")
    cid = S["chat"]
    media = [m for m in msgs("A", cid) if m["message_type"] == "image"]
    assert media, "image message nahi mila"
    fwd = call("POST", f"/api/chats/{cid}/messages", tok("A"),
               json={"content": media[-1]["content"], "message_type": "image"}, expect=200).json()
    assert fwd["message_type"] == "image" and fwd["content"] == media[-1]["content"]


# =========================================================== groups
def t_group():
    need("A", "B", "C")
    g = call("POST", "/api/chats/group", tok("A"),
             json={"name": "Smoke Group", "description": "d", "member_ids": [B()["id"]]}, expect=200).json()
    S["gid"] = g["id"]
    adm = {m["user"]["id"]: m["is_admin"] for m in g["members"]}
    assert adm == {A()["id"]: True, B()["id"]: False}, f"members/admin flags: {adm}"
    u = call("PUT", f"/api/chats/{g['id']}", tok("A"), json={"name": "Smoke Group 2", "description": "new"}, expect=200).json()
    assert u["name"] == "Smoke Group 2"
    call("PUT", f"/api/chats/{g['id']}", tok("B"), json={"name": "hack"}, expect=403)
    call("POST", f"/api/chats/{g['id']}/members", tok("B"), json={"member_ids": [C()["id"]]}, expect=403)
    r = call("POST", f"/api/chats/{g['id']}/members", tok("A"), json={"member_ids": [C()["id"]]}, expect=200).json()
    assert len(r["members"]) == 3
    r = call("PUT", f"/api/chats/{g['id']}/members/{B()['id']}/admin", tok("A"), json={"is_admin": True}, expect=200).json()
    assert {m["user"]["id"]: m["is_admin"] for m in r["members"]}[B()["id"]] is True
    return f"group {g['id']}"

def t_group_invite_leave():
    need("gid")
    gid = S["gid"]
    call("POST", f"/api/chats/{gid}/leave", tok("C"), expect=200)
    assert len(call("GET", f"/api/chats/{gid}", tok("A"), expect=200).json()["members"]) == 2
    call("GET", f"/api/chats/{gid}", tok("C"), expect=403)
    code = call("POST", f"/api/chats/{gid}/invite-link", tok("A"), expect=200).json()["join_code"]
    assert code
    r = call("POST", f"/api/chats/join/{code}", tok("C"), expect=200).json()
    assert any(m["user"]["id"] == C()["id"] for m in r["members"]), "invite code se join nahi hua"
    call("POST", "/api/chats/join/doesnotexist", tok("C"), expect=404)

def t_group_chat_and_photo():
    need("gid")
    gid = S["gid"]
    m = send("C", gid, "hi group")
    assert find(msgs("A", gid), m["id"])["sender"]["id"] == C()["id"]
    r = call("POST", f"/api/chats/{gid}/photo", tok("A"), files={"file": ("g.png", PNG, "image/png")}, expect=200).json()
    assert r["photo"] and r["photo"].startswith("/uploads/")


# =========================================================== status
def t_status():
    need("A", "B")
    s = call("POST", "/api/status/text", tok("A"), json={"content": "smoke status", "background_color": "#17c3a2"}, expect=200).json()
    sid = s["id"]
    assert s["status_type"] == "text" and s["expires_at"]
    assert any(x["id"] == sid for x in call("GET", "/api/status/my", tok("A"), expect=200).json())
    assert any(x["id"] == sid for x in call("GET", "/api/status", tok("B"), expect=200).json()), "B ke feed me A ka status nahi aaya"
    assert not any(x["id"] == sid for x in call("GET", "/api/status", tok("A"), expect=200).json()), "apna status apni feed me aa gaya"
    v = call("GET", f"/api/status/{sid}", tok("B"), expect=200).json()
    assert v["view_count"] == 1 and v["viewed_by_me"] is True
    viewers = call("GET", f"/api/status/{sid}/viewers", tok("A"), expect=200).json()
    assert [x["viewer"]["id"] for x in viewers] == [B()["id"]]
    call("GET", f"/api/status/{sid}/viewers", tok("B"), expect=403)
    call("DELETE", f"/api/status/{sid}", tok("B"), expect=403)
    call("POST", "/api/status/media", tok("A"), data={"status_type": "image", "caption": "c"},
         files={"file": ("s.png", PNG, "image/png")}, expect=200)
    call("DELETE", f"/api/status/{sid}", tok("A"), expect=200)
    call("GET", f"/api/status/{sid}", tok("B"), expect=404)
    return "text + image status, views, owner-only rules"


# =========================================================== communities
def t_communities():
    need("A", "B", "C")
    c = call("POST", "/api/communities", tok("A"), json={"name": "Smoke Community", "description": "d"}, expect=200).json()
    cid = c["id"]
    assert any(g["name"] == "Announcements" for g in c["groups"]), "default Announcements group nahi bana"
    assert any(x["id"] == cid for x in call("GET", "/api/communities", tok("A"), expect=200).json())
    sub = call("POST", f"/api/communities/{cid}/groups", tok("A"),
               json={"name": "Sub Group", "description": "x", "member_ids": []}, expect=200).json()
    assert sub["type"] == "group"
    r = call("POST", f"/api/communities/{cid}/members", tok("A"), json={"member_ids": [B()["id"]]}, expect=200).json()
    assert len(r["members"]) == 2
    call("POST", f"/api/communities/{cid}/members", tok("B"), json={"member_ids": [C()["id"]]}, expect=403)
    call("GET", f"/api/communities/{cid}", tok("B"), expect=200)
    call("GET", f"/api/communities/{cid}", tok("C"), expect=403)
    r = call("DELETE", f"/api/communities/{cid}/members/{B()['id']}", tok("A"), expect=200).json()
    assert len(r["members"]) == 1


# =========================================================== calls
def t_call_offline():
    need("A", "B")
    r = call("POST", "/api/calls", tok("A"), json={"callee_id": B()["id"], "call_type": "voice"}, expect=200).json()
    assert r["status"] == "missed", f"offline callee pe status '{r['status']}' mila"
    call("POST", "/api/calls", tok("A"), json={"callee_id": A()["id"], "call_type": "voice"}, expect=400)
    call("POST", "/api/calls", tok("A"), json={"callee_id": 99999999, "call_type": "voice"}, expect=404)
    call("POST", "/api/calls", tok("A"), json={"callee_id": B()["id"], "call_type": "hologram"}, expect=400)

def t_call_flow():
    need("A", "B")
    if not HAVE_WS:
        raise Skip("'websockets' library nahi mili (pip install websockets)")
    wa = ws_connect(ws_url(f"/api/calls/ws?token={tok('A')}"))
    wb = ws_connect(ws_url(f"/api/calls/ws?token={tok('B')}"))
    try:
        time.sleep(0.4)
        c = call("POST", "/api/calls", tok("A"), json={"callee_id": B()["id"], "call_type": "video"}, expect=200).json()
        assert c["status"] == "ringing"
        ev = ws_recv(wb, "incoming_call")
        assert ev["call"]["id"] == c["id"] and ev["call"]["call_type"] == "video"
        call("POST", f"/api/calls/{c['id']}/answer", tok("A"), expect=403)          # caller cannot answer
        a = call("POST", f"/api/calls/{c['id']}/answer", tok("B"), expect=200).json()
        assert a["status"] == "ongoing"
        ws_recv(wa, "call_answered")
        wa.send(json.dumps({"event": "signal", "target_user_id": B()["id"], "data": {"type": "offer", "sdp": "x"}}))
        sig = ws_recv(wb, "signal")
        assert sig["from_user_id"] == A()["id"] and sig["data"]["type"] == "offer"
        time.sleep(1.2)
        e = call("POST", f"/api/calls/{c['id']}/end", tok("A"), expect=200).json()
        assert e["status"] == "ended" and e["duration_seconds"] is not None and e["duration_seconds"] >= 1
        ws_recv(wb, "call_ended")
        c2 = call("POST", "/api/calls", tok("A"), json={"callee_id": B()["id"], "call_type": "voice"}, expect=200).json()
        ws_recv(wb, "incoming_call")
        d = call("POST", f"/api/calls/{c2['id']}/decline", tok("B"), expect=200).json()
        assert d["status"] == "declined"
        ws_recv(wa, "call_declined")
        hist = call("GET", "/api/calls/history", tok("A"), expect=200).json()
        assert len(hist) >= 3, f"history me {len(hist)} calls"
        return "ring -> answer -> WebRTC signal relay -> end (duration) + decline + history"
    finally:
        wa.close(); wb.close()


# =========================================================== chat websocket
def t_ws_chat():
    need("chat", "m1")
    if not HAVE_WS:
        raise Skip("'websockets' library nahi mili (pip install websockets)")
    cid = S["chat"]
    wa = ws_connect(ws_url(f"/ws/chats/{cid}?token={tok('A')}"))
    wb = ws_connect(ws_url(f"/ws/chats/{cid}?token={tok('B')}"))
    try:
        time.sleep(0.3)
        m = send("A", cid, "ws hello")
        ev = ws_recv(wb, "new_message")
        assert ev["message"]["content"] == "ws hello", "B ko real-time new_message nahi mila"
        call("POST", f"/api/messages/{m['id']}/reactions", tok("B"), json={"emoji": "😂"}, expect=200)
        ev = ws_recv(wa, "message_updated")
        assert any(r["emoji"] == "😂" for r in ev["message"]["reactions"]), "reaction live A tak nahi pahunchi"
        call("PUT", f"/api/messages/{m['id']}", tok("A"), json={"content": "ws hello edited"}, expect=200)
        ev = ws_recv(wb, "message_updated")
        assert ev["message"]["content"] == "ws hello edited" and ev["message"]["edited_at"], "edit live B tak nahi pahunchi"
        wa.send(json.dumps({"event": "typing"}))
        assert ws_recv(wb, "typing")["user_id"] == A()["id"]
    finally:
        wa.close(); wb.close()
    return "new_message, message_updated (reaction + edit), typing"

def t_ws_security():
    need("chat")
    if not HAVE_WS:
        raise Skip("'websockets' library nahi mili")
    cid = S["chat"]
    for label, url in (("galat token", ws_url(f"/ws/chats/{cid}?token=bad.token")),
                       ("non-member", ws_url(f"/ws/chats/{cid}?token={tok('C')}"))):
        accepted = False
        try:
            w = ws_connect(url)
            try:
                w.recv(timeout=2)           # a rejected socket closes straight away
            except Exception:  # noqa: BLE001
                pass
            accepted = getattr(w, "close_code", None) is None
            w.close()
        except Exception:  # noqa: BLE001
            accepted = False                # handshake refused — good
        assert not accepted, f"{label} wala WebSocket accept ho gaya"


# =========================================================== AI (optional)
def t_ai_access():
    need("chat", "C")
    call("GET", f"/api/ai/summarize-chat/{S['chat']}", tok("C"), expect=403)
    call("GET", f"/api/ai/reply-suggestions/{S['chat']}", tok("C"), expect=403)

def t_ai_chat():
    need("A")
    r = call("POST", "/api/ai/chat", tok("A"), json={"message": "Say hello in 3 words"}, expect=(200, 502, 503))
    if r.status_code == 503:
        raise Skip("ANTHROPIC_API_KEY set nahi hai — AI optional hai, baaki app pe asar nahi")
    assert r.status_code == 200, f"AI service error: {r.text[:200]}"
    assert r.json()["reply"].strip(), "AI ne khali reply diya"
    return r.json()["reply"][:60]


# =========================================================== run everything
CHECKS = [
    ("Server reachable", t_server), ("OpenAPI / Swagger", t_openapi), ("Database tables + Phase-10 columns", t_db),
    ("CORS preflight (file:// frontend)", t_cors),
    ("Auth: unauthenticated / bad token blocked", t_unauth), ("Auth: phone OTP login (A) + wrong/reused OTP", t_login_a),
    ("Auth: phone OTP login (B)", t_login_b), ("Auth: Gmail OTP login (C)", t_login_c_email), ("Auth: /me", t_me),
    ("Profile: name + about", t_profile), ("Profile: username (unique, validated)", t_username),
    ("Users: search + get by id", t_search_and_get), ("Profile: photo upload + serve", t_profile_photo),
    ("Chat: private chat create/dedupe/privacy", t_private_chat), ("Messages: send / list / validation / privacy", t_send_and_list),
    ("Messages: pagination", t_pagination), ("Messages: reply (quoted preview)", t_reply), ("Messages: edit", t_edit),
    ("Messages: reactions (add / toggle / replace)", t_reactions), ("Messages: star (per user)", t_star),
    ("Messages: pin", t_pin), ("Messages: seen (✓✓)", t_seen), ("Messages: delete for me", t_delete_for_me),
    ("Messages: delete for everyone", t_delete_for_everyone), ("Media: image / voice / document + validation", t_media),
    ("Media: forward image", t_forward_media),
    ("Groups: create / admin / update / add members", t_group), ("Groups: leave / invite code / join", t_group_invite_leave),
    ("Groups: group chat + photo", t_group_chat_and_photo), ("Status: create / feed / views / delete", t_status),
    ("Communities: create / groups / members / privacy", t_communities),
    ("Calls: offline callee = missed + validation", t_call_offline),
    ("Calls: ring -> answer -> signal -> end + decline + history (WebSocket)", t_call_flow),
    ("WebSocket chat: live message / reaction / edit / typing", t_ws_chat), ("WebSocket: bad token / non-member rejected", t_ws_security),
    ("AI: membership rules", t_ai_access), ("AI: assistant reply (needs ANTHROPIC_API_KEY)", t_ai_chat),
]

if __name__ == "__main__":
    print(f"ConnectX smoke test  ->  {BASE}   (OTP source: {'manual' if args.manual_otp else args.db})\n")
    try:
        call("GET", "/", expect=200)
    except Exception as e:  # noqa: BLE001
        print(f"Backend tak nahi pahunch paya ({e}).\nPehle backend chalao:  uvicorn app.main:app --reload")
        sys.exit(2)
    for name, fn in CHECKS:
        run(name, fn)
    p = sum(1 for r in rows if r[0] == "PASS")
    f = [r for r in rows if r[0] == "FAIL"]
    s = sum(1 for r in rows if r[0] == "SKIP")
    print(f"\n==== RESULT: {p} passed, {len(f)} failed, {s} skipped  (total {len(rows)}) ====")
    if f:
        print("\nFAILED checks (ye lines copy karke bhej do):")
        for _, name, detail in f:
            print(f"  - {name}: {detail}")
    sys.exit(1 if f else 0)
