import pytest
from fastapi.testclient import TestClient
import redis
import sqlite3

from app.main import app
from app.core import generate_intent_hash
from app.models import IntentPayload
from app.config import DB_PATH

client = TestClient(app)
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

TEST_PAYLOAD = {
    "graph_state_id": "live_state_001",
    "node_id": "live_node_001",
    "telemetry_event_id": "live_event_001",
    "tool_name": "ping_hardware",
    "args": {"device_ip": "10.0.0.1"},
    "parent_intent_hash": None
}

@pytest.fixture(autouse=True)
def setup_and_teardown():
    intent_hash = generate_intent_hash(IntentPayload(**TEST_PAYLOAD))
    r.delete(f"resolved:{intent_hash}")
    r.delete(f"failures:{intent_hash}")
    r.delete(f"lease:{intent_hash}")
    yield
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM execution_log WHERE intent_hash = ?", (intent_hash,))
    conn.commit()
    conn.close()

def test_live_mcp_execution():
    """Validates that the orchestrator spins up the MCP server and captures physical tool output."""
    
    # Note the updated prefixed route from the APIRouter
    response = client.post("/agent/execute", json=TEST_PAYLOAD)
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify core idempotency fields
    assert data["status"] == "SUCCESS"
    assert "intent_hash" in data
    
    # Verify the orchestrator received the physical stdout from mcp_server.py
    assert "10.0.0.1 is online" in data["result"]