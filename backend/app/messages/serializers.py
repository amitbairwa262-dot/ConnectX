from app import models, schemas


def _type_str(t) -> str:
    return t.value if hasattr(t, "value") else str(t)


def message_to_out(msg: models.Message) -> schemas.MessageOut:
    """Turns a Message row into the API shape: hides content of deleted messages
    and attaches a small preview of the message it replies to."""
    out = schemas.MessageOut.model_validate(msg)
    if msg.is_deleted:
        out.content = None

    if msg.reply_to_id:
        parent = msg.reply_to
        if parent is not None:
            text = None
            if not parent.is_deleted and parent.message_type == models.MessageType.text and parent.content:
                text = parent.content[:120]
            sender = parent.sender
            out.reply = schemas.ReplyPreview(
                id=parent.id,
                sender_id=parent.sender_id,
                sender_name=((sender.name or sender.phone) if sender else None),
                content=text,
                message_type=_type_str(parent.message_type),
                is_deleted=bool(parent.is_deleted),
            )
    return out
