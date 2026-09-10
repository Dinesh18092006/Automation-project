import os
import sys
import json
import time
import logging
import asyncio
from typing import Optional, Set, Any
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def load_env():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    for env_path in [
        os.path.join(cur_dir, ".env"),
        os.path.join(cur_dir, "..", ".env"),
        os.path.join(cur_dir, "..", "frontend", ".env")
    ]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v

load_env()

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
DEFAULT_SUPABASE_URL = os.getenv("SUPABASE_URL", "https://vzxlgygptsdtyiowowfq.supabase.co")
DEFAULT_SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6eGxneWdwdHNkdHlpb3dvd2ZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDcyNDQsImV4cCI6MjEwMzgyMzI0NH0.pLgvSOj18ZPbcq6BNSPeQSMMx36HuWrjI_ycyg_J8ec")
DEFAULT_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
DEFAULT_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIMENSION", "768"))
DEFAULT_GEMINI_GENERATION_MODEL = os.getenv("GEMINI_GENERATION_MODEL", "models/gemini-3.1-flash-lite")

# --------------------------------------------------------------------------
# Logging Setup
# --------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice_trigger_api")

# Ensure APScheduler deserializes job refs identically across all import environments
sys.modules.setdefault("main", sys.modules[__name__])
sys.modules.setdefault("backend.main", sys.modules[__name__])

# --------------------------------------------------------------------------
# APScheduler Persistent Setup (Survives Backend Restarts)
# --------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheduled_jobs.sqlite")
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{DB_PATH}')
}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")


async def scheduled_trigger_job(trigger_id: str, duration_minutes: float):
    """Callback executed by APScheduler when a scheduled job time arrives."""
    logger.info(f"[SCHEDULER] Executing scheduled trigger job: '{trigger_id}' ({duration_minutes}m)")
    try:
        await execute_trigger_activation(
            trigger_id=trigger_id,
            duration_minutes=duration_minutes,
            source="internal_scheduler"
        )
    except Exception as e:
        logger.error(f"[SCHEDULER] Error firing scheduled job '{trigger_id}': {e}")


async def generate_gemini_embedding(text: str) -> Optional[list[float]]:
    """Generate 768-dim vector embedding using Google Gemini API."""
    if not text or not text.strip():
        return None
    api_key = os.getenv("GEMINI_API_KEY") or DEFAULT_GEMINI_KEY
    model = (os.getenv("GEMINI_EMBEDDING_MODEL") or DEFAULT_GEMINI_MODEL).replace("models/", "")
    dim = int(os.getenv("EMBEDDING_DIMENSION") or DEFAULT_EMBEDDING_DIM)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={api_key}"
    payload = {
        "output_dimensionality": dim,
        "content": {
            "parts": [{"text": text.strip()}]
        }
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("embedding", {}).get("values")
            else:
                logger.error(f"[GEMINI] Embedding error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"[GEMINI] Embedding request failed: {e}")
    return None


async def auto_embed_unembedded_transcripts_job():
    """Background task to detect and embed any Supabase transcripts missing embeddings."""
    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    gemini_key = os.getenv("GEMINI_API_KEY") or DEFAULT_GEMINI_KEY
    if not supabase_url or not supabase_key or not gemini_key:
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            query_url = f"{supabase_url}/rest/v1/speech_transcripts?embedding=is.null&transcript=not.is.null&select=id,session_id,transcript&limit=5&order=created_at.desc"
            resp = await client.get(query_url, headers=headers)
            if resp.status_code != 200:
                return
            rows = resp.json()
            if not rows or not isinstance(rows, list):
                return

            for row in rows:
                transcript_text = (row.get("transcript") or "").strip()
                if not transcript_text:
                    continue
                row_id = row.get("id")
                vector = await generate_gemini_embedding(transcript_text)
                if vector:
                    patch_headers = {**headers, "Prefer": "return=minimal"}
                    patch_url = f"{supabase_url}/rest/v1/speech_transcripts?id=eq.{row_id}"
                    patch_resp = await client.patch(patch_url, headers=patch_headers, json={"embedding": vector})
                    if patch_resp.status_code in (200, 204):
                        logger.info(f"[AUTO-EMBED] Stored {len(vector)}-dim Gemini embedding for row {row_id}")
    except Exception as e:
        logger.debug(f"[AUTO-EMBED] Scan error: {e}")


async def background_auto_embed_loop():
    """Continuous background loop checking for transcripts needing embedding every 15s."""
    await asyncio.sleep(5)
    while True:
        try:
            await auto_embed_unembedded_transcripts_job()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"[AUTO-EMBED LOOP] Error: {e}")
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to start and stop APScheduler and auto-embed background task."""
    if not scheduler.running:
        scheduler.start()
        logger.info(f"APScheduler initialized with SQLite job store at {DB_PATH}")
    embed_task = asyncio.create_task(background_auto_embed_loop())
    yield
    embed_task.cancel()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")


app = FastAPI(
    title="Voice Trigger API",
    description="Automated Voice Recording & Speech-to-Text Pipeline Trigger",
    version="1.2.1",
    lifespan=lifespan
)

# --------------------------------------------------------------------------
# CORS Configuration
# --------------------------------------------------------------------------
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if allowed_origins_env == "*":
    origins = ["*"]
else:
    origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
    allow_origins=origins if origins != ["*"] else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# In-Memory State & Lock
# --------------------------------------------------------------------------
trigger_state: dict[str, Any] = {
    "status": "IDLE",            # IDLE, ACTIVE, EXPIRED, COMPLETED
    "active": False,
    "trigger_id": None,
    "duration_seconds": None,
    "started_at": None,
    "expires_at": None,
    "transcript": None,
    "completed_at": None,
}

# Diagnostic store for most recent call to /trigger/start
last_received_call: dict[str, Any] = {
    "status": "none received yet",
    "timestamp": None,
    "source_ip": None,
    "endpoint": None,
    "headers": None,
    "raw_body": None,
    "parsed_json": None,
    "outcome": None,
}

active_websockets: Set[WebSocket] = set()


async def broadcast_state_change(event_name: str, payload: dict):
    """Notify all connected WebSockets of a state change."""
    if not active_websockets:
        return
    message = {"event": event_name, **payload}
    disconnected = set()
    for ws in list(active_websockets):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)
    for ws in disconnected:
        active_websockets.discard(ws)


def check_and_update_expiry():
    """Evaluate if current active trigger has exceeded its expires_at deadline."""
    if trigger_state["active"] and trigger_state["expires_at"]:
        now = datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(trigger_state["expires_at"])
            if now >= expires_at:
                trigger_state["active"] = False
                trigger_state["status"] = "EXPIRED"
                logger.info(f"Trigger {trigger_state['trigger_id']} expired at {now.isoformat()}")
        except Exception as e:
            logger.error(f"Error parsing expires_at: {e}")


def get_remaining_seconds() -> int:
    """Calculate remaining seconds until expiration for active sessions."""
    if trigger_state["active"] and trigger_state["expires_at"]:
        try:
            expires_at = datetime.fromisoformat(trigger_state["expires_at"])
            remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
            return max(0, int(remaining))
        except Exception:
            return 0
    return 0


# --------------------------------------------------------------------------
# Unified Internal Activation Routine
# Shared identically by /trigger/start, APScheduler, and /trigger/test-fire
# --------------------------------------------------------------------------
async def execute_trigger_activation(
    trigger_id: Optional[str] = None,
    duration_minutes: Optional[float] = None,
    duration_seconds: Optional[int] = None,
    source: str = "workbench"
) -> dict:
    check_and_update_expiry()

    # Reject if session is already active
    if trigger_state["active"]:
        remaining = get_remaining_seconds()
        logger.warning(f"Activation rejected: trigger '{trigger_state['trigger_id']}' is already ACTIVE")
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"A trigger session ({trigger_state['trigger_id']}) is already ACTIVE",
                "trigger_id": trigger_state["trigger_id"],
                "remaining_seconds": remaining,
            }
        )

    # Determine duration
    if duration_seconds is not None and duration_seconds > 0:
        total_seconds = duration_seconds
    elif duration_minutes is not None and duration_minutes > 0:
        total_seconds = int(duration_minutes * 60)
    else:
        total_seconds = 60  # Default 1 minute if omitted

    # Assign or auto-generate trigger_id
    if trigger_id and trigger_id.strip():
        assigned_id = trigger_id.strip()
    else:
        prefix = "TEST" if source == "manual_test_fire" else ("SCHED" if source == "internal_scheduler" else "WB")
        assigned_id = f"{prefix}_{int(time.time())}"

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=total_seconds)

    trigger_state["status"] = "ACTIVE"
    trigger_state["active"] = True
    trigger_state["trigger_id"] = assigned_id
    trigger_state["duration_seconds"] = total_seconds
    trigger_state["started_at"] = now.isoformat()
    trigger_state["expires_at"] = expires_at.isoformat()
    trigger_state["transcript"] = None
    trigger_state["completed_at"] = None

    logger.info(f"[{source.upper()}] Trigger STARTED: {assigned_id} for {total_seconds}s (expires: {expires_at.isoformat()})")

    response_payload = {
        "message": "Workflow started",
        "status": "ACTIVE",
        "active": True,
        "trigger_id": assigned_id,
        "duration_seconds": total_seconds,
        "started_at": trigger_state["started_at"],
        "expires_at": trigger_state["expires_at"],
        "remaining_seconds": total_seconds,
        "source": source
    }

    # Broadcast to connected WebSocket clients for zero-latency start
    await broadcast_state_change("TRIGGER_STARTED", response_payload)

    return response_payload


# --------------------------------------------------------------------------
# Request Models
# --------------------------------------------------------------------------
class TriggerStartRequest(BaseModel):
    trigger_id: Optional[str] = None
    duration_minutes: Optional[float] = Field(default=None, gt=0)
    duration_seconds: Optional[int] = Field(default=None, gt=0)


class TranscriptRequest(BaseModel):
    trigger_id: str = Field(..., min_length=1)
    transcript: str
    language_code: Optional[str] = "en-IN"
    audio_file_path: Optional[str] = None
    audio_duration_seconds: Optional[float] = None


class SaveSpeechTranscriptRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    transcript: str = Field(..., min_length=1)
    language_code: Optional[str] = "en-IN"
    audio_file_path: Optional[str] = None
    audio_duration_seconds: Optional[float] = None


class TestFireRequest(BaseModel):
    duration_minutes: Optional[float] = 1.0
    duration_seconds: Optional[int] = None
    trigger_id: Optional[str] = None


class ScheduleInternalRequest(BaseModel):
    trigger_id: Optional[str] = None
    start_at: str  # ISO-8601 datetime string
    duration_minutes: float = Field(default=1.0, gt=0)


class ChatWebhookProxyRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    conversation_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    webhook_url: Optional[str] = None


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/")
def home(request: Request):
    """
    If requested by browser (Accept: text/html), serve the frontend dashboard.
    If requested by API clients / tests (Accept: application/json), return service status JSON.
    """
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    check_and_update_expiry()
    return {
        "status": "online",
        "message": "Voice Trigger API is running",
        "active": trigger_state["active"],
        "session_status": trigger_state["status"],
        "trigger_id": trigger_state["trigger_id"],
    }


@app.get("/index.html")
def serve_index_html():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/style.css")
def serve_style_css():
    css_path = os.path.join(FRONTEND_DIR, "style.css")
    if os.path.exists(css_path):
        return FileResponse(css_path, media_type="text/css", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="style.css not found")


@app.get("/app.js")
def serve_app_js():
    js_path = os.path.join(FRONTEND_DIR, "app.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="app.js not found")


@app.get("/env.js")
def serve_env_js():
    safe_env = {
        "AI_WORKFLOW_WEBHOOK_URL": os.getenv("VITE_AI_WORKFLOW_WEBHOOK_URL") or os.getenv("AI_WORKFLOW_WEBHOOK_URL") or "https://api.agents.snsihub.ai/webhook/memora-chat",
        "AI_WORKFLOW_TEST_WEBHOOK_URL": os.getenv("VITE_AI_WORKFLOW_TEST_WEBHOOK_URL") or os.getenv("AI_WORKFLOW_TEST_WEBHOOK_URL") or "https://api.agents.snsihub.ai/webhook-test/memora-chat",
        "SUPABASE_URL": os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL,
        "SUPABASE_ANON_KEY": os.getenv("VITE_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY,
    }
    content = f"window.ENV = {json.dumps(safe_env, indent=2)};"
    return Response(content=content, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
def serve_api_config():
    return {
        "AI_WORKFLOW_WEBHOOK_URL": os.getenv("VITE_AI_WORKFLOW_WEBHOOK_URL") or os.getenv("AI_WORKFLOW_WEBHOOK_URL") or "https://api.agents.snsihub.ai/webhook/memora-chat",
        "AI_WORKFLOW_TEST_WEBHOOK_URL": os.getenv("VITE_AI_WORKFLOW_TEST_WEBHOOK_URL") or os.getenv("AI_WORKFLOW_TEST_WEBHOOK_URL") or "https://api.agents.snsihub.ai/webhook-test/memora-chat",
        "SUPABASE_URL": os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL,
        "SUPABASE_ANON_KEY": os.getenv("VITE_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY,
    }


@app.post("/api/workbench/audio-webhook")
async def audio_webhook_proxy(
    request: Request,
    file: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None),
    audio_file_path: Optional[str] = Form(None)
):
    target_url = request.headers.get("x-target-webhook-url") or os.getenv("AI_WORKFLOW_WEBHOOK_URL") or "https://api.agents.snsihub.ai/webhook/memora-chat"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {}
            data = {}
            if file:
                content = await file.read()
                files["file"] = (file.filename, content, file.content_type)
            if session_id:
                data["session_id"] = session_id
            if audio_file_path:
                data["audio_file_path"] = audio_file_path
            resp = await client.post(target_url, data=data, files=files if files else None)
            return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type", "application/json"))
    except Exception as e:
        logger.warning(f"Audio webhook forward warning: {e}")
        return JSONResponse({"status": "proxy_error", "detail": str(e)}, status_code=502)



@app.get("/health")
def health_check():
    """
    Basic reachability endpoint returning 200 OK.
    Confirms the backend is up and publicly reachable on Render.
    """
    check_and_update_expiry()
    return {
        "status": "ok",
        "service": "voice-trigger-backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_session": trigger_state["active"],
        "session_status": trigger_state["status"],
        "trigger_id": trigger_state["trigger_id"],
        "scheduler_running": scheduler.running if scheduler else False
    }


@app.get("/trigger/debug/last-received")
def get_last_received():
    """
    Lightweight diagnostic endpoint returning the timestamp, source IP,
    headers, and payload of the most recent call to /trigger/start.
    """
    if last_received_call["status"] == "none received yet":
        return {"status": "none received yet"}
    return last_received_call


@app.post("/trigger/start")
async def start_trigger(request: Request):
    """
    Called by Workbench's HTTP Request Node to initiate a voice capture window.
    Logs every incoming attempt with [TRIGGER-IN], updates diagnostic store,
    and calls the unified activation routine.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Source IP detection (respects proxy header X-Forwarded-For on Render)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    else:
        client_ip = "unknown"

    raw_bytes = await request.body()
    body_str = raw_bytes.decode("utf-8", errors="replace")

    # Required log format: [TRIGGER-IN] <timestamp> received from <ip> body=<json>
    log_line = f"[TRIGGER-IN] {now_iso} received from {client_ip} body={body_str}"
    logger.info(log_line)
    print(log_line, flush=True)

    # Parse JSON body
    try:
        body_json = json.loads(body_str) if body_str else {}
    except Exception as err:
        last_received_call.update({
            "status": "error",
            "timestamp": now_iso,
            "source_ip": client_ip,
            "headers": dict(request.headers),
            "raw_body": body_str,
            "parsed_json": None,
            "outcome": f"Invalid JSON decode error: {err}"
        })
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {err}")

    last_received_call.update({
        "status": "received",
        "timestamp": now_iso,
        "source_ip": client_ip,
        "headers": dict(request.headers),
        "raw_body": body_str,
        "parsed_json": body_json,
    })

    # --------------------------------------------------------------------------
    # AWS SNS (Simple Notification Service) Message Handling
    # --------------------------------------------------------------------------
    sns_msg_type = request.headers.get("x-amz-sns-message-type") or body_json.get("Type")
    if sns_msg_type == "SubscriptionConfirmation":
        subscribe_url = body_json.get("SubscribeURL")
        logger.info(f"[AWS-SNS] SubscriptionConfirmation received. Auto-confirming via SubscribeURL: {subscribe_url}")
        if subscribe_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    confirm_resp = await http_client.get(subscribe_url)
                    logger.info(f"[AWS-SNS] ConfirmSubscription response status: {confirm_resp.status_code}")
            except Exception as e:
                logger.error(f"[AWS-SNS] Failed to GET SubscribeURL: {e}")
        last_received_call["outcome"] = "AWS_SNS_CONFIRMED"
        return {"message": "Subscription confirmed successfully", "status": "confirmed"}

    elif sns_msg_type == "UnsubscribeConfirmation":
        logger.info("[AWS-SNS] UnsubscribeConfirmation received")
        last_received_call["outcome"] = "AWS_SNS_UNSUBSCRIBED"
        return {"message": "Unsubscribe confirmed successfully", "status": "unsubscribed"}

    elif sns_msg_type == "Notification":
        # AWS SNS wraps published payload in the 'Message' string
        inner_msg = body_json.get("Message")
        if isinstance(inner_msg, str) and inner_msg.strip().startswith("{"):
            try:
                inner_json = json.loads(inner_msg)
                if isinstance(inner_json, dict):
                    # Merge inner payload so trigger_id, duration_minutes, etc. are accessible
                    for k, v in inner_json.items():
                        body_json.setdefault(k, v)
            except Exception as e:
                logger.warning(f"[AWS-SNS] Could not parse inner JSON message: {e}")

    # Validate duration if provided (checks body then headers)
    dur_mins = body_json.get("duration_minutes")
    if dur_mins is None and request.headers.get("duration_minutes"):
        try:
            dur_mins = float(str(request.headers.get("duration_minutes")))
        except (ValueError, TypeError):
            pass

    dur_secs = body_json.get("duration_seconds")
    if dur_secs is None and request.headers.get("duration_seconds"):
        try:
            dur_secs = int(str(request.headers.get("duration_seconds")))
        except (ValueError, TypeError):
            pass

    if dur_mins is not None and dur_mins <= 0:
        last_received_call["outcome"] = "REJECTED_422: duration_minutes must be > 0"
        raise HTTPException(status_code=422, detail="duration_minutes must be greater than 0")
    if dur_secs is not None and dur_secs <= 0:
        last_received_call["outcome"] = "REJECTED_422: duration_seconds must be > 0"
        raise HTTPException(status_code=422, detail="duration_seconds must be greater than 0")

    trigger_id = body_json.get("trigger_id") or request.headers.get("trigger_id")

    try:
        res = await execute_trigger_activation(
            trigger_id=trigger_id,
            duration_minutes=dur_mins,
            duration_seconds=dur_secs,
            source="workbench"
        )
        last_received_call["outcome"] = "ACCEPTED"
        return res
    except HTTPException as he:
        last_received_call["outcome"] = f"REJECTED_{he.status_code}: {he.detail}"
        raise he


@app.post("/trigger/test-fire")
async def test_fire_trigger(data: Optional[TestFireRequest] = None):
    """
    Quick manual test trigger endpoint to fire a test session without waiting on Workbench.
    Internally calls the exact same activation routine as /trigger/start.
    """
    mins = data.duration_minutes if data and data.duration_minutes else 1.0
    secs = data.duration_seconds if data else None
    tid = data.trigger_id if (data and data.trigger_id) else None
    return await execute_trigger_activation(
        trigger_id=tid,
        duration_minutes=mins,
        duration_seconds=secs,
        source="manual_test_fire"
    )


@app.post("/trigger/schedule-internal")
async def schedule_internal_trigger(data: ScheduleInternalRequest):
    """
    Fallback internal scheduler: schedules a session activation to fire
    at a specific future time without relying on SNS Workbench.
    """
    try:
        clean_str = data.start_at.replace("Z", "+00:00")
        target_dt = datetime.fromisoformat(clean_str)
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime for start_at: {e}")

    now = datetime.now(timezone.utc)
    if target_dt <= now:
        raise HTTPException(
            status_code=400,
            detail=f"start_at must be in the future. Received {target_dt.isoformat()}, current UTC time is {now.isoformat()}"
        )

    job_id = data.trigger_id.strip() if (data.trigger_id and data.trigger_id.strip()) else f"SCHED_{int(time.time())}"

    scheduler.add_job(
        scheduled_trigger_job,
        'date',
        run_date=target_dt,
        args=[job_id, data.duration_minutes],
        id=job_id,
        replace_existing=True
    )

    logger.info(f"[SCHEDULER] Job '{job_id}' scheduled for {target_dt.isoformat()} (duration: {data.duration_minutes}m)")

    return {
        "status": "scheduled",
        "job_id": job_id,
        "start_at": target_dt.isoformat(),
        "duration_minutes": data.duration_minutes,
        "seconds_until_run": int((target_dt - now).total_seconds())
    }


@app.get("/trigger/schedule-internal/jobs")
def list_scheduled_jobs():
    """List all currently pending scheduled jobs in the internal scheduler."""
    jobs = []
    for job in scheduler.get_jobs():
        nrt = getattr(job, "next_run_time", None)
        jobs.append({
            "job_id": job.id,
            "next_run_time": nrt.isoformat() if nrt else None,
            "args": list(job.args) if job.args else []
        })
    return {"jobs": jobs}


@app.get("/trigger/status")
def trigger_status():
    """
    Queried by Frontend polling every few seconds to detect activation, countdown, and expiry.
    """
    check_and_update_expiry()
    return {
        "status": trigger_state["status"],
        "active": trigger_state["active"],
        "trigger_id": trigger_state["trigger_id"],
        "duration_seconds": trigger_state["duration_seconds"],
        "started_at": trigger_state["started_at"],
        "expires_at": trigger_state["expires_at"],
        "remaining_seconds": get_remaining_seconds(),
        "transcript": trigger_state["transcript"],
        "completed_at": trigger_state["completed_at"],
    }


@app.post("/trigger/transcript")
async def receive_transcript(data: TranscriptRequest):
    """
    Called automatically by frontend upon expires_at passing to submit the transcript.
    Sets status = COMPLETED.
    """
    # Verify trigger ID
    if not trigger_state["trigger_id"] or data.trigger_id != trigger_state["trigger_id"]:
        raise HTTPException(
            status_code=400,
            detail=f"Mismatched trigger ID. Expected: '{trigger_state['trigger_id']}', received: '{data.trigger_id}'"
        )

    now = datetime.now(timezone.utc)
    trigger_state["transcript"] = data.transcript
    trigger_state["status"] = "COMPLETED"
    trigger_state["active"] = False
    trigger_state["completed_at"] = now.isoformat()

    logger.info(f"Trigger COMPLETED: {data.trigger_id} with transcript length {len(data.transcript)}")

    # --------------------------------------------------------------------------
    # Persist to Supabase Database (public.speech_transcripts & public.voice_transcripts)
    # --------------------------------------------------------------------------
    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    saved_to_supabase = False
    lang_code = getattr(data, "language_code", None) or "en-IN"

    if supabase_url and supabase_key:
        try:
            import httpx
            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }
            # Primary: public.speech_transcripts
            st_payload = {
                "session_id": data.trigger_id,
                "transcript": data.transcript,
                "language_code": lang_code,
            }
            if data.audio_file_path:
                st_payload["audio_file_path"] = data.audio_file_path
            if data.audio_duration_seconds is not None:
                st_payload["audio_duration_seconds"] = data.audio_duration_seconds

            # Generate Gemini Vector Embedding
            try:
                emb_vector = await generate_gemini_embedding(data.transcript)
                if emb_vector:
                    st_payload["embedding"] = emb_vector
            except Exception as emb_e:
                logger.warning(f"[GEMINI] Embedding generation warning: {emb_e}")

            # Fallback/Legacy: public.voice_transcripts
            vt_payload = {
                "trigger_id": data.trigger_id,
                "transcript": data.transcript,
                "duration_seconds": trigger_state.get("duration_seconds") or data.audio_duration_seconds,
                "source": "voice_pipeline"
            }
            async with httpx.AsyncClient(timeout=8.0) as http_client:
                # Fire inserts
                resp_st = await http_client.post(f"{supabase_url}/rest/v1/speech_transcripts", headers=headers, json=st_payload)
                if resp_st.status_code in (200, 201):
                    saved_to_supabase = True
                    logger.info(f"[SUPABASE] Persisted transcript for '{data.trigger_id}' with embedding to speech_transcripts")
                elif resp_st.status_code not in (200, 201) and "embedding" in st_payload:
                    # Retry without embedding if column has not yet been added in Supabase
                    st_fallback = {k: v for k, v in st_payload.items() if k != "embedding"}
                    retry_resp = await http_client.post(f"{supabase_url}/rest/v1/speech_transcripts", headers=headers, json=st_fallback)
                    if retry_resp.status_code in (200, 201):
                        saved_to_supabase = True
                        logger.info(f"[SUPABASE] Persisted transcript without embedding (run add_vector_embeddings.sql to enable)")
                else:
                    logger.info(f"[SUPABASE] speech_transcripts table insert status: {resp_st.status_code}")
                
                # Also save to voice_transcripts
                await http_client.post(f"{supabase_url}/rest/v1/voice_transcripts", headers=headers, json=vt_payload)
        except Exception as db_err:
            logger.error(f"[SUPABASE] Database insert failed: {db_err}")

    response_payload = {
        "message": "Transcript accepted",
        "accepted": True,
        "status": "COMPLETED",
        "trigger_id": data.trigger_id,
        "transcript": data.transcript,
        "language_code": lang_code,
        "audio_file_path": data.audio_file_path,
        "completed_at": trigger_state["completed_at"],
        "persisted_to_database": saved_to_supabase
    }

    await broadcast_state_change("TRIGGER_COMPLETED", response_payload)

    return response_payload


@app.post("/trigger/result")
async def receive_transcript_alias(data: TranscriptRequest):
    """Alias for /trigger/transcript for backwards compatibility."""
    return await receive_transcript(data)


async def _async_insert_supabase_transcript(
    session_id: str,
    transcript: str,
    language_code: str,
    audio_file_path: Optional[str] = None,
    audio_duration_seconds: Optional[float] = None
):
    """Non-blocking asynchronous helper to save to Supabase speech_transcripts table."""
    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    if not supabase_url or not supabase_key:
        logger.warning("[SUPABASE] Skipping save: missing URL or Anon Key")
        return False
    try:
        import httpx
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        payload = {
            "session_id": session_id,
            "transcript": transcript,
            "language_code": language_code or "en-IN"
        }
        if audio_file_path:
            payload["audio_file_path"] = audio_file_path
        if audio_duration_seconds is not None:
            payload["audio_duration_seconds"] = audio_duration_seconds

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{supabase_url}/rest/v1/speech_transcripts", headers=headers, json=payload)
            if resp.status_code in (200, 201):
                logger.info(f"[SUPABASE] Background saved transcript for session '{session_id}' to speech_transcripts")
                return True
            else:
                logger.warning(f"[SUPABASE] speech_transcripts returned status {resp.status_code}: {resp.text}")
                return False
    except Exception as exc:
        logger.error(f"[SUPABASE] Non-blocking insert error: {exc}")
        return False


@app.post("/api/transcripts/save")
async def save_speech_transcript_endpoint(data: SaveSpeechTranscriptRequest):
    """
    Task 2 & Task 3 Endpoint:
    Can be called by the SNS Workbench HTTP Request Node or frontend fallback.
    Fires the Supabase insert independently in the background so it will never delay or block the AI Agent.
    """
    lang = data.language_code or "en-IN"
    # Run in background without awaiting so it doesn't block the caller
    asyncio.create_task(
        _async_insert_supabase_transcript(
            data.session_id,
            data.transcript,
            lang,
            data.audio_file_path,
            data.audio_duration_seconds
        )
    )
    return {
        "status": "queued",
        "session_id": data.session_id,
        "language_code": lang,
        "audio_file_path": data.audio_file_path,
        "message": "Transcript persistence task dispatched asynchronously"
    }


@app.get("/api/transcripts/history")
async def get_transcripts_history(limit: int = 20):
    """
    Task 4 Backend Proxy Endpoint:
    Fetches the last N rows from public.speech_transcripts (ordered by created_at DESC).
    Can also fall back to public.voice_transcripts if speech_transcripts is empty or not yet created.
    """
    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    if not supabase_url or not supabase_key:
        return {"transcripts": [], "source": "none"}

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1. Try public.speech_transcripts first
            st_url = f"{supabase_url}/rest/v1/speech_transcripts?select=*&order=created_at.desc&limit={limit}"
            resp = await client.get(st_url, headers=headers)
            if resp.status_code == 200:
                rows = resp.json()
                if rows and len(rows) > 0:
                    return {"transcripts": rows, "source": "speech_transcripts"}

            # 2. Fallback to public.voice_transcripts
            vt_url = f"{supabase_url}/rest/v1/voice_transcripts?select=*&order=created_at.desc&limit={limit}"
            vt_resp = await client.get(vt_url, headers=headers)
            if vt_resp.status_code == 200:
                vt_rows = vt_resp.json()
                # Normalize trigger_id -> session_id
                normalized = []
                for r in vt_rows:
                    normalized.append({
                        "id": r.get("id"),
                        "session_id": r.get("trigger_id") or r.get("session_id"),
                        "transcript": r.get("transcript"),
                        "language_code": r.get("language_code", "en-IN"),
                        "created_at": r.get("created_at")
                    })
                return {"transcripts": normalized, "source": "voice_transcripts"}
    except Exception as e:
        logger.error(f"[SUPABASE HISTORY] Error reading transcripts: {e}")

    return {"transcripts": [], "source": "error"}


@app.get("/api/transcripts/by-session/{session_id}")
async def get_transcripts_by_session(session_id: str, limit: int = 50):
    """
    Retrieve all transcripts from public.speech_transcripts that match a given session_id.
    Falls back to public.voice_transcripts (trigger_id column) if none found.

    Args:
        session_id: The session/trigger ID to filter by.
        limit: Maximum number of rows to return (default 50).

    Returns:
        { "transcripts": [...], "session_id": "...", "count": N, "source": "..." }
    """
    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)

    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=503, detail="Supabase configuration is missing.")

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1. Query public.speech_transcripts filtered by session_id
            st_url = (
                f"{supabase_url}/rest/v1/speech_transcripts"
                f"?session_id=eq.{session_id}"
                f"&select=*"
                f"&order=created_at.desc"
                f"&limit={limit}"
            )
            resp = await client.get(st_url, headers=headers)

            if resp.status_code == 200:
                rows = resp.json()
                if rows and len(rows) > 0:
                    logger.info(f"[SUPABASE] Found {len(rows)} transcript(s) for session_id='{session_id}' in speech_transcripts")
                    return {
                        "transcripts": rows,
                        "session_id": session_id,
                        "count": len(rows),
                        "source": "speech_transcripts"
                    }
            else:
                logger.warning(f"[SUPABASE] speech_transcripts query returned status {resp.status_code}: {resp.text}")

            # 2. Fallback: query public.voice_transcripts by trigger_id
            vt_url = (
                f"{supabase_url}/rest/v1/voice_transcripts"
                f"?trigger_id=eq.{session_id}"
                f"&select=*"
                f"&order=created_at.desc"
                f"&limit={limit}"
            )
            vt_resp = await client.get(vt_url, headers=headers)

            if vt_resp.status_code == 200:
                vt_rows = vt_resp.json()
                if vt_rows and len(vt_rows) > 0:
                    normalized = [
                        {
                            "id": r.get("id"),
                            "session_id": r.get("trigger_id") or r.get("session_id"),
                            "transcript": r.get("transcript"),
                            "language_code": r.get("language_code", "en-IN"),
                            "created_at": r.get("created_at")
                        }
                        for r in vt_rows
                    ]
                    logger.info(f"[SUPABASE] Found {len(normalized)} transcript(s) for trigger_id='{session_id}' in voice_transcripts (fallback)")
                    return {
                        "transcripts": normalized,
                        "session_id": session_id,
                        "count": len(normalized),
                        "source": "voice_transcripts"
                    }

            # Nothing found in either table
            return {
                "transcripts": [],
                "session_id": session_id,
                "count": 0,
                "source": "none"
            }

    except Exception as e:
        logger.error(f"[SUPABASE BY-SESSION] Error retrieving transcripts for session_id='{session_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch transcripts: {e}")


class SemanticSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10
    threshold: Optional[float] = 0.2


@app.post("/api/transcripts/search")
async def semantic_search_transcripts_endpoint(data: SemanticSearchRequest):
    """
    Search speech_transcripts semantically by text query using Gemini embeddings
    and Supabase match_speech_transcripts RPC.
    """
    if not data.query or not data.query.strip():
        raise HTTPException(status_code=400, detail="Query text cannot be empty")

    vector = await generate_gemini_embedding(data.query)
    if not vector:
        raise HTTPException(status_code=502, detail="Failed to generate query embedding via Gemini")

    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=503, detail="Supabase configuration missing")

    import httpx
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "query_embedding": vector,
        "match_threshold": data.threshold or 0.2,
        "match_count": data.limit or 10
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{supabase_url}/rest/v1/rpc/match_speech_transcripts", headers=headers, json=payload)
            if resp.status_code == 200:
                results = resp.json()
                return {"matches": results, "query": data.query, "count": len(results)}
            else:
                logger.error(f"[SEMANTIC SEARCH] RPC error {resp.status_code}: {resp.text}")
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SEMANTIC SEARCH] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def generate_gemini_rag_response(query: str, context_chunks: list[dict]) -> str:
    """
    Generate an answer using Google Gemini 3.1 Flash Lite based on retrieved transcripts context.
    """
    api_key = os.getenv("GEMINI_API_KEY") or DEFAULT_GEMINI_KEY
    model = (os.getenv("GEMINI_GENERATION_MODEL") or DEFAULT_GEMINI_GENERATION_MODEL).replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    context_lines = []
    for idx, chunk in enumerate(context_chunks, 1):
        sess = chunk.get("session_id") or "UNKNOWN"
        created = chunk.get("created_at") or ""
        sim = chunk.get("similarity")
        sim_str = f" (relevance: {round(sim * 100, 1)}%)" if sim is not None else ""
        transcript = chunk.get("transcript") or ""
        context_lines.append(f"[Source {idx} | Session: {sess}{sim_str} | Time: {created}]:\n\"{transcript}\"")

    context_str = "\n\n".join(context_lines) if context_lines else "(No relevant speech transcripts found.)"

    system_instruction = (
        "You are an intelligent AI assistant answering questions about recorded voice notes and speech transcripts.\n"
        "Analyze the provided transcript context to provide accurate, factual, and helpful responses.\n"
        "- If the answer is found in the transcripts, quote or summarize it and reference the session ID.\n"
        "- If the information is partial or ambiguous, explain what is known from the transcripts.\n"
        "- If the transcripts don't contain enough information to answer, state clearly that the recorded voice notes do not contain this information."
    )

    prompt = (
        f"{system_instruction}\n\n"
        f"--- CONTEXT TRANSCRIPTS ---\n"
        f"{context_str}\n\n"
        f"--- USER QUESTION ---\n"
        f"{query}\n\n"
        f"--- ANSWER ---"
    )

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 800
        }
    }

    primary_model = (os.getenv("GEMINI_GENERATION_MODEL") or DEFAULT_GEMINI_GENERATION_MODEL).replace("models/", "")
    models_to_try = [primary_model, "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    last_error = "Unknown error"
    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        for attempt in range(2):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=25.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            if parts and "text" in parts[0]:
                                return parts[0]["text"].strip()
                        return "No response text generated by Gemini."
                    elif resp.status_code == 503:
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        last_error = f"Gemini API {resp.status_code}: {resp.text}"
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(1.0)
    return f"AI generation error: {last_error}"


class RAGQueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    threshold: Optional[float] = 0.15
    session_id: Optional[str] = None


@app.post("/api/rag/query")
async def rag_query_endpoint(data: RAGQueryRequest):
    """
    RAG Endpoint using Gemini 3.1 Flash Lite:
    1. Embeds user query using Gemini (gemini-embedding-001).
    2. Performs vector cosine similarity retrieval in Supabase pgvector.
    3. Synthesizes an answer using Gemini 3.1 Flash Lite (gemini-3.1-flash-lite).
    """
    if not data.query or not data.query.strip():
        raise HTTPException(status_code=400, detail="Query text cannot be empty")

    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=503, detail="Supabase configuration missing")

    import httpx
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    retrieved_chunks = []
    vector = await generate_gemini_embedding(data.query)

    # 1. Attempt Vector Similarity Search via RPC match_speech_transcripts
    if vector:
        try:
            rpc_payload = {
                "query_embedding": vector,
                "match_threshold": data.threshold or 0.15,
                "match_count": data.top_k or 5
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                rpc_resp = await client.post(
                    f"{supabase_url}/rest/v1/rpc/match_speech_transcripts",
                    headers=headers,
                    json=rpc_payload
                )
                if rpc_resp.status_code == 200:
                    retrieved_chunks = rpc_resp.json()
        except Exception as e:
            logger.warning(f"[RAG] Vector RPC query failed, falling back to recent rows: {e}")

    # 2. Graceful Fallback: If vector matches are empty, retrieve recent transcripts
    if not retrieved_chunks:
        try:
            params = {
                "select": "id,session_id,transcript,language_code,created_at,audio_file_path,audio_duration_seconds",
                "order": "created_at.desc",
                "limit": str(data.top_k or 5)
            }
            if data.session_id:
                params["session_id"] = f"eq.{data.session_id}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                fb_resp = await client.get(
                    f"{supabase_url}/rest/v1/speech_transcripts",
                    headers=headers,
                    params=params
                )
                if fb_resp.status_code == 200:
                    retrieved_chunks = fb_resp.json()
        except Exception as fb_err:
            logger.error(f"[RAG] Fallback retrieval error: {fb_err}")

    # 3. Generate Answer with Gemini 3.1 Flash Lite
    answer = await generate_gemini_rag_response(data.query, retrieved_chunks)

    generation_model = os.getenv("GEMINI_GENERATION_MODEL") or DEFAULT_GEMINI_GENERATION_MODEL

    return {
        "query": data.query,
        "answer": answer,
        "sources": retrieved_chunks,
        "source_count": len(retrieved_chunks),
        "embedding_model": os.getenv("GEMINI_EMBEDDING_MODEL") or DEFAULT_GEMINI_MODEL,
        "generation_model": generation_model
    }


@app.post("/api/webhooks/supabase/embed-transcript")
async def supabase_webhook_embed_transcript(request: Request):
    """
    Supabase Database Webhook handler:
    Can be configured in Supabase (Database -> Webhooks) on speech_transcripts for INSERT/UPDATE.
    Automatically generates Gemini embedding and stores in the row.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    record = body.get("record") or {}
    row_id = record.get("id")
    transcript_text = (record.get("transcript") or "").strip()

    if not row_id or not transcript_text:
        return {"status": "skipped", "reason": "No row_id or transcript present"}

    # Avoid infinite loop if embedding already updated
    if record.get("embedding"):
        return {"status": "skipped", "reason": "Embedding already exists"}

    embedding = await generate_gemini_embedding(transcript_text)
    if not embedding:
        return {"status": "error", "detail": "Failed to generate Gemini embedding"}

    supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    supabase_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_KEY)
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=503, detail="Supabase configuration missing")

    import httpx
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            patch_res = await client.patch(
                f"{supabase_url}/rest/v1/speech_transcripts?id=eq.{row_id}",
                headers=headers,
                json={"embedding": embedding}
            )
            if patch_res.status_code in (200, 204):
                logger.info(f"[WEBHOOK] Saved Gemini embedding for row {row_id}")
                return {"status": "success", "row_id": row_id, "dimension": len(embedding)}
            else:
                logger.error(f"[WEBHOOK] Failed to update row {row_id}: {patch_res.status_code} {patch_res.text}")
                return {"status": "error", "code": patch_res.status_code, "detail": patch_res.text}
    except Exception as e:
        logger.error(f"[WEBHOOK] Error patching row {row_id}: {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/trigger/reset")
async def reset_trigger():
    """Reset trigger state back to IDLE (for testing and workbench resetting)."""
    trigger_state["status"] = "IDLE"
    trigger_state["active"] = False
    trigger_state["trigger_id"] = None
    trigger_state["duration_seconds"] = None
    trigger_state["started_at"] = None
    trigger_state["expires_at"] = None
    trigger_state["transcript"] = None
    trigger_state["completed_at"] = None

    logger.info("Trigger state reset to IDLE")

    response_payload = {
        "message": "Trigger state reset to IDLE",
        "status": "IDLE",
        "active": False,
    }

    await broadcast_state_change("TRIGGER_RESET", response_payload)

    return response_payload


# --------------------------------------------------------------------------
# OrgMind / SNS Agent Workbench AI Chat Webhook Proxy
# --------------------------------------------------------------------------
@app.post("/api/chat/webhook-proxy")
async def chat_webhook_proxy(data: ChatWebhookProxyRequest):
    """
    Forward chat messages to the SNS Agent Workbench Webhook Trigger.
    Ensures browser requests succeed without CORS restrictions.
    Accepts: { user_id, conversation_id, message, webhook_url? }
    Returns: { success: true, response: "AI generated response" }
    """
    if data.webhook_url is not None:
        target_url = data.webhook_url.strip()
    else:
        target_url = (os.getenv("AI_WORKFLOW_WEBHOOK_URL") or os.getenv("VITE_AI_WORKFLOW_WEBHOOK_URL") or "https://api.agents.snsihub.ai/webhook/memora-chat").strip()

    if not target_url:
        raise HTTPException(
            status_code=400,
            detail="No SNS Agent Workbench Webhook URL provided. Set AI_WORKFLOW_WEBHOOK_URL in environment or pass webhook_url."
        )

    payload = {
        "user_id": data.user_id,
        "conversation_id": data.conversation_id,
        "message": data.message
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                target_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            try:
                result_json = resp.json()
            except Exception:
                result_json = {"raw": resp.text}

            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Webhook returned error ({resp.status_code}): {resp.text}"
                )

            # Standardize response to { "success": true, "response": "..." }
            if isinstance(result_json, dict) and "response" in result_json:
                return {
                    "success": result_json.get("success", True),
                    "response": result_json["response"]
                }
            elif isinstance(result_json, dict) and "text" in result_json:
                return {
                    "success": True,
                    "response": result_json["text"]
                }
            elif isinstance(result_json, dict) and "message" in result_json:
                return {
                    "success": True,
                    "response": result_json["message"]
                }
            else:
                return {
                    "success": True,
                    "response": str(result_json) if not isinstance(result_json, str) else result_json
                }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[WEBHOOK PROXY] Communication error with {target_url}: {exc}")
        raise HTTPException(status_code=502, detail=f"Failed to communicate with SNS Webhook: {exc}")


# --------------------------------------------------------------------------
# WebSocket Endpoint for Real-Time Event Streaming
# --------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    try:
        # Send current status immediately upon connection
        check_and_update_expiry()
        await websocket.send_json({
            "event": "INITIAL_STATE",
            "status": trigger_state["status"],
            "active": trigger_state["active"],
            "trigger_id": trigger_state["trigger_id"],
            "remaining_seconds": get_remaining_seconds(),
            "expires_at": trigger_state["expires_at"],
        })
        while True:
            # Keep-alive heartbeat listener
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception:
        active_websockets.discard(websocket)


@app.websocket("/trigger/ws")
async def trigger_websocket_alias(websocket: WebSocket):
    await websocket_endpoint(websocket)