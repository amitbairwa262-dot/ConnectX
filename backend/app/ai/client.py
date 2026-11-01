import httpx
from fastapi import HTTPException
from app.config import settings

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


async def ask_claude(system: str, user_message: str, max_tokens: int = 500) -> str:
    """Sends one message to Claude and returns the plain text reply.
    Requires ANTHROPIC_API_KEY to be set as an environment variable."""
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "ANTHROPIC_API_KEY set nahi hai. console.anthropic.com se API key lo "
                "aur environment variable ANTHROPIC_API_KEY me set karo."
            ),
        )

    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": settings.AI_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.post(ANTHROPIC_URL, headers=headers, json=body)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"AI service tak nahi pahunch paye: {e}")

    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"AI service error: {res.text}")

    data = res.json()
    parts = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
    return "".join(parts).strip()
