import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app import models, schemas
from app.config import settings
from app.auth.dependencies import get_current_user
from app.messages.connection_manager import manager
from app.messages.serializers import message_to_out

router = APIRouter(prefix="/api/chats", tags=["Media"])

MEDIA_RULES = {
    models.MessageType.image: {
        "folder": "images",
        "allowed": {"image/jpeg", "image/png", "image/webp", "image/gif"},
        "max_mb": 10,
    },
    models.MessageType.video: {
        "folder": "videos",
        "allowed": {"video/mp4", "video/quicktime", "video/webm", "video/3gpp"},
        "max_mb": 100,
    },
    models.MessageType.document: {
        "folder": "documents",
        "allowed": {
            "application/pdf",
            "application/zip",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "text/plain",
        },
        "max_mb": 25,
    },
    models.MessageType.voice: {
        "folder": "voice",
        "allowed": {"audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg", "audio/wav"},
        "max_mb": 15,
    },
}


def _ensure_member(db: Session, chat_id: int, user_id: int):
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


@router.post("/{chat_id}/media", response_model=schemas.MessageOut)
async def send_media(
    chat_id: int,
    media_type: str = Form(..., description="image | video | document | voice"),
    caption: str = Form(""),
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member(db, chat_id, current_user.id)

    try:
        msg_type = models.MessageType(media_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="media_type image/video/document/voice me se ek hona chahiye")

    rules = MEDIA_RULES.get(msg_type)
    if not rules:
        raise HTTPException(status_code=400, detail="Ye media type abhi supported nahi hai")

    if file.content_type not in rules["allowed"]:
        raise HTTPException(
            status_code=400,
            detail=f"{media_type} ke liye ye file type allowed nahi: {file.content_type}",
        )

    contents = await file.read()
    max_bytes = rules["max_mb"] * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File {rules['max_mb']}MB se badi nahi honi chahiye")

    ext = os.path.splitext(file.filename or "")[1] or ""
    filename = f"{uuid.uuid4().hex}{ext}"
    folder = os.path.join(settings.UPLOAD_DIR, "chat_media", rules["folder"])
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    file_url = f"/{filepath.replace(os.sep, '/')}"
    # store as "URL|||original filename|||caption" so the frontend can show a nice file name + caption
    content_str = f"{file_url}|||{file.filename or filename}|||{caption}"

    message = models.Message(
        chat_id=chat_id,
        sender_id=current_user.id,
        content=content_str,
        message_type=msg_type,
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

    await manager.broadcast(
        chat_id, {"event": "new_message", "message": result.model_dump(mode="json")},
        exclude_user_id=current_user.id,
    )

    return result
