from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

app = FastAPI(title="Voice Trigger Automation")

# Allow your web application to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Current trigger state
trigger = {
    "active": False,
    "trigger_id": None,
    "started_at": None,
    "expires_at": None,
}


# -----------------------------
# START TRIGGER
# -----------------------------

class TriggerRequest(BaseModel):
    trigger_id: str
    duration_minutes: int


@app.post("/trigger/start")
def start_trigger(data: TriggerRequest):

    now = datetime.now(timezone.utc)

    expires_at = now + timedelta(
        minutes=data.duration_minutes
    )

    trigger["active"] = True
    trigger["trigger_id"] = data.trigger_id
    trigger["started_at"] = now
    trigger["expires_at"] = expires_at

    print("\n==============================")
    print("TRIGGER STARTED")
    print("==============================")
    print("Trigger ID:", data.trigger_id)
    print("Duration:", data.duration_minutes, "minutes")
    print("Started:", now)
    print("Expires:", expires_at)
    print("==============================\n")

    return {
        "message": "Trigger activated",
        "trigger_id": data.trigger_id,
        "active": True,
        "started_at": now,
        "expires_at": expires_at,
    }


# -----------------------------
# CHECK TRIGGER STATUS
# -----------------------------

@app.get("/trigger/status")
def trigger_status():

    if trigger["expires_at"] is None:
        return {
            "active": False,
            "trigger_id": None,
        }

    now = datetime.now(timezone.utc)

    # Automatically expire the trigger
    if now >= trigger["expires_at"]:
        trigger["active"] = False

    return {
        "active": trigger["active"],
        "trigger_id": trigger["trigger_id"],
        "started_at": trigger["started_at"],
        "expires_at": trigger["expires_at"],
    }


# -----------------------------
# STOP TRIGGER
# -----------------------------

@app.post("/trigger/stop")
def stop_trigger():

    trigger["active"] = False

    print("\n==============================")
    print("TRIGGER STOPPED")
    print("==============================\n")

    return {
        "message": "Trigger stopped",
        "active": False,
    }


# -----------------------------
# RECEIVE FINAL TRANSCRIPT
# -----------------------------

class TranscriptRequest(BaseModel):
    trigger_id: str
    transcript: str


@app.post("/trigger/result")
def receive_transcript(data: TranscriptRequest):

    print("\n==============================")
    print("FINAL TRANSCRIPT")
    print("==============================")
    print("Trigger ID:", data.trigger_id)
    print("Text:")
    print(data.transcript)
    print("==============================\n")

    return {
        "message": "Transcript received",
        "trigger_id": data.trigger_id,
        "text_length": len(data.transcript),
    }


# -----------------------------
# ROOT
# -----------------------------

@app.get("/")
def home():

    return {
        "message": "Voice Trigger Backend is running",
        "status": trigger["active"],
    }