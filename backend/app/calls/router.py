from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db, SessionLocal
from app import models, schemas
from app.auth.dependencies import get_current_user
from app.auth.utils import decode_access_token
from app.calls.connection_manager import manager

router = APIRouter(prefix="/api/calls", tags=["Calls"])


def _call_query(db: Session):
    return db.query(models.Call).options(
        joinedload(models.Call.caller), joinedload(models.Call.callee)
    )


def _get_my_call(db: Session, call_id: int, user_id: int) -> models.Call:
    call = _call_query(db).filter(models.Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call nahi mili")
    if user_id not in (call.caller_id, call.callee_id):
        raise HTTPException(status_code=403, detail="Ye aapki call nahi hai")
    return call


@router.post("", response_model=schemas.CallOut)
async def start_call(
    payload: schemas.StartCallRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.callee_id == current_user.id:
        raise HTTPException(status_code=400, detail="Khud ko call nahi kar sakte")

    callee = db.query(models.User).filter(models.User.id == payload.callee_id).first()
    if not callee:
        raise HTTPException(status_code=404, detail="User nahi mila")

    try:
        call_type = models.CallType(payload.call_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="call_type voice ya video hona chahiye")

    call = models.Call(caller_id=current_user.id, callee_id=callee.id, call_type=call_type)
    db.add(call)
    db.commit()
    db.refresh(call)

    call_out = _call_query(db).filter(models.Call.id == call.id).first()
    result = schemas.CallOut.model_validate(call_out)

    delivered = await manager.send_to(
        callee.id,
        {"event": "incoming_call", "call": result.model_dump(mode="json")},
    )
    if not delivered:
        # callee abhi online nahi hai — call missed maan lo
        call.status = models.CallStatus.missed
        db.commit()
        result.status = "missed"

    return result


@router.post("/{call_id}/answer", response_model=schemas.CallOut)
async def answer_call(
    call_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    call = _get_my_call(db, call_id, current_user.id)
    if call.callee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sirf callee hi call answer kar sakta hai")
    if call.status != models.CallStatus.ringing:
        raise HTTPException(status_code=400, detail=f"Ye call abhi '{call.status.value}' state me hai")

    call.status = models.CallStatus.ongoing
    call.answered_at = datetime.now(timezone.utc)
    db.commit()

    await manager.send_to(call.caller_id, {"event": "call_answered", "call_id": call.id})

    return _call_query(db).filter(models.Call.id == call.id).first()


@router.post("/{call_id}/decline", response_model=schemas.CallOut)
async def decline_call(
    call_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    call = _get_my_call(db, call_id, current_user.id)
    if call.callee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sirf callee hi call decline kar sakta hai")

    call.status = models.CallStatus.declined
    call.ended_at = datetime.now(timezone.utc)
    db.commit()

    await manager.send_to(call.caller_id, {"event": "call_declined", "call_id": call.id})

    return _call_query(db).filter(models.Call.id == call.id).first()


@router.post("/{call_id}/end", response_model=schemas.CallOut)
async def end_call(
    call_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    call = _get_my_call(db, call_id, current_user.id)
    if call.status not in (models.CallStatus.ringing, models.CallStatus.ongoing):
        raise HTTPException(status_code=400, detail="Ye call pehle se khatam ho chuki hai")

    now = datetime.now(timezone.utc)
    call.ended_at = now
    if call.status == models.CallStatus.ongoing and call.answered_at:
        answered_at = call.answered_at
        if answered_at.tzinfo is None:
            answered_at = answered_at.replace(tzinfo=timezone.utc)
        call.duration_seconds = int((now - answered_at).total_seconds())
    call.status = models.CallStatus.ended
    db.commit()

    other_id = call.callee_id if current_user.id == call.caller_id else call.caller_id
    await manager.send_to(other_id, {"event": "call_ended", "call_id": call.id})

    return _call_query(db).filter(models.Call.id == call.id).first()


@router.get("/history", response_model=List[schemas.CallOut])
def call_history(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        _call_query(db)
        .filter(
            (models.Call.caller_id == current_user.id)
            | (models.Call.callee_id == current_user.id)
        )
        .order_by(models.Call.started_at.desc())
        .limit(100)
        .all()
    )


@router.websocket("/ws")
async def call_signaling_socket(websocket: WebSocket, token: str = Query(...)):
    """
    Ek user ka ek hi signaling connection — poore app me jahan bhi ho, isi se
    incoming call, answer/decline/end notifications, aur WebRTC offer/answer/
    ICE candidates relay hote hain.

    Connect: ws://127.0.0.1:8000/api/calls/ws?token=<jwt>

    Signal relay bhejne ke liye:
      { "event": "signal", "target_user_id": 5, "data": { ...webrtc offer/answer/candidate... } }
    Doosri taraf ko milta hai:
      { "event": "signal", "from_user_id": 3, "data": { ... } }
    """
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=4401)
        return
    user_id = int(payload.get("sub"))

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            await websocket.close(code=4404)
            return
    finally:
        db.close()

    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("event") == "signal":
                target_id = data.get("target_user_id")
                await manager.send_to(
                    target_id,
                    {"event": "signal", "from_user_id": user_id, "data": data.get("data")},
                )
    except WebSocketDisconnect:
        manager.disconnect(user_id)
