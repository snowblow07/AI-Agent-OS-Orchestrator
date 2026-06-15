import pytest
from fastapi.testclient import TestClient
import redis
import sqlite3

from app.orchestrator import app, generate_intent_hash, IntentPayload
from app.config import DB_PATH


client = TestClient(app)
r = redis.Redis(host='localhost', port=6379, decode_responses=True)


TEST_PAYLOAD = {
    "graph_state_id": "test_state_1",
    "node_id": "test_node_1",
    "telemetry_event_id": "test_event_1",
    "tool_name": "ping_hardware",
    "args": {"device_ip": "10.0.0.1"},
    "parent_intent_hash": None
}


@pytest.fixture(autouse=True)
def setup_and_teardown():
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))

    # Redis cleanup
    r.delete(f"resolved:{intent_hash}")
    r.delete(f"failures:{intent_hash}")
    r.delete(f"lease:{intent_hash}")

    yield

    # SQLite cleanup
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM execution_log WHERE intent_hash = ?",
        (intent_hash,)
    )
    conn.commit()
    conn.close()


def test_initial_execution_success():
    response = client.post("/execute", json=TEST_PAYLOAD)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "SUCCESS"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_type FROM execution_log WHERE intent_hash = ?",
        (data["intent_hash"],)
    )
    events = [row[0] for row in cursor.fetchall()]
    conn.close()

    assert "IntentRegistered" in events
    assert "ExecutionSucceeded" in events


def test_idempotency_deduplication():
    client.post("/execute", json=TEST_PAYLOAD)

    response = client.post("/execute", json=TEST_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["status"] == "DEDUPLICATED"


def test_circuit_breaker_quarantine():
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))

    r.set(f"failures:{intent_hash}", 5)

    response = client.post("/execute", json=TEST_PAYLOAD)

    assert response.status_code == 423
    assert "QUARANTINED" in response.json()["detail"]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_type FROM execution_log WHERE intent_hash = ? AND event_type = 'IntentQuarantined'",
        (intent_hash,)
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_single_flight_lease_lock():
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))

    r.set(f"lease:{intent_hash}", "active", ex=30, nx=True)

    response = client.post("/execute", json=TEST_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["status"] == "LOCKED"