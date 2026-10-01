import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from telethon import TelegramClient, errors

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_DIR = os.environ.get("SESSION_DIR", "/data")
SESSION_NAME = os.environ.get("SESSION_NAME", "agent")
SESSION_PATH = os.path.join(SESSION_DIR, SESSION_NAME)
API_TOKEN = os.environ.get("API_TOKEN", "")

os.makedirs(SESSION_DIR, exist_ok=True)

client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

_pending_login: dict[str, str] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await client.connect()
    yield
    await client.disconnect()


app = FastAPI(title="mimic-telethon", lifespan=lifespan)


async def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not API_TOKEN:
        return
    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


class SendRequest(BaseModel):
    to: str = Field(..., description="Peer: @username, phone, or numeric id")
    message: str


class LoginStartRequest(BaseModel):
    phone: str = Field(..., description="Phone in international format, e.g. +15551234567")


class LoginVerifyRequest(BaseModel):
    code: str
    password: Optional[str] = Field(default=None, description="2FA password if enabled")


def _peer_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/health", dependencies=[Depends(require_token)])
async def health():
    return {
        "connected": client.is_connected(),
        "authorized": await client.is_user_authorized(),
    }


@app.post("/login/start", dependencies=[Depends(require_token)])
async def login_start(req: LoginStartRequest):
    if await client.is_user_authorized():
        return {"status": "already_authorized"}
    sent = await client.send_code_request(req.phone)
    _pending_login["phone"] = req.phone
    _pending_login["phone_code_hash"] = sent.phone_code_hash
    return {"status": "code_sent", "phone": req.phone}


@app.post("/login/verify", dependencies=[Depends(require_token)])
async def login_verify(req: LoginVerifyRequest):
    phone = _pending_login.get("phone")
    phone_code_hash = _pending_login.get("phone_code_hash")
    if not phone or not phone_code_hash:
        raise HTTPException(status_code=400, detail="call /login/start first")
    try:
        await client.sign_in(
            phone=phone,
            code=req.code,
            phone_code_hash=phone_code_hash,
        )
    except errors.SessionPasswordNeededError:
        if not req.password:
            raise HTTPException(status_code=428, detail="2FA password required")
        try:
            await client.sign_in(password=req.password)
        except errors.PasswordHashInvalidError:
            raise HTTPException(status_code=400, detail="invalid 2FA password")
    except errors.PhoneCodeInvalidError:
        raise HTTPException(status_code=400, detail="invalid login code")
    except errors.PhoneCodeExpiredError:
        raise HTTPException(status_code=400, detail="login code expired; restart")
    _pending_login.clear()
    me = await client.get_me()
    return {"status": "authorized", "id": me.id, "username": me.username}


@app.post("/logout", dependencies=[Depends(require_token)])
async def logout():
    await client.log_out()
    return {"status": "logged_out"}


@app.post("/send", dependencies=[Depends(require_token)])
async def send(req: SendRequest):
    if not await client.is_user_authorized():
        raise HTTPException(status_code=401, detail="not authorized; use /login/start")
    try:
        entity = await client.get_entity(req.to)
    except Exception as exc:
        raise _peer_error(exc)
    sent = await client.send_message(entity, req.message)
    return {"status": "sent", "message_id": sent.id, "to": req.to}


@app.get("/messages/{peer}", dependencies=[Depends(require_token)])
async def messages(peer: str, limit: int = 20):
    if not await client.is_user_authorized():
        raise HTTPException(status_code=401, detail="not authorized; use /login/start")
    try:
        entity = await client.get_entity(peer)
    except Exception as exc:
        raise _peer_error(exc)
    out = []
    async for msg in client.iter_messages(entity, limit=limit):
        out.append(
            {
                "id": msg.id,
                "out": msg.out,
                "date": msg.date.isoformat() if msg.date else None,
                "sender_id": msg.sender_id,
                "text": msg.text,
            }
        )
    return {"peer": peer, "messages": out}
