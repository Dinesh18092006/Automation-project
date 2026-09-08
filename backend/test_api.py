import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest
from fastapi.testclient import TestClient
from main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_full_lifecycle(client):
    print("\n--- Running Backend Lifecycle Test ---")
    
    # 1. Reset state
    res = client.post("/trigger/reset")
    assert res.status_code == 200
    assert res.json()["status"] == "IDLE"
    print("[PASS] Reset verified")

    # 2. Check health endpoint
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "online"
    print("[PASS] Health check verified")

    # 3. Start a trigger with 2 seconds duration
    res = client.post("/trigger/start", json={"trigger_id": "TEST_001", "duration_seconds": 2})
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is True
    assert data["status"] == "ACTIVE"
    assert data["trigger_id"] == "TEST_001"
    print(f"[PASS] Trigger started: {data['trigger_id']} (expires in {data['duration_seconds']}s)")

    # 4. Attempt to start duplicate trigger while active -> must return 409
    res = client.post("/trigger/start", json={"trigger_id": "TEST_002", "duration_minutes": 1})
    assert res.status_code == 409
    print("[PASS] Duplicate active trigger rejected with 409 Conflict")

    # 5. Check status immediately -> should be active
    res = client.get("/trigger/status")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["active"] is True
    assert status_data["status"] == "ACTIVE"
    print(f"[PASS] Active status confirmed (remaining: {status_data['remaining_seconds']}s)")

    # 6. Wait for expiration (2.5 seconds)
    print("Waiting 2.5 seconds for trigger expiration...")
    time.sleep(2.5)

    # 7. Check status after expiration -> should auto-expire
    res = client.get("/trigger/status")
    assert res.status_code == 200
    expired_data = res.json()
    assert expired_data["active"] is False
    assert expired_data["status"] == "EXPIRED"
    print("[PASS] Auto-expiration verified on GET /trigger/status")

    # 8. Submit transcript with mismatched trigger ID -> must fail 400
    res = client.post("/trigger/transcript", json={"trigger_id": "WRONG_ID", "transcript": "some text"})
    assert res.status_code == 400
    print("[PASS] Mismatched trigger ID rejected with 400 Bad Request")

    # 9. Submit transcript with correct trigger ID
    transcript_text = "Testing voice trigger automation speech-to-text pipeline."
    res = client.post("/trigger/transcript", json={"trigger_id": "TEST_001", "transcript": transcript_text})
    assert res.status_code == 200
    comp_data = res.json()
    assert comp_data["accepted"] is True
    assert comp_data["status"] == "COMPLETED"
    print("[PASS] Transcript submitted and accepted")

    # 10. Final status check
    res = client.get("/trigger/status")
    assert res.status_code == 200
    final_data = res.json()
    assert final_data["status"] == "COMPLETED"
    assert final_data["transcript"] == transcript_text
    print("[PASS] Final COMPLETED state confirmed")

    print("\nAll Backend Lifecycle Tests Passed Successfully!")

def test_workbench_trigger_format(client):
    print("\n--- Running Workbench Payload Test ---")
    client.post("/trigger/reset")
    
    # Workbench fires POST /trigger/start with only duration_minutes
    res = client.post("/trigger/start", json={"duration_minutes": 0.05})
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is True
    assert data["status"] == "ACTIVE"
    assert data["trigger_id"].startswith("WB_")
    assert data["duration_seconds"] == 3
    print(f"[PASS] Workbench auto trigger_id generated: {data['trigger_id']}")
    
    # Cleanup
    client.post("/trigger/reset")

def test_diagnostics_and_reachability(client):
    print("\n--- Running Diagnostics & Reachability Tests ---")
    
    # 1. Health check
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
    print("[PASS] GET /health verified")

    # 2. Debug last-received initially
    client.post("/trigger/reset")
    # Fire a start request to verify it captures metadata
    res = client.post("/trigger/start", json={"trigger_id": "DEBUG_TEST_01", "duration_seconds": 10})
    assert res.status_code == 200

    res = client.get("/trigger/debug/last-received")
    assert res.status_code == 200
    debug_data = res.json()
    assert debug_data["status"] == "received"
    assert debug_data["source_ip"] is not None
    assert debug_data["parsed_json"]["trigger_id"] == "DEBUG_TEST_01"
    assert debug_data["outcome"] == "ACCEPTED"
    print("[PASS] GET /trigger/debug/last-received verified")

    # Reset
    client.post("/trigger/reset")

def test_manual_test_fire_and_scheduler(client):
    print("\n--- Running Manual Test Fire & Internal Scheduler Tests ---")
    client.post("/trigger/reset")

    # 1. Manual test-fire
    res = client.post("/trigger/test-fire", json={"duration_minutes": 0.5})
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is True
    assert data["status"] == "ACTIVE"
    assert data["source"] == "manual_test_fire"
    assert data["duration_seconds"] == 30
    print(f"[PASS] POST /trigger/test-fire verified: {data['trigger_id']}")

    # Reset
    client.post("/trigger/reset")

    # 2. Schedule internal job for future
    from datetime import datetime, timedelta, timezone
    future_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    res = client.post("/trigger/schedule-internal", json={
        "trigger_id": "TEST_SCHED_01",
        "start_at": future_time,
        "duration_minutes": 2.0
    })
    assert res.status_code == 200
    sched_data = res.json()
    assert sched_data["status"] == "scheduled"
    assert sched_data["job_id"] == "TEST_SCHED_01"
    print("[PASS] POST /trigger/schedule-internal verified")

    # 3. List scheduled jobs
    res = client.get("/trigger/schedule-internal/jobs")
    assert res.status_code == 200
    jobs_data = res.json()
    assert any(j["job_id"] == "TEST_SCHED_01" for j in jobs_data["jobs"])
    print("[PASS] GET /trigger/schedule-internal/jobs verified")

    # Cleanup
    client.post("/trigger/reset")


def test_chat_webhook_proxy(client):
    """Verify OrgMind AI chat webhook proxy endpoint validation."""
    # 1. Validation error when missing required fields
    res = client.post("/api/chat/webhook-proxy", json={
        "user_id": "",
        "conversation_id": "conv_123",
        "message": ""
    })
    assert res.status_code == 422  # Pydantic validation error

    # 2. Validation error when no webhook URL is configured
    res = client.post("/api/chat/webhook-proxy", json={
        "user_id": "usr_test_123",
        "conversation_id": "conv_123",
        "message": "Hello OrgMind",
        "webhook_url": ""
    })
    assert res.status_code == 400
    assert "No SNS Agent Workbench Webhook URL" in res.json()["detail"]
    print("[PASS] POST /api/chat/webhook-proxy validation verified")


def test_aws_sns_integration(client):
    """Verify AWS SNS SubscriptionConfirmation and Notification handling."""
    # 1. Test SubscriptionConfirmation
    res = client.post(
        "/trigger/start",
        headers={"x-amz-sns-message-type": "SubscriptionConfirmation"},
        json={
            "Type": "SubscriptionConfirmation",
            "MessageId": "123-abc",
            "Token": "2336412f37fb687f5d51e6e241d09c805a5a57e30d718b7346163f3",
            "TopicArn": "arn:aws:sns:us-east-1:123456789012:MyTopic",
            "Message": "You have chosen to subscribe to the topic",
            "SubscribeURL": ""  # empty so test doesn't make external call
        }
    )
    assert res.status_code == 200
    assert res.json()["status"] == "confirmed"
    print("[PASS] AWS SNS SubscriptionConfirmation auto-handled")

    # 2. Test Notification with wrapped JSON payload
    res = client.post(
        "/trigger/start",
        headers={"x-amz-sns-message-type": "Notification"},
        json={
            "Type": "Notification",
            "MessageId": "456-def",
            "TopicArn": "arn:aws:sns:us-east-1:123456789012:MyTopic",
            "Message": json.dumps({"trigger_id": "SNS_NOTIF_01", "duration_seconds": 10})
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ACTIVE"
    assert data["trigger_id"] == "SNS_NOTIF_01"
    print("[PASS] AWS SNS Notification with JSON payload unwrapped and activated")

    # Cleanup
    client.post("/trigger/reset")


if __name__ == "__main__":
    with TestClient(app) as test_client:
        test_full_lifecycle(test_client)
        test_workbench_trigger_format(test_client)
        test_diagnostics_and_reachability(test_client)
        test_manual_test_fire_and_scheduler(test_client)
        test_chat_webhook_proxy(test_client)
        test_aws_sns_integration(test_client)
