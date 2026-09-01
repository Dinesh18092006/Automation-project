"""
Voice Trigger Automation — FastAPI Backend
==========================================
Lifecycle:
  POST /trigger/start  →  activate session  →  auto-expire after duration
  No /trigger/stop endpoint (requirement #8).

Expiry is enforced at three server layers:
  1. Background asyncio task   — proactive, every 30 s
  2. GET /trigger/status        — on every read
  3. POST /trigger/result       — on every write
"""

import asyncio
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone


# ─────────────────────────────────────────────
# IN-MEMORY TRIGGER STATE
# ─────────────────────────────────────────────

trigger: dict = {
    "active":        False,
    "trigger_id":    None,
    "started_at":    None,   # datetime (UTC)
    "expires_at":    None,   # datetime (UTC)
    "session_token": None,   # UUID4 string — unique per /trigger/start call
}


# ─────────────────────────────────────────────
# HELPER — check and auto-expire
# ─────────────────────────────────────────────

def _check_expiry() -> bool:
    """
    Compare server UTC clock against expires_at.
    Sets active=False if the session has expired.
    Returns True if the session is still active, False otherwise.
    """
    if not trigger["expires_at"]:
        return False
    if datetime.now(timezone.utc) >= trigger["expires_at"]:
        if trigger["active"]:
            trigger["active"] = False
            print("\n==============================")
            print("TRIGGER EXPIRED")
            print("Trigger ID:", trigger["trigger_id"])
            print("==============================\n")
    return trigger["active"]


# ─────────────────────────────────────────────
# BACKGROUND AUTO-EXPIRY TASK  (Layer 1)
# ─────────────────────────────────────────────

async def _auto_expiry_loop() -> None:
    """
    Runs indefinitely, checking for session expiry every 30 seconds.
    Ensures the trigger becomes inactive even if no endpoint is polled.
    """
    while True:
        await asyncio.sleep(30)
        _check_expiry()


# ─────────────────────────────────────────────
# LIFESPAN — start background task on startup
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_auto_expiry_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────

app = FastAPI(title="Voice Trigger Automation", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static frontend files at /static
_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


# ─────────────────────────────────────────────
# ROOT — serve the frontend UI
# ─────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def serve_frontend():
    index_path = os.path.join(_frontend_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")
    return {"message": "Voice Trigger Backend is running", "status": trigger["active"]}


# ─────────────────────────────────────────────
# HEALTH CHECK  (JSON — for monitoring / SNS Workbench)
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "message": "Voice Trigger Backend is running",
        "status":  trigger["active"],
    }


# ─────────────────────────────────────────────
# START TRIGGER
# ─────────────────────────────────────────────

class TriggerRequest(BaseModel):
    trigger_id:       str
    duration_minutes: int = Field(..., ge=1, le=1440,
                                  description="Session duration in minutes (1–1440)")


@app.post("/trigger/start")
def start_trigger(data: TriggerRequest):
    """
    Activate a new voice session.
    Always overwrites any existing session silently (requirement #10).
    Generates a fresh session_token per call to prevent cross-session leakage.
    """
    now           = datetime.now(timezone.utc)
    expires_at    = now + timedelta(minutes=data.duration_minutes)
    session_token = str(uuid4())

    trigger["active"]        = True
    trigger["trigger_id"]    = data.trigger_id
    trigger["started_at"]    = now
    trigger["expires_at"]    = expires_at
    trigger["session_token"] = session_token

    print("\n==============================")
    print("TRIGGER STARTED")
    print("==============================")
    print("Trigger ID   :", data.trigger_id)
    print("Duration     :", data.duration_minutes, "minutes")
    print("Started      :", now.isoformat())
    print("Expires      :", expires_at.isoformat())
    print("Session Token:", session_token)
    print("==============================\n")

    # Response preserves all original fields; session_token is additive
    return {
        "message":       "Trigger activated",
        "trigger_id":    data.trigger_id,
        "active":        True,
        "started_at":    now,
        "expires_at":    expires_at,
        "session_token": session_token,
    }


# ─────────────────────────────────────────────
# TRIGGER STATUS  (Layer 2 expiry — on read)
# ─────────────────────────────────────────────

@app.get("/trigger/status")
def trigger_status():
    """
    Returns the current trigger state.
    Auto-expires the session if expires_at has passed (Layer 2).
    Frontend polls this every 5 seconds.
    """
    if trigger["expires_at"] is None:
        return {
            "active":            False,
            "trigger_id":        None,
            "started_at":        None,
            "expires_at":        None,
            "session_token":     None,
            "seconds_remaining": 0,
        }

    _check_expiry()  # Layer 2: expire on read

    seconds_remaining = 0
    if trigger["active"] and trigger["expires_at"]:
        delta             = trigger["expires_at"] - datetime.now(timezone.utc)
        seconds_remaining = max(0, int(delta.total_seconds()))

    return {
        "active":            trigger["active"],
        "trigger_id":        trigger["trigger_id"],
        "started_at":        trigger["started_at"],
        "expires_at":        trigger["expires_at"],
        "session_token":     trigger["session_token"],
        "seconds_remaining": seconds_remaining,
    }


# ─────────────────────────────────────────────
# RECEIVE TRANSCRIPT  (Layer 3 expiry — on write)
# ─────────────────────────────────────────────

class TranscriptRequest(BaseModel):
    trigger_id:    str
    transcript:    str
    session_token: str


@app.post("/trigger/result")
def receive_transcript(data: TranscriptRequest):
    """
    Accept a speech transcript from the frontend.
    Validates (in order):
      1. Session is currently active
      2. Current time < expires_at  (Layer 3)
      3. trigger_id matches active session
      4. session_token matches active session (prevents cross-session leakage)
      5. Transcript is non-empty
    """
    # Layer 3: expire on write
    _check_expiry()

    if not trigger["active"]:
        raise HTTPException(
            status_code=403,
            detail="Trigger not active or session expired",
        )

    if data.trigger_id != trigger["trigger_id"]:
        raise HTTPException(
            status_code=403,
            detail="Trigger ID mismatch",
        )

    if data.session_token != trigger["session_token"]:
        raise HTTPException(
            status_code=403,
            detail="Invalid session token — possible expired or replaced session",
        )

    if not data.transcript.strip():
        raise HTTPException(
            status_code=400,
            detail="Transcript must not be empty",
        )

    print("\n==============================")
    print("TRANSCRIPT RECEIVED")
    print("==============================")
    print("Trigger ID:", data.trigger_id)
    print("Text:")
    print(data.transcript)
    print("==============================\n")

    return {
        "message":     "Transcript received",
        "trigger_id":  data.trigger_id,
        "text_length": len(data.transcript),
    }