from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app import models, schemas
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/communities", tags=["Communities"])


def _community_query(db: Session):
    return db.query(models.Community).options(
        joinedload(models.Community.members).joinedload(models.CommunityMember.user),
        joinedload(models.Community.groups).joinedload(models.Chat.members).joinedload(models.ChatMember.user),
    )


def _require_community_admin(db: Session, community: models.Community, user_id: int) -> models.CommunityMember:
    membership = {m.user_id: m for m in community.members}
    my_membership = membership.get(user_id)
    if not my_membership:
        raise HTTPException(status_code=403, detail="Aap is community ke member nahi ho")
    if not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Sirf community admin ye kaam kar sakta hai")
    return my_membership


@router.post("", response_model=schemas.CommunityOut)
def create_community(
    payload: schemas.CreateCommunityRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    community = models.Community(
        name=payload.name, description=payload.description, created_by=current_user.id
    )
    db.add(community)
    db.flush()

    db.add(models.CommunityMember(community_id=community.id, user_id=current_user.id, is_admin=True))
    db.commit()

    # har community ke saath ek default "Announcements" channel auto-banta hai
    announcement = models.Chat(
        type=models.ChatType.group,
        name="Announcements",
        description="Sirf admins yahan post kar sakte hain",
        community_id=community.id,
        is_announcement=True,
    )
    db.add(announcement)
    db.flush()
    db.add(models.ChatMember(chat_id=announcement.id, user_id=current_user.id, is_admin=True))
    db.commit()

    return _community_query(db).filter(models.Community.id == community.id).first()


@router.get("", response_model=List[schemas.CommunityOut])
def list_my_communities(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    my_ids = [
        cm.community_id
        for cm in db.query(models.CommunityMember).filter(
            models.CommunityMember.user_id == current_user.id
        )
    ]
    if not my_ids:
        return []
    return (
        _community_query(db)
        .filter(models.Community.id.in_(my_ids))
        .order_by(models.Community.created_at.desc())
        .all()
    )


@router.get("/{community_id}", response_model=schemas.CommunityOut)
def get_community(
    community_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    community = _community_query(db).filter(models.Community.id == community_id).first()
    if not community:
        raise HTTPException(status_code=404, detail="Community nahi mili")
    if current_user.id not in {m.user_id for m in community.members}:
        raise HTTPException(status_code=403, detail="Aap is community ke member nahi ho")
    return community


@router.post("/{community_id}/groups", response_model=schemas.ChatOut)
def create_group_under_community(
    community_id: int,
    payload: schemas.CreateCommunityGroupRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    community = _community_query(db).filter(models.Community.id == community_id).first()
    if not community:
        raise HTTPException(status_code=404, detail="Community nahi mili")
    if current_user.id not in {m.user_id for m in community.members}:
        raise HTTPException(status_code=403, detail="Aap is community ke member nahi ho")

    member_ids = set(payload.member_ids) - {current_user.id}
    if member_ids:
        found = db.query(models.User.id).filter(models.User.id.in_(member_ids)).all()
        found_ids = {f[0] for f in found}
        missing = member_ids - found_ids
        if missing:
            raise HTTPException(status_code=404, detail=f"Ye user IDs nahi mile: {sorted(missing)}")

    group = models.Chat(
        type=models.ChatType.group,
        name=payload.name,
        description=payload.description,
        community_id=community_id,
    )
    db.add(group)
    db.flush()

    db.add(models.ChatMember(chat_id=group.id, user_id=current_user.id, is_admin=True))
    for uid in member_ids:
        db.add(models.ChatMember(chat_id=group.id, user_id=uid, is_admin=False))
    db.commit()

    return (
        db.query(models.Chat)
        .options(joinedload(models.Chat.members).joinedload(models.ChatMember.user))
        .filter(models.Chat.id == group.id)
        .first()
    )


@router.post("/{community_id}/members", response_model=schemas.CommunityOut)
def add_community_members(
    community_id: int,
    payload: schemas.AddCommunityMembersRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    community = _community_query(db).filter(models.Community.id == community_id).first()
    if not community:
        raise HTTPException(status_code=404, detail="Community nahi mili")

    _require_community_admin(db, community, current_user.id)

    existing = {m.user_id for m in community.members}
    new_ids = set(payload.member_ids) - existing
    if new_ids:
        found = db.query(models.User.id).filter(models.User.id.in_(new_ids)).all()
        found_ids = {f[0] for f in found}
        missing = new_ids - found_ids
        if missing:
            raise HTTPException(status_code=404, detail=f"Ye user IDs nahi mile: {sorted(missing)}")
        for uid in new_ids:
            db.add(models.CommunityMember(community_id=community_id, user_id=uid, is_admin=False))
        db.commit()

    return _community_query(db).filter(models.Community.id == community_id).first()


@router.delete("/{community_id}/members/{user_id}", response_model=schemas.CommunityOut)
def remove_community_member(
    community_id: int,
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    community = _community_query(db).filter(models.Community.id == community_id).first()
    if not community:
        raise HTTPException(status_code=404, detail="Community nahi mili")

    membership = {m.user_id: m for m in community.members}
    my_membership = membership.get(current_user.id)
    if not my_membership:
        raise HTTPException(status_code=403, detail="Aap is community ke member nahi ho")
    if user_id != current_user.id and not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Sirf community admin dusre members remove kar sakta hai")

    target = membership.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Ye user is community ka member nahi hai")

    db.delete(target)
    db.commit()
    return _community_query(db).filter(models.Community.id == community_id).first()
