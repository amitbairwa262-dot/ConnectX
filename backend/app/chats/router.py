from typing import List
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app import models, schemas
from app.config import settings
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/chats", tags=["Chats"])


def _chat_with_members_query(db: Session):
    return db.query(models.Chat).options(
        joinedload(models.Chat.members).joinedload(models.ChatMember.user)
    )


@router.post("/private", response_model=schemas.ChatOut)
def create_or_get_private_chat(
    payload: schemas.CreatePrivateChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Khud ke saath chat nahi bana sakte")

    other_user = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="User nahi mila")

    # check if a private chat already exists between these two users
    my_chat_ids = {
        cm.chat_id
        for cm in db.query(models.ChatMember).filter(models.ChatMember.user_id == current_user.id)
    }
    existing = (
        _chat_with_members_query(db)
        .filter(models.Chat.id.in_(my_chat_ids), models.Chat.type == models.ChatType.private)
        .all()
    )
    for chat in existing:
        member_ids = {m.user_id for m in chat.members}
        if member_ids == {current_user.id, other_user.id}:
            return chat

    # create a new private chat
    chat = models.Chat(type=models.ChatType.private)
    db.add(chat)
    db.flush()  # get chat.id before commit

    db.add(models.ChatMember(chat_id=chat.id, user_id=current_user.id, is_admin=True))
    db.add(models.ChatMember(chat_id=chat.id, user_id=other_user.id, is_admin=True))
    db.commit()

    return _chat_with_members_query(db).filter(models.Chat.id == chat.id).first()


@router.post("/group", response_model=schemas.ChatOut)
def create_group_chat(
    payload: schemas.CreateGroupChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member_ids = set(payload.member_ids) - {current_user.id}
    if member_ids:
        found = db.query(models.User.id).filter(models.User.id.in_(member_ids)).all()
        found_ids = {f[0] for f in found}
        missing = member_ids - found_ids
        if missing:
            raise HTTPException(status_code=404, detail=f"Ye user IDs nahi mile: {sorted(missing)}")

    chat = models.Chat(
        type=models.ChatType.group, name=payload.name, description=payload.description
    )
    db.add(chat)
    db.flush()

    db.add(models.ChatMember(chat_id=chat.id, user_id=current_user.id, is_admin=True))
    for uid in member_ids:
        db.add(models.ChatMember(chat_id=chat.id, user_id=uid, is_admin=False))
    db.commit()

    return _chat_with_members_query(db).filter(models.Chat.id == chat.id).first()


@router.get("", response_model=List[schemas.ChatOut])
def list_my_chats(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    my_chat_ids = [
        cm.chat_id
        for cm in db.query(models.ChatMember).filter(models.ChatMember.user_id == current_user.id)
    ]
    if not my_chat_ids:
        return []
    return (
        _chat_with_members_query(db)
        .filter(models.Chat.id.in_(my_chat_ids))
        .order_by(models.Chat.created_at.desc())
        .all()
    )


@router.get("/{chat_id}", response_model=schemas.ChatOut)
def get_chat(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if current_user.id not in {m.user_id for m in chat.members}:
        raise HTTPException(status_code=403, detail="Aap is chat ke member nahi ho")
    return chat


@router.post("/{chat_id}/members", response_model=schemas.ChatOut)
def add_members(
    chat_id: int,
    payload: schemas.AddMembersRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Sirf group chats me members add kar sakte ho")

    membership = {m.user_id: m for m in chat.members}
    my_membership = membership.get(current_user.id)
    if not my_membership:
        raise HTTPException(status_code=403, detail="Aap is group ke member nahi ho")
    if not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Sirf group admin members add kar sakta hai")

    new_ids = set(payload.member_ids) - set(membership.keys())
    if new_ids:
        found = db.query(models.User.id).filter(models.User.id.in_(new_ids)).all()
        found_ids = {f[0] for f in found}
        missing = new_ids - found_ids
        if missing:
            raise HTTPException(status_code=404, detail=f"Ye user IDs nahi mile: {sorted(missing)}")
        for uid in new_ids:
            db.add(models.ChatMember(chat_id=chat.id, user_id=uid, is_admin=False))
        db.commit()

    return _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()


@router.delete("/{chat_id}/members/{user_id}", response_model=schemas.ChatOut)
def remove_member(
    chat_id: int,
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Sirf group chats se members remove kar sakte ho")

    membership = {m.user_id: m for m in chat.members}
    my_membership = membership.get(current_user.id)
    if not my_membership:
        raise HTTPException(status_code=403, detail="Aap is group ke member nahi ho")

    # a member can remove themselves; otherwise only an admin can remove others
    if user_id != current_user.id and not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Sirf group admin dusre members remove kar sakta hai")

    target = membership.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Ye user is group ka member nahi hai")

    db.delete(target)
    db.commit()

    return _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()


def _require_group_admin(db: Session, chat: models.Chat, user_id: int) -> models.ChatMember:
    membership = {m.user_id: m for m in chat.members}
    my_membership = membership.get(user_id)
    if not my_membership:
        raise HTTPException(status_code=403, detail="Aap is group ke member nahi ho")
    if not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Sirf group admin ye kaam kar sakta hai")
    return my_membership


@router.put("/{chat_id}", response_model=schemas.ChatOut)
def update_group_info(
    chat_id: int,
    payload: schemas.UpdateGroupRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Sirf group chats ki info update ho sakti hai")

    _require_group_admin(db, chat, current_user.id)

    if payload.name is not None:
        chat.name = payload.name.strip()
    if payload.description is not None:
        chat.description = payload.description.strip()

    db.commit()
    return _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()


@router.post("/{chat_id}/photo", response_model=schemas.ChatOut)
def upload_group_photo(
    chat_id: int,
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Sirf group chats ki photo set ho sakti hai")

    _require_group_admin(db, chat, current_user.id)

    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Sirf JPEG, PNG ya WEBP image allowed hai")

    contents = file.file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Photo 5MB se badi nahi honi chahiye")

    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    folder = os.path.join(settings.UPLOAD_DIR, "group_photos")
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    chat.photo = f"/{filepath.replace(os.sep, '/')}"
    db.commit()
    return _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()


@router.put("/{chat_id}/members/{user_id}/admin", response_model=schemas.ChatOut)
def set_member_admin(
    chat_id: int,
    user_id: int,
    payload: schemas.SetAdminRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Sirf group chats me admin set ho sakta hai")

    _require_group_admin(db, chat, current_user.id)

    membership = {m.user_id: m for m in chat.members}
    target = membership.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Ye user is group ka member nahi hai")

    target.is_admin = payload.is_admin
    db.commit()
    return _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()


@router.post("/{chat_id}/leave")
def leave_group(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Private chat chhod nahi sakte, sirf group")

    membership = {m.user_id: m for m in chat.members}
    my_membership = membership.get(current_user.id)
    if not my_membership:
        raise HTTPException(status_code=403, detail="Aap is group ke member nahi ho")

    db.delete(my_membership)
    db.commit()

    # agar koi admin bacha hi nahi, to sabse purane member ko promote kar do
    remaining = (
        db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id).all()
    )
    if remaining and not any(m.is_admin for m in remaining):
        oldest = min(remaining, key=lambda m: m.joined_at)
        oldest.is_admin = True
        db.commit()

    return {"message": "Group chhod diya"}


@router.post("/{chat_id}/invite-link")
def get_or_create_invite_link(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nahi mila")
    if chat.type != models.ChatType.group:
        raise HTTPException(status_code=400, detail="Sirf group chats ka invite link banta hai")

    membership = {m.user_id: m for m in chat.members}
    if current_user.id not in membership:
        raise HTTPException(status_code=403, detail="Aap is group ke member nahi ho")

    if not chat.join_code:
        chat.join_code = uuid.uuid4().hex[:10]
        db.commit()

    return {"join_code": chat.join_code}


@router.post("/join/{join_code}", response_model=schemas.ChatOut)
def join_group_via_code(
    join_code: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = _chat_with_members_query(db).filter(models.Chat.join_code == join_code).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Invalid ya expired invite link")

    membership = {m.user_id for m in chat.members}
    if current_user.id not in membership:
        db.add(models.ChatMember(chat_id=chat.id, user_id=current_user.id, is_admin=False))
        db.commit()

    return _chat_with_members_query(db).filter(models.Chat.id == chat.id).first()
