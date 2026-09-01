from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

app = FastAPI(title="Voice Trigger API")


# -----------------------------
# Trigger state
# -----------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

trigger = {
    "active": False,
    "trigger_id": None,
    "started_at": None,
    "expires_at": None,
}


# -----------------------------
# Request models
# -----------------------------

class TriggerRequest(BaseModel):
    trigger_id: str = Field(min_length=1)
    duration_minutes: int = Field(gt=0)


class TranscriptRequest(BaseModel):
    trigger_id: str = Field(min_length=1)
    transcript: str


# -----------------------------
# Home / health check
# -----------------------------

@app.get("/")
def home():
    return {
        "message": "Voice Trigger API is running",
        "active": trigger["active"],
    }


# -----------------------------
# Start trigger
# -----------------------------

@app.post("/trigger/start")
def start_trigger(data: TriggerRequest):

    now = datetime.now(timezone.utc)

    trigger["active"] = True
    trigger["trigger_id"] = data.trigger_id
    trigger["started_at"] = now
    trigger["expires_at"] = now + timedelta(
        minutes=data.duration_minutes
    )

    return {
        "message": "Trigger activated",
        "trigger_id": trigger["trigger_id"],
        "active": True,
        "started_at": trigger["started_at"],
        "expires_at": trigger["expires_at"],
    }


# -----------------------------
# Check trigger status
# -----------------------------

@app.get("/trigger/status")
def trigger_status():

    if trigger["expires_at"] is not None:

        now = datetime.now(timezone.utc)

        if now >= trigger["expires_at"]:
            trigger["active"] = False

    return {
        "active": trigger["active"],
        "trigger_id": trigger["trigger_id"],
        "started_at": trigger["started_at"],
        "expires_at": trigger["expires_at"],
    }


# -----------------------------
# Receive transcript
# -----------------------------

@app.post("/trigger/result")
def receive_transcript(data: TranscriptRequest):

    # Check expiration before accepting text
    if trigger["expires_at"] is not None:

        now = datetime.now(timezone.utc)

        if now >= trigger["expires_at"]:
            trigger["active"] = False

    # Do not accept text after trigger expires
    if not trigger["active"]:
        return {
            "message": "Trigger is inactive",
            "accepted": False,
        }

    # Make sure transcript belongs to active trigger
    if data.trigger_id != trigger["trigger_id"]:
        return {
            "message": "Invalid trigger ID",
            "accepted": False,
        }

    print("Received transcript:")
    print(data.transcript)

    return {
        "message": "Transcript received",
        "trigger_id": data.trigger_id,
        "accepted": True,
    }

