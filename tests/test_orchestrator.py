import pytest
from fastapi.testclient import TestClient
import redis
import sqlite3
import json
from app.orchestrator import app, generate_intent_hash, IntentPayload

# Initialize test clients
client = TestClient(app)
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Standardized test payload
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
    """Clear Redis and SQLite test data before and after each test."""
    # Setup: Clean Redis keys related to our test payload
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))
    r.delete(f"resolved:{intent_hash}")
    r.delete(f"failures:{intent_hash}")
    r.delete(f"lease:{intent_hash}")
    
    yield # Run the test
    
    # Teardown: Clean up the database
    conn = sqlite3.connect('agent_os_events.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM execution_log WHERE intent_hash = ?", (intent_hash,))
    conn.commit()
    conn.close()

def test_initial_execution_success():
    """Validates that a fresh intent is executed and logged."""
    response = client.post("/execute", json=TEST_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    
    # Verify the immutable ledger recorded the event
    conn = sqlite3.connect('agent_os_events.db')
    cursor = conn.cursor()
    cursor.execute("SELECT event_type FROM execution_log WHERE intent_hash = ?", (data["intent_hash"],))
    events = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    assert "IntentRegistered" in events
    assert "ExecutionSucceeded" in events

def test_idempotency_deduplication():
    """Validates that identical payloads are blocked from duplicate execution."""
    # First call
    client.post("/execute", json=TEST_PAYLOAD)
    
    # Second call with the exact same payload
    response_two = client.post("/execute", json=TEST_PAYLOAD)
    assert response_two.status_code == 200
    assert response_two.json()["status"] == "DEDUPLICATED"

def test_circuit_breaker_quarantine():
    """Validates that an intent is quarantined after 5 failures."""
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))
    
    # Manually inject 5 failures into Redis
    r.set(f"failures:{intent_hash}", 5)
    
    # Attempt execution
    response = client.post("/execute", json=TEST_PAYLOAD)
    
    assert response.status_code == 423
    assert "QUARANTINED" in response.json()["detail"]
    
    # Verify the quarantine event was logged to SQLite
    conn = sqlite3.connect('agent_os_events.db')
    cursor = conn.cursor()
    cursor.execute("SELECT event_type FROM execution_log WHERE intent_hash = ? AND event_type = 'IntentQuarantined'", (intent_hash,))
    assert cursor.fetchone() is not None
    conn.close()

def test_single_flight_lease_lock():
    """Validates that concurrent executions are blocked by the Redis mutex."""
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))
    
    # Manually acquire the lease to simulate another worker currently executing
    r.set(f"lease:{intent_hash}", "active", ex=30, nx=True)
    
    response = client.post("/execute", json=TEST_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["status"] == "LOCKED"