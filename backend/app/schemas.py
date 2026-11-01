from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime


# ---------- OTP ----------
class SendOTPRequest(BaseModel):
    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    @field_validator("phone")
    @classmethod
    def check_identifier(cls, v, info):
        return v

    def identifier(self) -> str:
        if self.phone:
            return self.phone.strip()
        if self.email:
            return self.email.strip().lower()
        raise ValueError("phone ya email me se ek dena zaruri hai")


class VerifyOTPRequest(BaseModel):
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    code: str

    def identifier(self) -> str:
        if self.phone:
            return self.phone.strip()
        if self.email:
            return self.email.strip().lower()
        raise ValueError("phone ya email me se ek dena zaruri hai")


# ---------- User ----------
class UserOut(BaseModel):
    id: int
    username: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    about: Optional[str] = None
    profile_image: Optional[str] = None
    is_online: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    is_new_user: bool


# ---------- Profile (Phase 2) ----------
class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    about: Optional[str] = None


class SetUsernameRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("Username khali nahi ho sakta")
        if len(v) < 3 or len(v) > 30:
            raise ValueError("Username 3 se 30 characters ke beech hona chahiye")
        if not all(c.isalnum() or c == "_" for c in v):
            raise ValueError("Username sirf letters, numbers aur underscore (_) use kar sakta hai")
        return v


class UsernameAvailableResponse(BaseModel):
    username: str
    available: bool


# ---------- Chats (Phase 3) ----------
class CreatePrivateChatRequest(BaseModel):
    user_id: int  # the other person to chat with


class CreateGroupChatRequest(BaseModel):
    name: str
    description: Optional[str] = None
    member_ids: list[int] = []  # other members besides the creator

    @field_validator("name")
    @classmethod
    def validate_group_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Group ka naam khali nahi ho sakta")
        if len(v) > 100:
            raise ValueError("Group ka naam 100 characters se chhota hona chahiye")
        return v


class AddMembersRequest(BaseModel):
    member_ids: list[int]


class ChatMemberOut(BaseModel):
    user: UserOut
    is_admin: bool

    class Config:
        from_attributes = True


class ChatOut(BaseModel):
    id: int
    type: str
    name: Optional[str] = None
    description: Optional[str] = None
    photo: Optional[str] = None
    community_id: Optional[int] = None
    is_announcement: bool = False
    created_at: datetime
    members: list[ChatMemberOut] = []

    class Config:
        from_attributes = True


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class SetAdminRequest(BaseModel):
    is_admin: bool


# ---------- Messages (Phase 4) ----------
class SendMessageRequest(BaseModel):
    content: str
    message_type: str = "text"
    reply_to_id: Optional[int] = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message khali nahi ho sakta")
        if len(v) > 5000:
            raise ValueError("Message bahut lamba hai (max 5000 characters)")
        return v


class ReactionOut(BaseModel):
    user_id: int
    emoji: str

    class Config:
        from_attributes = True


class ReplyPreview(BaseModel):
    id: int
    sender_id: int
    sender_name: Optional[str] = None
    content: Optional[str] = None
    message_type: str = "text"
    is_deleted: bool = False


class EditMessageRequest(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message khali nahi ho sakta")
        if len(v) > 5000:
            raise ValueError("Message bahut lamba hai (max 5000 characters)")
        return v


class ReactRequest(BaseModel):
    emoji: str

    @field_validator("emoji")
    @classmethod
    def validate_emoji(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 16:
            raise ValueError("Emoji galat hai")
        return v


class PinRequest(BaseModel):
    pinned: bool = True


class MessageOut(BaseModel):
    id: int
    chat_id: int
    sender_id: int
    sender: UserOut
    content: Optional[str] = None
    message_type: str
    is_seen: bool
    created_at: datetime
    reply_to_id: Optional[int] = None
    is_deleted: Optional[bool] = False
    edited_at: Optional[datetime] = None
    is_pinned: Optional[bool] = False
    reactions: list[ReactionOut] = []
    reply: Optional[ReplyPreview] = None  # filled by messages/serializers.py

    class Config:
        from_attributes = True

    def media_info(self) -> Optional[dict]:
        """For image/video/document/voice messages, splits the stored
        'url|||filename|||caption' string into a friendly dict for the frontend."""
        if self.message_type == "text" or not self.content or "|||" not in self.content:
            return None
        parts = self.content.split("|||")
        url = parts[0] if len(parts) > 0 else ""
        filename = parts[1] if len(parts) > 1 else ""
        caption = parts[2] if len(parts) > 2 else ""
        return {"url": url, "filename": filename, "caption": caption}


# ---------- Status / Stories (Phase 6) ----------
class CreateTextStatusRequest(BaseModel):
    content: str
    background_color: Optional[str] = "#2dd4bf"

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Status khali nahi ho sakta")
        if len(v) > 700:
            raise ValueError("Status text bahut lamba hai (max 700 characters)")
        return v


class StatusOut(BaseModel):
    id: int
    user_id: int
    user: UserOut
    status_type: str
    content: Optional[str] = None
    background_color: Optional[str] = None
    caption: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    view_count: int = 0
    viewed_by_me: bool = False

    class Config:
        from_attributes = True


class StatusViewerOut(BaseModel):
    viewer: UserOut
    viewed_at: datetime

    class Config:
        from_attributes = True


# ---------- Communities (Phase 7) ----------
class CreateCommunityRequest(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Community ka naam khali nahi ho sakta")
        if len(v) > 100:
            raise ValueError("Naam 100 characters se chhota hona chahiye")
        return v


class CreateCommunityGroupRequest(BaseModel):
    name: str
    description: Optional[str] = None
    member_ids: list[int] = []


class CommunityMemberOut(BaseModel):
    user: UserOut
    is_admin: bool

    class Config:
        from_attributes = True


class CommunityOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    photo: Optional[str] = None
    created_by: int
    created_at: datetime
    members: list[CommunityMemberOut] = []
    groups: list[ChatOut] = []

    class Config:
        from_attributes = True


class AddCommunityMembersRequest(BaseModel):
    member_ids: list[int]


# ---------- Calls (Phase 8) ----------
class StartCallRequest(BaseModel):
    callee_id: int
    call_type: str = "voice"  # voice | video


class CallOut(BaseModel):
    id: int
    caller_id: int
    callee_id: int
    caller: UserOut
    callee: UserOut
    call_type: str
    status: str
    started_at: datetime
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None

    class Config:
        from_attributes = True


# ---------- AI Features (Phase 9) ----------
class AIChatRequest(BaseModel):
    message: str


class AIChatResponse(BaseModel):
    reply: str


class TranslateRequest(BaseModel):
    text: str
    target_language: str  # e.g. "Hindi", "English", "Spanish"


class TranslateResponse(BaseModel):
    translated_text: str


class RewriteRequest(BaseModel):
    text: str
    tone: str = "polite"  # polite | formal | casual | funny | professional


class RewriteResponse(BaseModel):
    rewritten_text: str


class SummaryResponse(BaseModel):
    summary: str
    message_count: int


class ReplySuggestionsResponse(BaseModel):
    suggestions: list[str]
