from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app import models, schemas
from app.auth.dependencies import get_current_user
from app.ai.client import ask_claude

router = APIRouter(prefix="/api/ai", tags=["AI Features"])


def _ensure_member(db: Session, chat_id: int, user_id: int):
    is_member = (
        db.query(models.ChatMember)
        .filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == user_id)
        .first()
    )
    if not is_member:
        raise HTTPException(status_code=403, detail="Aap is chat ke member nahi ho")


@router.post("/chat", response_model=schemas.AIChatResponse)
async def ai_chat_assistant(
    payload: schemas.AIChatRequest,
    current_user: models.User = Depends(get_current_user),
):
    """ConnectX ke andar ek general-purpose AI assistant — koi bhi sawal pooch sakte ho."""
    reply = await ask_claude(
        system="You are ConnectX's helpful in-app AI assistant. Keep replies concise and friendly.",
        user_message=payload.message,
    )
    return schemas.AIChatResponse(reply=reply)


@router.post("/translate", response_model=schemas.TranslateResponse)
async def translate_text(
    payload: schemas.TranslateRequest,
    current_user: models.User = Depends(get_current_user),
):
    reply = await ask_claude(
        system=(
            f"Translate the user's message into {payload.target_language}. "
            "Reply with ONLY the translated text, nothing else — no notes, no quotes."
        ),
        user_message=payload.text,
        max_tokens=300,
    )
    return schemas.TranslateResponse(translated_text=reply)


@router.post("/rewrite", response_model=schemas.RewriteResponse)
async def rewrite_message(
    payload: schemas.RewriteRequest,
    current_user: models.User = Depends(get_current_user),
):
    reply = await ask_claude(
        system=(
            f"Rewrite the user's message in a {payload.tone} tone, keeping the same meaning "
            "and roughly the same length. Reply with ONLY the rewritten text, nothing else."
        ),
        user_message=payload.text,
        max_tokens=300,
    )
    return schemas.RewriteResponse(rewritten_text=reply)


@router.get("/summarize-chat/{chat_id}", response_model=schemas.SummaryResponse)
async def summarize_chat(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member(db, chat_id, current_user.id)

    messages = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender))
        .filter(models.Message.chat_id == chat_id, models.Message.message_type == models.MessageType.text, models.Message.is_deleted.isnot(True))
        .order_by(models.Message.id.desc())
        .limit(50)
        .all()
    )
    messages = list(reversed(messages))

    if not messages:
        return schemas.SummaryResponse(summary="Is chat me abhi tak koi text message nahi hai.", message_count=0)

    transcript = "\n".join(f"{m.sender.name or m.sender.phone or m.sender.id}: {m.content}" for m in messages)

    reply = await ask_claude(
        system=(
            "Summarize this chat conversation in 3-5 short bullet points, in Hinglish. "
            "Focus on key topics, decisions, and action items."
        ),
        user_message=transcript,
        max_tokens=400,
    )
    return schemas.SummaryResponse(summary=reply, message_count=len(messages))


@router.get("/reply-suggestions/{chat_id}", response_model=schemas.ReplySuggestionsResponse)
async def reply_suggestions(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member(db, chat_id, current_user.id)

    last_messages = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender))
        .filter(models.Message.chat_id == chat_id, models.Message.message_type == models.MessageType.text, models.Message.is_deleted.isnot(True))
        .order_by(models.Message.id.desc())
        .limit(5)
        .all()
    )
    last_messages = list(reversed(last_messages))

    if not last_messages:
        return schemas.ReplySuggestionsResponse(suggestions=[])

    transcript = "\n".join(
        f"{m.sender.name or m.sender.phone or m.sender.id}: {m.content}" for m in last_messages
    )

    reply = await ask_claude(
        system=(
            "Based on this chat, suggest exactly 3 short, natural quick-reply options for the "
            "last message — one per line, no numbering, no quotes, no extra text."
        ),
        user_message=transcript,
        max_tokens=150,
    )
    suggestions = [line.strip("-• ").strip() for line in reply.split("\n") if line.strip()][:3]
    return schemas.ReplySuggestionsResponse(suggestions=suggestions)
