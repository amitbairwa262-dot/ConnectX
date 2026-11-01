from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db, SessionLocal
from app import models, schemas
from app.auth.dependencies import get_current_user
from app.auth.utils import decode_access_token
from app.messages.connection_manager import manager
from app.messages.serializers import message_to_out

router = APIRouter(tags=["Messages"])


def _ensure_member(db: Session, chat_id: int, user_id: int) -> models.Chat:
    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    is_member = (
        db.query(models.ChatMember)
        .filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == user_id)
        .first()
    )
    if not is_member:
        raise HTTPException(status_code=403, detail="Aap is chat ke member nahi ho")
    return chat


def _get_message_for_member(db: Session, message_id: int, user_id: int) -> models.Message:
    message = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender), selectinload(models.Message.reactions))
        .filter(models.Message.id == message_id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message nahi mila")
    _ensure_member(db, message.chat_id, user_id)
    return message


async def _broadcast_update(message: models.Message, exclude_user_id: int):
    """Tell everyone else in the chat that a message changed (edit/reaction/pin/delete)."""
    out = message_to_out(message)
    await manager.broadcast(
        message.chat_id,
        {"event": "message_updated", "message": out.model_dump(mode="json")},
        exclude_user_id=exclude_user_id,
    )
    return out


# ------------------------------------------------------------------ send / list

@router.post("/api/chats/{chat_id}/messages", response_model=schemas.MessageOut)
async def send_message(
    chat_id: int,
    payload: schemas.SendMessageRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member(db, chat_id, current_user.id)

    try:
        msg_type = models.MessageType(payload.message_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message_type")

    reply_to_id = None
    if payload.reply_to_id:
        parent = (
            db.query(models.Message)
            .filter(models.Message.id == payload.reply_to_id, models.Message.chat_id == chat_id)
            .first()
        )
        if not parent:
            raise HTTPException(status_code=400, detail="Jis message ka reply de rahe ho wo is chat me nahi mila")
        reply_to_id = parent.id

    message = models.Message(
        chat_id=chat_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type=msg_type,
        reply_to_id=reply_to_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    message_out = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender), selectinload(models.Message.reactions))
        .filter(models.Message.id == message.id)
        .first()
    )
    result = message_to_out(message_out)

    # push to everyone else connected to this chat in real time
    await manager.broadcast(
        chat_id, {"event": "new_message", "message": result.model_dump(mode="json")},
        exclude_user_id=current_user.id,
    )

    return result


@router.get("/api/chats/{chat_id}/messages", response_model=List[schemas.MessageOut])
def get_messages(
    chat_id: int,
    limit: int = Query(50, ge=1, le=200),
    before_id: int = Query(None, description="Isse pehle ke messages laane ke liye (pagination)"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member(db, chat_id, current_user.id)

    hidden_for_me = select(models.MessageHidden.message_id).where(
        models.MessageHidden.user_id == current_user.id
    )
    query = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender), selectinload(models.Message.reactions))
        .filter(models.Message.chat_id == chat_id, ~models.Message.id.in_(hidden_for_me))
    )
    if before_id:
        query = query.filter(models.Message.id < before_id)

    messages = query.order_by(models.Message.id.desc()).limit(limit).all()
    return [message_to_out(m) for m in reversed(messages)]  # oldest first


# ------------------------------------------------------------------ starred (per user)

@router.get("/api/messages/starred", response_model=List[schemas.MessageOut])
def starred_messages(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    starred_ids = select(models.MessageStar.message_id).where(models.MessageStar.user_id == current_user.id)
    my_chats = select(models.ChatMember.chat_id).where(models.ChatMember.user_id == current_user.id)
    hidden_for_me = select(models.MessageHidden.message_id).where(models.MessageHidden.user_id == current_user.id)
    messages = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender), selectinload(models.Message.reactions))
        .filter(
            models.Message.id.in_(starred_ids),
            models.Message.chat_id.in_(my_chats),
            ~models.Message.id.in_(hidden_for_me),
            models.Message.is_deleted.isnot(True),
        )
        .order_by(models.Message.id.desc())
        .limit(200)
        .all()
    )
    return [message_to_out(m) for m in messages]


# ------------------------------------------------------------------ seen

@router.put("/api/messages/{message_id}/seen", response_model=schemas.MessageOut)
def mark_seen(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = _get_message_for_member(db, message_id, current_user.id)

    if message.sender_id != current_user.id:
        message.is_seen = True
        db.commit()
        db.refresh(message)

    return message_to_out(message)


# ------------------------------------------------------------------ edit / delete

@router.put("/api/messages/{message_id}", response_model=schemas.MessageOut)
async def edit_message(
    message_id: int,
    payload: schemas.EditMessageRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = _get_message_for_member(db, message_id, current_user.id)
    if message.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sirf apna message edit kar sakte ho")
    if message.is_deleted:
        raise HTTPException(status_code=400, detail="Delete hua message edit nahi ho sakta")
    if message.message_type != models.MessageType.text:
        raise HTTPException(status_code=400, detail="Sirf text message edit ho sakta hai")

    message.content = payload.content
    message.edited_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    return await _broadcast_update(message, current_user.id)


@router.delete("/api/messages/{message_id}")
async def delete_message(
    message_id: int,
    for_everyone: bool = Query(False),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = _get_message_for_member(db, message_id, current_user.id)

    if for_everyone:
        if message.sender_id != current_user.id:
            raise HTTPException(status_code=403, detail="Sirf apna message sabke liye delete kar sakte ho")
        if not message.is_deleted:
            message.is_deleted = True
            message.is_pinned = False
            message.content = None
            db.commit()
            db.refresh(message)
        out = await _broadcast_update(message, current_user.id)
        return out.model_dump(mode="json")

    # delete for me: hide it only for this user
    already = (
        db.query(models.MessageHidden)
        .filter(models.MessageHidden.message_id == message_id, models.MessageHidden.user_id == current_user.id)
        .first()
    )
    if not already:
        db.add(models.MessageHidden(message_id=message_id, user_id=current_user.id))
        db.commit()
    return {"deleted_for_me": True, "id": message_id}


# ------------------------------------------------------------------ reactions / star / pin

@router.post("/api/messages/{message_id}/reactions", response_model=schemas.MessageOut)
async def react_to_message(
    message_id: int,
    payload: schemas.ReactRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """React with an emoji. Same emoji again removes it; a different emoji replaces it."""
    message = _get_message_for_member(db, message_id, current_user.id)
    if message.is_deleted:
        raise HTTPException(status_code=400, detail="Delete hue message pe reaction nahi de sakte")

    existing = (
        db.query(models.MessageReaction)
        .filter(models.MessageReaction.message_id == message_id, models.MessageReaction.user_id == current_user.id)
        .first()
    )
    if existing and existing.emoji == payload.emoji:
        db.delete(existing)
    elif existing:
        existing.emoji = payload.emoji
    else:
        db.add(models.MessageReaction(message_id=message_id, user_id=current_user.id, emoji=payload.emoji))
    db.commit()
    db.expire(message)
    return await _broadcast_update(message, current_user.id)


@router.post("/api/messages/{message_id}/star")
def toggle_star(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_message_for_member(db, message_id, current_user.id)
    existing = (
        db.query(models.MessageStar)
        .filter(models.MessageStar.message_id == message_id, models.MessageStar.user_id == current_user.id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"starred": False}
    db.add(models.MessageStar(message_id=message_id, user_id=current_user.id))
    db.commit()
    return {"starred": True}


@router.put("/api/messages/{message_id}/pin", response_model=schemas.MessageOut)
async def pin_message(
    message_id: int,
    payload: schemas.PinRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = _get_message_for_member(db, message_id, current_user.id)
    if message.is_deleted:
        raise HTTPException(status_code=400, detail="Delete hua message pin nahi ho sakta")
    message.is_pinned = payload.pinned
    db.commit()
    db.refresh(message)
    return await _broadcast_update(message, current_user.id)


# ------------------------------------------------------------------ websocket

@router.websocket("/ws/chats/{chat_id}")
async def chat_websocket(websocket: WebSocket, chat_id: int, token: str = Query(...)):
    """
    Real-time chat connection.
    Connect from the frontend like:
        new WebSocket(`ws://127.0.0.1:8000/ws/chats/${chatId}?token=${accessToken}`)

    Events pushed to the client: new_message, message_updated, typing
    """
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=4401)  # custom code: unauthorized
        return

    user_id = int(payload.get("sub"))

    db = SessionLocal()
    try:
        chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
        if not chat:
            await websocket.close(code=4404)
            return
        is_member = (
            db.query(models.ChatMember)
            .filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == user_id)
            .first()
        )
        if not is_member:
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    await manager.connect(chat_id, user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("event")

            if event_type == "typing":
                await manager.broadcast(
                    chat_id,
                    {"event": "typing", "user_id": user_id},
                    exclude_user_id=user_id,
                )
            # message sending itself goes through the REST endpoints above,
            # which broadcast automatically — keeps one source of truth in the DB.
    except WebSocketDisconnect:
        manager.disconnect(chat_id, user_id, websocket)
