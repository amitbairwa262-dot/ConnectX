# API reference

Base URL (local): `http://127.0.0.1:8000` — interactive docs at **`/docs`** (Swagger UI) once the backend is running.

Authentication: send `Authorization: Bearer <access_token>` (obtained from `POST /api/auth/verify-otp`). Endpoints marked **JWT** require it. WebSockets take the token as a `?token=` query parameter.

_This file is generated from the FastAPI routers._

## Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/auth/send-otp` | public | Send otp |
| `POST` | `/api/auth/verify-otp` | public | Verify otp |
| `GET` | `/api/auth/me` | JWT | Get me |

## Users & Profile

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/users/check-username` | public | Check username |
| `PUT` | `/api/users/username` | JWT | Set username |
| `PUT` | `/api/users/profile` | JWT | Update profile |
| `POST` | `/api/users/profile-photo` | JWT | Upload profile photo |
| `GET` | `/api/users/search` | JWT | Search users |
| `GET` | `/api/users/{user_id}` | JWT | Get user by id |

## Chats

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chats/private` | JWT | Create or get private chat |
| `POST` | `/api/chats/group` | JWT | Create group chat |
| `GET` | `/api/chats` | JWT | List my chats |
| `GET` | `/api/chats/{chat_id}` | JWT | Get chat |
| `POST` | `/api/chats/{chat_id}/members` | JWT | Add members |
| `DELETE` | `/api/chats/{chat_id}/members/{user_id}` | JWT | Remove member |
| `PUT` | `/api/chats/{chat_id}` | JWT | Update group info |
| `POST` | `/api/chats/{chat_id}/photo` | JWT | Upload group photo |
| `PUT` | `/api/chats/{chat_id}/members/{user_id}/admin` | JWT | Set member admin |
| `POST` | `/api/chats/{chat_id}/leave` | JWT | Leave group |
| `POST` | `/api/chats/{chat_id}/invite-link` | JWT | Get or create invite link |
| `POST` | `/api/chats/join/{join_code}` | JWT | Join group via code |

## Messages

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chats/{chat_id}/messages` | JWT | Send message |
| `GET` | `/api/chats/{chat_id}/messages` | JWT | Get messages |
| `GET` | `/api/messages/starred` | JWT | Starred messages |
| `PUT` | `/api/messages/{message_id}/seen` | JWT | Mark seen |
| `PUT` | `/api/messages/{message_id}` | JWT | Edit message |
| `DELETE` | `/api/messages/{message_id}` | JWT | Delete message |
| `POST` | `/api/messages/{message_id}/reactions` | JWT | React with an emoji. Same emoji again removes it; a different emoji replaces it |
| `POST` | `/api/messages/{message_id}/star` | JWT | Toggle star |
| `PUT` | `/api/messages/{message_id}/pin` | JWT | Pin message |
| `WS` | `/ws/chats/{chat_id}` | `?token=<JWT>` | Real-time chat connection |

## Media

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chats/{chat_id}/media` | JWT | Send media |

## Status

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/status/text` | JWT | Create text status |
| `POST` | `/api/status/media` | JWT | Create media status |
| `GET` | `/api/status` | JWT | Sabke active (non-expired) statuses — apna khud ka chhodkar |
| `GET` | `/api/status/my` | JWT | My statuses |
| `GET` | `/api/status/{status_id}` | JWT | View status |
| `GET` | `/api/status/{status_id}/viewers` | JWT | Get viewers |
| `DELETE` | `/api/status/{status_id}` | JWT | Delete status |

## Communities

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/communities` | JWT | Create community |
| `GET` | `/api/communities` | JWT | List my communities |
| `GET` | `/api/communities/{community_id}` | JWT | Get community |
| `POST` | `/api/communities/{community_id}/groups` | JWT | Create group under community |
| `POST` | `/api/communities/{community_id}/members` | JWT | Add community members |
| `DELETE` | `/api/communities/{community_id}/members/{user_id}` | JWT | Remove community member |

## Calls

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/calls` | JWT | Start call |
| `POST` | `/api/calls/{call_id}/answer` | JWT | Answer call |
| `POST` | `/api/calls/{call_id}/decline` | JWT | Decline call |
| `POST` | `/api/calls/{call_id}/end` | JWT | End call |
| `GET` | `/api/calls/history` | JWT | Call history |
| `WS` | `/api/calls/ws` | `?token=<JWT>` | Ek user ka ek hi signaling connection — poore app me jahan bhi ho, isi se |

## AI Features

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/ai/chat` | JWT | ConnectX ke andar ek general-purpose AI assistant — koi bhi sawal pooch sakte ho |
| `POST` | `/api/ai/translate` | JWT | Translate text |
| `POST` | `/api/ai/rewrite` | JWT | Rewrite message |
| `GET` | `/api/ai/summarize-chat/{chat_id}` | JWT | Summarize chat |
| `GET` | `/api/ai/reply-suggestions/{chat_id}` | JWT | Reply suggestions |

## WebSocket events

**`/ws/chats/{chat_id}`** (server → client): `new_message`, `message_updated` (edit / reaction / pin / delete), `typing`. Client → server: `{"event": "typing"}`.

**`/api/calls/ws`** (server → client): `incoming_call`, `call_answered`, `call_declined`, `call_ended`, `signal` (WebRTC offer / answer / ICE candidates). Client → server: `{"event": "signal", "target_user_id": <id>, "data": {...}}`.
