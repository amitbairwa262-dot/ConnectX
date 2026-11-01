import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app import models  # noqa: F401  (needed so tables get registered on Base)
from app.config import settings
from app.auth.router import router as auth_router
from app.users.router import router as users_router
from app.chats.router import router as chats_router
from app.messages.router import router as messages_router
from app.messages.media_router import router as media_router
from app.status.router import router as status_router
from app.communities.router import router as communities_router
from app.calls.router import router as calls_router
from app.ai.router import router as ai_router

Base.metadata.create_all(bind=engine)
from app.migrate import run_light_migrations  # noqa: E402
run_light_migrations()
os.makedirs(os.path.join(settings.UPLOAD_DIR, "profile_photos"), exist_ok=True)
os.makedirs(os.path.join(settings.UPLOAD_DIR, "group_photos"), exist_ok=True)
for folder in ("images", "videos", "documents", "voice"):
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "chat_media", folder), exist_ok=True)
os.makedirs(os.path.join(settings.UPLOAD_DIR, "status_media"), exist_ok=True)

app = FastAPI(title="ConnectX API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(f"/{settings.UPLOAD_DIR}", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(media_router)
app.include_router(status_router)
app.include_router(communities_router)
app.include_router(calls_router)
app.include_router(ai_router)


@app.get("/")
def root():
    return {"message": "ConnectX API chal raha hai 🚀"}
