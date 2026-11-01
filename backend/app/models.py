from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Enum, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ChatType(str, enum.Enum):
    private = "private"
    group = "group"


class MessageType(str, enum.Enum):
    text = "text"
    image = "image"
    video = "video"
    document = "document"
    voice = "voice"
    location = "location"
    contact = "contact"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    email = Column(String(120), unique=True, index=True, nullable=True)
    name = Column(String(100), nullable=True)
    about = Column(String(200), default="Hey there! I'm using ConnectX.")
    profile_image = Column(String(255), nullable=True)
    is_online = Column(Boolean, default=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat_memberships = relationship("ChatMember", back_populates="user")
    messages = relationship("Message", back_populates="sender")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ChatType), default=ChatType.private)
    name = Column(String(100), nullable=True)         # used for group chats
    description = Column(String(255), nullable=True)  # group description
    photo = Column(String(255), nullable=True)
    join_code = Column(String(20), unique=True, nullable=True)  # invite-link code (groups only)
    community_id = Column(Integer, ForeignKey("communities.id"), nullable=True)
    is_announcement = Column(Boolean, default=False)   # announcement channel: only community admins can post
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    members = relationship("ChatMember", back_populates="chat")
    messages = relationship("Message", back_populates="chat")
    community = relationship("Community", back_populates="groups")


class ChatMember(Base):
    __tablename__ = "chat_members"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_admin = Column(Boolean, default=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("Chat", back_populates="members")
    user = relationship("User", back_populates="chat_memberships")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=True)
    message_type = Column(Enum(MessageType), default=MessageType.text)
    is_seen = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Phase 10: reply / edit / delete-for-everyone / pin ---
    reply_to_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    edited_at = Column(DateTime(timezone=True), nullable=True)
    is_pinned = Column(Boolean, default=False)

    chat = relationship("Chat", back_populates="messages")
    sender = relationship("User", back_populates="messages")
    reply_to = relationship("Message", remote_side=[id], foreign_keys=[reply_to_id])
    reactions = relationship(
        "MessageReaction", back_populates="message", cascade="all, delete-orphan"
    )


class MessageReaction(Base):
    """One emoji reaction per user per message (tap same emoji again to remove)."""
    __tablename__ = "message_reactions"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_reaction_message_user"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    emoji = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="reactions")


class MessageStar(Base):
    """Per-user starred (bookmarked) messages."""
    __tablename__ = "message_stars"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_star_message_user"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class MessageHidden(Base):
    """'Delete for me' — message stays for others, hidden only for this user."""
    __tablename__ = "message_hidden"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_hidden_message_user"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class OTP(Base):
    """Stores the latest OTP issued for a phone or email until it's verified/expired."""
    __tablename__ = "otps"

    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(120), index=True, nullable=False)  # phone or email
    code = Column(String(10), nullable=False)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StatusType(str, enum.Enum):
    text = "text"
    image = "image"
    video = "video"


class Status(Base):
    """A story/status post that auto-expires after 24 hours."""
    __tablename__ = "statuses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status_type = Column(Enum(StatusType), default=StatusType.text)
    content = Column(Text, nullable=True)          # text content, or file URL for image/video
    background_color = Column(String(20), nullable=True)  # for text statuses, e.g. "#2dd4bf"
    caption = Column(String(255), nullable=True)   # caption for image/video statuses
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")
    views = relationship("StatusView", back_populates="status", cascade="all, delete-orphan")


class StatusView(Base):
    """Tracks who has viewed a status, and when."""
    __tablename__ = "status_views"

    id = Column(Integer, primary_key=True, index=True)
    status_id = Column(Integer, ForeignKey("statuses.id"), nullable=False)
    viewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now())

    status = relationship("Status", back_populates="views")
    viewer = relationship("User")


class Community(Base):
    """A community groups multiple group chats together under one umbrella,
    with its own members and admins (WhatsApp Communities-style)."""
    __tablename__ = "communities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    photo = Column(String(255), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    members = relationship("CommunityMember", back_populates="community")
    groups = relationship("Chat", back_populates="community")


class CommunityMember(Base):
    __tablename__ = "community_members"

    id = Column(Integer, primary_key=True, index=True)
    community_id = Column(Integer, ForeignKey("communities.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_admin = Column(Boolean, default=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    community = relationship("Community", back_populates="members")
    user = relationship("User")


class CallType(str, enum.Enum):
    voice = "voice"
    video = "video"


class CallStatus(str, enum.Enum):
    ringing = "ringing"
    ongoing = "ongoing"
    missed = "missed"
    declined = "declined"
    ended = "ended"


class Call(Base):
    """1-to-1 voice/video call. Actual media is peer-to-peer (WebRTC) between
    the two users' devices — this table + the /ws/calls signaling socket only
    handle call setup (ringing, answer, decline, end) and history."""
    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, index=True)
    caller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    callee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    call_type = Column(Enum(CallType), default=CallType.voice)
    status = Column(Enum(CallStatus), default=CallStatus.ringing)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    answered_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    caller = relationship("User", foreign_keys=[caller_id])
    callee = relationship("User", foreign_keys=[callee_id])
